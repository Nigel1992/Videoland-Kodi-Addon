import importlib.util
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from test_auth import load_plugin
from test_resume import layout


class LocalHistoryTests(unittest.TestCase):
    def plugin(self):
        plugin = load_plugin()
        plugin.ADDON.getSettingString.side_effect = lambda key: 'local' if key == 'history_source' else ''
        return plugin

    def test_native_kodi_metadata_remains_unset(self):
        plugin = self.plugin()
        plugin.menu_icon = MagicMock(return_value=None)
        plugin.add('Episode', 'plugin://test?action=play', folder=False, playable=True)
        item = plugin.xbmcgui.ListItem.return_value
        item.getVideoInfoTag.return_value.setResumePoint.assert_not_called()
        item.getVideoInfoTag.return_value.setPlaycount.assert_not_called()
        self.assertNotIn(('OverrideInfotag', 'true'), [c.args for c in item.setProperty.call_args_list])

    def test_cloud_bookmark_duration_and_tracker_are_not_used(self):
        plugin = self.plugin()
        client = MagicMock()
        client.layout.return_value = layout(347)
        client.LICENSE_URL = 'https://example.invalid/license'
        client.upfront_token.return_value = 'test'
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
        plugin.ensure_profile = MagicMock()
        plugin.get_resume_position = MagicMock(side_effect=AssertionError('cloud resume read'))
        plugin.get_video_duration = MagicMock(side_effect=AssertionError('cloud duration read'))
        plugin.progress_tracker = MagicMock(side_effect=AssertionError('cloud tracker created'))
        with patch.dict('sys.modules', {'inputstreamhelper': MagicMock()}):
            plugin.play('clip_46228')
        plugin.xbmcgui.Dialog.return_value.yesnocustom.assert_not_called()
        item = plugin.xbmcgui.ListItem.return_value
        item.getVideoInfoTag.return_value.setResumePoint.assert_not_called()
        self.assertNotIn('StartOffset', [c.args[0] for c in item.setProperty.call_args_list])
        plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(plugin.HANDLE, True, item)

    def test_stale_cloud_actions_are_blocked(self):
        plugin = self.plugin()
        plugin.api = MagicMock(side_effect=AssertionError('cloud action'))
        plugin.continue_watching()
        plugin.remove_continue_watching('title', 'profile', 'Name')
        plugin.show_sync_status()
        plugin.api.assert_not_called()
        self.assertFalse(plugin.cloud_sync_enabled())
        self.assertIsNone(plugin.progress_tracker(None, None, {}, 'id', '', ''))

    def test_local_listing_excludes_cloud_continue_rail(self):
        plugin = self.plugin()
        item = {'title': 'Film', 'actions': [{'target': {'type': 'video', 'value': {'id': 'clip_1'}}}]}
        plugin.action_target = lambda item: {'type': 'video', 'id': 'clip_1'}
        block = {'analytics': {'tealium': {'from': 'feature.recommended_videos_by_user'}},
                 'content': {'items': [{'itemContent': item}]}}
        self.assertEqual(plugin._build_rows({'blocks': [block]}), [])
        block['analytics']['tealium']['from'] = 'catalogue'
        self.assertEqual(len(plugin._build_rows({'blocks': [block]})), 1)

    def test_retry_service_does_not_decrypt_or_send_in_local_mode(self):
        spec = importlib.util.spec_from_file_location('local_sync_service', 'resources/lib/sync_service.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {name: MagicMock() for name in ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs')}):
            spec.loader.exec_module(module)
        addon = MagicMock()
        addon.getSettingString.return_value = 'local'
        addon.getSettingBool.return_value = True
        module.decrypt_json = MagicMock(side_effect=AssertionError('should return first'))
        store = MagicMock()
        module.retry_pending(addon, '/unused', store)
        module.decrypt_json.assert_not_called()
        store.due.assert_not_called()

    def test_cloud_setting_dependencies(self):
        root = ET.parse('resources/settings.xml')
        self.assertEqual(root.find('.//setting[@id="history_source"]/default').text, 'cloud')
        for name in ('sync_progress', 'sync_status'):
            dependency = root.find('.//setting[@id="'+name+'"]/dependencies/dependency')
            self.assertEqual(dependency.get('setting'), 'history_source')
            self.assertEqual(dependency.text, 'cloud')
        conditions = root.findall('.//setting[@id="sync_notifications"]/dependencies/dependency/and/condition')
        self.assertEqual({c.get('setting'):c.text for c in conditions}, {'history_source':'cloud', 'sync_progress':'true'})
