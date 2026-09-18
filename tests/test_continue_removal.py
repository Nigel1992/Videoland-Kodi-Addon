import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from resources.lib.api import ApiError, VideolandApi
from resources.lib.sync_store import SyncStore, DurableWriter
from test_auth import load_plugin
from test_progress import CONFIG


ACTION = {'target': {'type': 'app', 'value_app': {
    'reference': 'remove_from_continuous_watching', 'details': {'id': '3341'}}}}


class ContinueRemovalTests(unittest.TestCase):
    def test_request_uses_visibility_endpoint_and_card_content_id(self):
        client = VideolandApi('test')
        client.token = 'profile-token'
        client._request = Mock(return_value={})
        client.remove_continue_watching('3341')
        args, kwargs = client._request.call_args
        self.assertEqual(args[0], 'https://heartbeat-v3.videoland.bedrock.tech/v3/rtlnl/m6group_web/watched_contents_visibility')
        self.assertEqual(args[1]['Authorization'], 'Bearer profile-token')
        self.assertEqual(json.loads(args[2]), {'3341': True})
        self.assertTrue(kwargs['allow_empty'])

    def test_removal_retries_gateway_errors_but_not_permanent_errors(self):
        for status in (502, 503, 504, 400, 403):
            with self.subTest(status=status):
                client = VideolandApi('test')
                error = ApiError('temporary' if status >= 500 else 'rejected')
                error.__cause__ = HTTPError('https://example.invalid', status, 'error', {}, None)
                self.addCleanup(error.__cause__.close)
                client._request = Mock(side_effect=[error, {}])
                with patch('resources.lib.api.time.sleep'):
                    if status >= 500:
                        self.assertEqual(client.remove_continue_watching('3341'), {})
                        self.assertEqual(client._request.call_count, 2)
                        self.assertEqual(client._request.call_args_list[0], client._request.call_args_list[1])
                    else:
                        with self.assertRaises(ApiError): client.remove_continue_watching('3341')
                        self.assertEqual(client._request.call_count, 1)

    def test_removal_stops_after_three_attempts(self):
        client = VideolandApi('test')
        error = ApiError('gateway timeout')
        error.__cause__ = HTTPError('https://example.invalid', 504, 'error', {}, None)
        self.addCleanup(error.__cause__.close)
        client._request = Mock(side_effect=error)
        with patch('resources.lib.api.time.sleep'), self.assertRaises(ApiError):
            client.remove_continue_watching('3341')
        self.assertEqual(client._request.call_count, 3)
        self.assertEqual(client._request.call_args.kwargs['timeout'], 10)

    def test_removal_retries_socket_timeout(self):
        client = VideolandApi('test')
        client._request = Mock(side_effect=[TimeoutError(), {}])
        with patch('resources.lib.api.time.sleep'):
            self.assertEqual(client.remove_continue_watching('3341'), {})
        self.assertEqual(client._request.call_count, 2)

    def test_empty_success_response_supported_only_when_requested(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b''
        with patch('resources.lib.api.urlopen', return_value=response):
            self.assertEqual(VideolandApi()._request('https://example.invalid', allow_empty=True), {})
            with self.assertRaises(ApiError):
                VideolandApi()._request('https://example.invalid')

    def test_context_menu_only_when_cloud_card_offers_removal(self):
        plugin = load_plugin()
        plugin.add = Mock()
        plugin.setting = Mock(return_value='profile')
        plugin.ADDON.getLocalizedString.return_value = 'Remove from Continue Watching'
        target = {'id':'clip_46228', 'type':'video'}
        card = {'title':'Casper en Emma', 'secondaryActions':[None,ACTION]}
        plugin._render_rows([(card, target, 'video', {})])
        menu = plugin.add.call_args.kwargs['context_menu']
        removal = next(entry for entry in menu if entry[1].startswith('RunPlugin('))
        self.assertEqual(removal[0], 'Remove from Continue Watching')
        params = parse_qs(urlsplit(removal[1][len('RunPlugin('):-1]).query)
        self.assertEqual(params['content_id'], ['3341'])
        self.assertEqual(params['profile_id'], ['profile'])
        plugin._render_rows([({'title':'Another title'}, target, 'video', {})])
        self.assertFalse(any(entry[1].startswith('RunPlugin(') for entry in plugin.add.call_args.kwargs['context_menu']))

    def test_stale_profile_menu_cannot_remove(self):
        plugin = load_plugin()
        plugin.setting = Mock(return_value='different-profile')
        plugin.ADDON.getLocalizedString.return_value = 'Profile changed'
        plugin.api = Mock()
        with self.assertRaises(ApiError):plugin.remove_continue_watching('3341','old-profile','Title')
        plugin.api.assert_not_called()

    def test_success_refreshes_and_failure_does_not_claim_success(self):
        for fail in (False, True):
            plugin = load_plugin()
            plugin.setting = Mock(return_value='profile')
            plugin.ADDON.getLocalizedString.return_value = 'Removed: {0}'
            client = Mock()
            plugin.api = lambda: client
            plugin.ensure_login = Mock(return_value={'uid':'account'})
            plugin.SyncStore = Mock()
            def remove(account, profile, content_id, callback):callback()
            plugin.SyncStore.return_value.remove_content.side_effect = remove
            if fail:client.remove_continue_watching.side_effect = ApiError('offline')
            with patch.object(plugin.VideolandApi, 'clear_cache') as clear:
                if fail:
                    with self.assertRaises(ApiError):plugin.remove_continue_watching('3341','profile','Title')
                    plugin.xbmcgui.Dialog.return_value.notification.assert_not_called()
                    plugin.xbmc.executebuiltin.assert_not_called()
                    clear.assert_not_called()
                else:
                    plugin.remove_continue_watching('3341','profile','Title')
                    client.remove_continue_watching.assert_called_once_with('3341')
                    plugin.xbmc.executebuiltin.assert_called_once_with('Container.Refresh')

    def test_removal_clears_matching_retries_and_blocks_old_playback_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncStore(directory)
            store.enqueue('account','profile',CONFIG,'location',123,'stop')
            other = copy.deepcopy(CONFIG);other['session']['programId']='999';other['session']['videoId']='clip_other'
            store.enqueue('account','profile',other,'location',40,'stop')
            store.enqueue('account','kids',CONFIG,'location',50,'stop')
            remove = Mock()
            store.remove_content('account','profile','3341',remove)
            remove.assert_called_once()
            self.assertEqual(store.status('account','profile')['pending'],1)
            self.assertEqual(store.status('account','kids')['pending'],1)
            self.assertIsNone(store.enqueue('account','profile',CONFIG,'location',124,'stop',started_at=0))
            self.assertIsNotNone(store.enqueue('account','profile',CONFIG,'location',130,'start',started_at=10**12))

    def test_failed_cloud_removal_preserves_pending_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncStore(directory)
            store.enqueue('account','profile',CONFIG,'location',123,'stop')
            with self.assertRaises(ApiError):
                store.remove_content('account','profile','3341',Mock(side_effect=ApiError('offline')))
            self.assertEqual(store.status('account','profile')['pending'],1)
            self.assertIsNotNone(store.enqueue('account','profile',CONFIG,'location',124,'stop',started_at=0))

    def test_listing_passes_context_actions_to_kodi(self):
        plugin = load_plugin()
        plugin.menu_icon = Mock(return_value=None)
        menu = [('Remove', 'RunPlugin(plugin://test?action=remove)')]
        plugin.add('Title','plugin://test',folder=False,context_menu=menu)
        plugin.xbmcgui.ListItem.return_value.addContextMenuItems.assert_called_once_with(menu)
