import json
import unittest
from unittest.mock import Mock

from resources.lib.api import VideolandApi, ApiError, AuthError
from resources.lib.progress import ProgressWriter, heartbeat_config, monitor_class


CONFIG = {'polling': 240, 'session': {'videoId': 'clip_46228', 'clipId': 46228,
          'clipType': 'vi', 'clipDuration': 770, 'programId': '3341'}, 'view': {'clipId': 46228}}


class ProgressTests(unittest.TestCase):
    def writer(self):
        client = Mock()
        client.session_expired.return_value = False
        client.progress_session.return_value = 'session'
        client.progress_view.return_value = {}
        return ProgressWriter(client, {'uid': 'user'}, 'original-profile', CONFIG,
                              'https://v2.videoland.com/casper-en-emma-p_3341/seizoen-1-c_46228')

    def test_api_matches_har_and_uses_current_identity(self):
        client = VideolandApi('test')
        client.token = 'profile-token'
        client._request = Mock(return_value={'sessionId': 'session'})
        self.assertEqual(client.progress_session('user', CONFIG['session']), 'session')
        url, headers, data = client._request.call_args.args
        self.assertTrue(url.endswith('/notify/session'))
        self.assertEqual(headers['Authorization'], 'Bearer profile-token')
        self.assertEqual(json.loads(data)['clipDuration'], 770)
        client.progress_view('user', {'uid': 'wrong', 'tc': 347, 'sessionId': 'session'})
        url, headers, data = client._request.call_args.args
        self.assertTrue(url.endswith('/notify/view'))
        self.assertEqual(headers['Authorization'], 'Bearer profile-token')
        self.assertEqual(json.loads(data)['uid'], 'user')
        self.assertEqual(json.loads(data)['tc'], 347)

    def test_seek_backward_stop_and_end(self):
        w = self.writer()
        for position, reason in [(347, 'start'), (367, 'periodic'), (20, 'seek'), (21, 'stop'), (900, 'end')]:
            w.save(position, reason)
        views = [call.args[1] for call in w.client.progress_view.call_args_list]
        self.assertEqual([v['tc'] for v in views], [347, 367, 20, 21, 770])
        self.assertEqual([v['sequenceNumber'] for v in views], list(range(5)))
        self.assertEqual([v['tcRelative'] for v in views], [0, 20, 0, 1, 0])
        w.client.progress_session.assert_called_once()

    def test_auth_refresh_keeps_original_profile(self):
        w = self.writer()
        w.client.progress_view.side_effect = [AuthError('expired'), {}]
        w.save(123, 'seek')
        w.client.jwt.assert_called_once_with({'uid': 'user'}, 'original-profile')
        self.assertEqual(w.sequence, 1)

    def test_failure_does_not_advance_acknowledged_progress(self):
        w = self.writer()
        w.client.progress_view.side_effect = ApiError('offline')
        with self.assertRaises(ApiError):
            w.save(123, 'seek')
        self.assertEqual(w.sequence, 0)
        self.assertIsNone(w.previous)

    def test_heartbeat_only_for_selected_video(self):
        data = {'itemContent': {'video': {'id': 'clip_46228'}, 'analytics': {'heartbeat-v2': CONFIG}}}
        self.assertIsNone(heartbeat_config(data, 'clip_other'))
        result = heartbeat_config(data, 'clip_46228')
        result['view']['clipId'] = 1
        self.assertEqual(CONFIG['view']['clipId'], 46228)

    def test_monitor_captures_final_seek_and_ignores_other_playback(self):
        class Player:
            def isPlayingVideo(self): return True
            def getPlayingFile(self): return 'our-stream'
            def getTime(self): return 30
        class Monitor:
            def abortRequested(self): return False
            def waitForAbort(self, delay): raise AssertionError('all events should finish immediately')
        xbmc = Mock(Player=Player, Monitor=Monitor)
        w = self.writer()
        tracker = monitor_class(xbmc)(w, 'our-stream', lambda: True, Mock(), Mock())
        tracker.onAVStarted()
        tracker.onPlayBackSeek(123000, 93000)
        tracker.onPlayBackStopped()
        tracker.run()
        self.assertEqual([c.args[1]['tc'] for c in w.client.progress_view.call_args_list], [30, 123, 123])
        tracker.stream = 'different-stream'
        self.assertFalse(tracker.matches())

    def test_disabled_sync_never_writes(self):
        xbmc = Mock(Player=object)
        w = self.writer()
        tracker = monitor_class(xbmc)(w, 'stream', lambda: False, Mock(), Mock())
        tracker.position = 30
        tracker.submit('seek')
        self.assertTrue(tracker.writes.empty())

    def test_notification_setting_controls_success_and_failure(self):
        from test_auth import load_plugin
        plugin = load_plugin()
        plugin.SyncStore = Mock()
        config_layout = {'itemContent': {'video': {'id': 'clip_46228'},
                         'analytics': {'heartbeat-v2': CONFIG}}}
        constructor = Mock()
        plugin.monitor_class = Mock(return_value=constructor)
        plugin.setting = Mock(return_value='profile')
        settings = {'sync_progress': True, 'sync_notifications': False}
        plugin.setting_bool = lambda name, default: settings.get(name, default)
        plugin.ADDON.getLocalizedString.return_value = 'Saved {0}'
        plugin.progress_tracker(Mock(), {'uid': 'user'}, config_layout,
                                'clip_46228', 'location', 'stream')
        notify = constructor.call_args.args[3]
        notify(True, 347)
        notify(False, 347)
        plugin.xbmcgui.Dialog.return_value.notification.assert_not_called()
        settings['sync_notifications'] = True
        notify(True, 347)
        plugin.xbmcgui.Dialog.return_value.notification.assert_called_once_with(
            'Videoland', 'Saved 5:47', time=2500, sound=False)

    def test_worker_reports_failures_without_success_notice(self):
        xbmc = Mock(Player=object)
        w = self.writer()
        w.client.progress_view.side_effect = ApiError('offline')
        notify = Mock()
        tracker = monitor_class(xbmc)(w, 'stream', lambda: True, notify, Mock())
        tracker.writes.put((123, 'seek'))
        tracker.writes.put(None)
        tracker.write_loop()
        notify.assert_called_once_with(False, 123)
