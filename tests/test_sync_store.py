import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch

from resources.lib.api import ApiError
from resources.lib.sync_store import SyncStore, DurableWriter
from test_progress import CONFIG
from test_auth import load_plugin


class SyncStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SyncStore(self.directory.name)

    def enqueue(self, position, account='account', profile='profile'):
        return self.store.enqueue(account, profile, CONFIG, 'https://v2.videoland.com/test', position, 'stop')

    def test_failed_save_survives_restart_then_retries_original_profile(self):
        key, revision = self.enqueue(123)
        with self.assertRaises(ApiError):
            self.store.deliver(key, Mock(side_effect=ApiError('offline')), revision)
        reopened = SyncStore(self.directory.name)
        self.assertEqual(reopened.status('account', 'profile')['pending'], 1)
        self.assertEqual(reopened.status('account', 'profile')['error'], 'connection')
        self.assertEqual(reopened.due('different-account', now=10**12), [])
        self.assertEqual(reopened.due('account', now=10**12), [('account', 'profile', 'clip_46228')])
        self.assertEqual(reopened.due('account', now=0), [])
        self.assertEqual(reopened.deliver(key, lambda data: data['position']), 123)
        state = reopened.status('account', 'profile')
        self.assertEqual(state['pending'], 0)
        self.assertEqual(state['position'], 123)
        self.assertIsNone(state['error'])

    def test_latest_position_replaces_old_even_for_backward_seek(self):
        key, old = self.enqueue(500)
        _, new = self.enqueue(20)
        send = Mock(return_value=20)
        self.assertIsNone(self.store.deliver(key, send, old))
        send.assert_not_called()
        self.store.deliver(key, send, new)
        self.assertEqual(send.call_args.args[0]['position'], 20)

    def test_disabling_sync_pauses_retries_and_signout_clears(self):
        key, revision = self.enqueue(30)
        send = Mock()
        self.store.deliver(key, send, revision, enabled=lambda: False)
        send.assert_not_called()
        self.assertEqual(self.store.status('account', 'profile')['pending'], 1)
        self.store.clear()
        self.assertEqual(self.store.status('account', 'profile')['pending'], 0)

    def test_profiles_keep_separate_positions(self):
        first, _ = self.enqueue(10)
        second, _ = self.enqueue(50, profile='kids')
        self.store.deliver(first, lambda data: data['position'])
        self.assertEqual(self.store.status('account', 'kids')['pending'], 1)
        self.store.deliver(second, lambda data: data['position'])
        self.assertEqual(self.store.status('account', 'profile')['position'], 10)
        self.assertEqual(self.store.status('account', 'kids')['position'], 50)

    def test_retry_cannot_finish_after_newer_live_save(self):
        key, _ = self.enqueue(100)
        entered, release = threading.Event(), threading.Event()
        calls, errors = [], []
        def slow_send(data):
            entered.set()
            self.assertTrue(release.wait(5))
            calls.append(data['position'])
            return data['position']
        def retry():
            try:self.store.deliver(key, slow_send)
            except Exception as exc:errors.append(exc)
        def newer():
            try:
                new_key, revision = self.enqueue(20)
                self.store.deliver(new_key, lambda data: calls.append(data['position']) or data['position'], revision)
            except Exception as exc:errors.append(exc)
        first = threading.Thread(target=retry);first.start()
        self.assertTrue(entered.wait(5))
        second = threading.Thread(target=newer);second.start()
        release.set();first.join(5);second.join(5)
        self.assertFalse(errors)
        self.assertEqual(calls, [100, 20])
        self.assertEqual(self.store.status('account', 'profile')['position'], 20)

    def test_durable_writer_does_not_store_credentials(self):
        writer = Mock(auth={'uid': 'account', 'signature': 'SECRET'}, profile_id='profile', config=CONFIG, duration=770)
        writer.location = 'https://v2.videoland.com/test'
        writer.save.side_effect = ApiError('offline')
        with self.assertRaises(ApiError):
            DurableWriter(writer, self.store).save(123, 'stop')
        with open(self.store.path, 'rb') as file:
            self.assertNotIn(b'SECRET', file.read())

    def test_service_retries_with_saved_profile_not_current_profile(self):
        key, _ = self.enqueue(123)
        spec = importlib.util.spec_from_file_location('sync_service_test', os.path.join(os.path.dirname(__file__), '../resources/lib/sync_service.py'))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {name: MagicMock() for name in ('xbmc','xbmcaddon','xbmcgui','xbmcvfs')}):
            spec.loader.exec_module(module)
        addon = Mock()
        addon.getSettingBool.side_effect = lambda name: name == 'sync_progress'
        addon.getSettingString.return_value = 'saved'
        module.decrypt_json = Mock(return_value={'uid': 'account'})
        client = Mock()
        module.VideolandApi = Mock(return_value=client)
        module.ProgressWriter = Mock()
        module.ProgressWriter.return_value.save.return_value = 123
        module.retry_pending(addon, self.directory.name, self.store)
        client.jwt.assert_called_once_with({'uid': 'account'}, 'profile')
        module.ProgressWriter.return_value.save.assert_called_once_with(123, 'seek')
        self.assertEqual(self.store.status('account','profile')['pending'], 0)

    def test_status_shows_last_success_and_pending_error(self):
        key, _ = self.enqueue(120)
        self.store.deliver(key, lambda data: data['position'])
        key, _ = self.enqueue(150)
        with self.assertRaises(ApiError):
            self.store.deliver(key, Mock(side_effect=ApiError('offline')))
        plugin = load_plugin()
        labels = {31060:'Actief profiel: {0}', 31062:'Status', 31067:'Laatst geslaagd: {0}', 31068:'Wachtende updates: {0}', 31069:'Fout: {0}', 31071:'Updates gepauzeerd', 31075:'Verbindingsfout'}
        plugin.ADDON.getLocalizedString.side_effect = labels.__getitem__
        plugin.data_dir = lambda: self.directory.name
        plugin.auth_data = lambda: {'uid':'account'}
        plugin.setting = lambda key: {'profile_id':'profile', 'profile_name':'Test'}[key]
        plugin.setting_bool = lambda key, default: False
        plugin.show_sync_status()
        body = plugin.xbmcgui.Dialog.return_value.textviewer.call_args.args[1]
        self.assertIn('2:00', body)
        self.assertIn('Wachtende updates: 1', body)
        self.assertIn('Actief profiel: Test', body)
        self.assertIn('gepauzeerd', body)



class NewMenuTests(unittest.TestCase):
    def test_continue_watching_bypasses_cache_and_filters_other_rails(self):
        plugin = load_plugin()
        client = Mock()
        block = {'analytics': {'tealium': {'from': 'feature.recommended_videos_by_user'}}}
        client.layout.return_value = {'blocks': [block, {'analytics': {'tealium': {'from': 'other'}}}]}
        plugin.api = lambda: client
        plugin.ensure_login = Mock(return_value={'uid': 'account'})
        plugin.ensure_profile = Mock()
        plugin.add = Mock()
        plugin._build_rows = Mock(return_value=['row'])
        plugin._render_rows = Mock()
        plugin.hero_art = Mock(return_value={})
        plugin.ADDON.getLocalizedString.return_value = "Continue Watching"
        plugin.continue_watching()
        self.assertIsNone(client.cache_dir)
        self.assertEqual(client.cache_ttl, 0)
        plugin._build_rows.assert_called_once_with({'blocks': [block]})
        plugin.xbmcplugin.endOfDirectory.assert_called_once_with(plugin.HANDLE, cacheToDisc=False)

    def test_active_profile_name_is_resolved_from_matching_id(self):
        plugin = load_plugin()
        plugin.setting = lambda name: {'profile_name':'', 'profile_id':'kids'}[name]
        plugin.save = Mock()
        client = Mock()
        client.profiles.return_value = [{'uid':'parent','username':'Parent'}, {'uid':'kids','username':'Kids'}]
        self.assertEqual(plugin.active_profile_name(client, {'uid':'account'}), 'Kids')
        client.jwt.assert_called_with({'uid':'account'}, 'kids')
        plugin.save.assert_called_once_with('profile_name','Kids')
