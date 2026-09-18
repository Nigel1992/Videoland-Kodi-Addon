"""Resume behaviour using the response shape in the Casper en Emma HAR."""
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from resources.lib.api import VideolandApi
from test_auth import load_plugin


def layout(position=347, video_id='clip_46228'):
    return {'blocks': [{'content': {'items': [{'itemContent': {
        'video': {'id': video_id, 'duration': 770, 'progress': {'tcResume': position},
                  'assets': [{'format': 'dash', 'path': 'https://example.invalid/video.mpd'}]}
    }}]}}]}


class ResumeTests(unittest.TestCase):
    def test_selected_episode_only(self):
        plugin = load_plugin()
        data = layout(99, 'clip_other')
        data['blocks'].extend(layout()['blocks'])
        self.assertEqual(plugin.get_resume_position(data, 'clip_46228'), 347)
        self.assertEqual(plugin.get_resume_position(data, 'clip_missing'), 0)

    def test_duration_belongs_to_selected_video(self):
        plugin = load_plugin()
        self.assertEqual(plugin.get_video_duration(layout(), 'clip_46228'), 770)
        self.assertEqual(plugin.get_video_duration(layout(), 'clip_other'), 0)

    def test_invalid_or_absent_progress(self):
        plugin = load_plugin()
        for value in (None, '347', True, -1, 0, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.assertEqual(plugin.get_resume_position(layout(value), 'clip_46228'), 0)
        self.assertEqual(plugin.get_resume_position({}, 'clip_46228'), 0)

    def test_video_layout_always_fetches_current_profile_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            client = VideolandApi('test', cache_dir=directory)
            client._request = MagicMock(side_effect=[layout(100), layout(347)])
            first = client.layout('video', 'clip_46228')
            second = client.layout('video', 'clip_46228')
            self.assertNotEqual(first, second)
            self.assertEqual(client._request.call_count, 2)
            client._request.reset_mock()
            client._request.side_effect = None
            client._request.return_value = {'blocks': []}
            client.layout()
            client.layout()
            self.assertEqual(client._request.call_count, 1)

    def test_resume_restart_and_no_progress(self):
        for position, answer, expected in ((347, 1, '347'), (347, 0, '0'), (0, 1, '0')):
            with self.subTest(position=position, answer=answer):
                plugin = load_plugin()
                client = MagicMock()
                client.layout.return_value = layout(position)
                client.LICENSE_URL = 'https://example.invalid/license'
                client.upfront_token.return_value = 'test'
                plugin.api = lambda: client
                plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
                plugin.ensure_profile = MagicMock()
                plugin.xbmcgui.Dialog.return_value.yesnocustom.return_value = answer
                with patch.dict('sys.modules', {'inputstreamhelper': MagicMock()}):
                    plugin.play('clip_46228')
                dialog = plugin.xbmcgui.Dialog.return_value.yesnocustom
                if position:
                    self.assertIn('5:47', dialog.call_args.args[1])
                else:
                    dialog.assert_not_called()
                plugin.xbmcgui.ListItem.return_value.getVideoInfoTag.return_value.setResumePoint.assert_called_once_with(float(expected), 770.0)
                plugin.xbmcgui.ListItem.return_value.setProperty.assert_any_call('StartOffset', expected)
                plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(
                    plugin.HANDLE, True, plugin.xbmcgui.ListItem.return_value)

    def test_dismissed_resume_dialog_never_plays_or_syncs(self):
        for answer in (-1, 2, None):
            with self.subTest(answer=answer):
                plugin = load_plugin()
                client = MagicMock()
                client.layout.return_value = layout()
                plugin.api = lambda: client
                plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
                plugin.ensure_profile = MagicMock()
                plugin.video_assets = MagicMock()
                plugin.progress_tracker = MagicMock()
                plugin.xbmcgui.Dialog.return_value.yesnocustom.return_value = answer
                with patch.dict('sys.modules', {'inputstreamhelper': MagicMock()}):
                    plugin.play('clip_46228')
                plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(
                    plugin.HANDLE, False, plugin.xbmcgui.ListItem.return_value)
                plugin.video_assets.assert_not_called()
                client.upfront_token.assert_not_called()
                plugin.progress_tracker.assert_not_called()
                client.progress_session.assert_not_called()
                client.progress_view.assert_not_called()

    def test_browse_items_explicitly_suppress_local_progress(self):
        plugin = load_plugin()
        plugin.menu_icon = MagicMock(return_value=None)
        plugin.add('Episode', 'plugin://test?action=play', folder=False,
                   playable=True, info={'title': 'Episode'})
        item = plugin.xbmcgui.ListItem.return_value
        item.getVideoInfoTag.return_value.setPlaycount.assert_called_once_with(0)
        item.getVideoInfoTag.return_value.setResumePoint.assert_called_once_with(0.0, 1.0)
        item.setProperty.assert_any_call('ForceResolvePlugin', 'true')
        item.setProperty.assert_any_call('OverrideInfotag', 'true')

    def test_playback_refreshes_only_our_visible_listing(self):
        for path, playing, refresh in [('plugin://test?series=1', False, True),
                                       ('plugin://another', False, False),
                                       ('plugin://test?series=1', True, False)]:
            with self.subTest(path=path, playing=playing):
                plugin = load_plugin()
                client = MagicMock()
                client.layout.return_value = layout(0)
                client.LICENSE_URL = 'https://example.invalid/license'
                client.upfront_token.return_value = 'test'
                plugin.api = lambda: client
                plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
                plugin.ensure_profile = MagicMock()
                tracker = MagicMock()
                plugin.progress_tracker = MagicMock(return_value=tracker)
                plugin.xbmc.Player.return_value.isPlaying.return_value = playing
                plugin.xbmc.getInfoLabel.return_value = path
                with patch.dict('sys.modules', {'inputstreamhelper': MagicMock()}):
                    plugin.play('clip_46228')
                tracker.run.assert_called_once()
                if refresh:
                    plugin.xbmc.executebuiltin.assert_called_once_with('Container.Refresh')
                else:
                    plugin.xbmc.executebuiltin.assert_not_called()
