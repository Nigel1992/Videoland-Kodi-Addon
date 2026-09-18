import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qsl, urlsplit

from test_auth import load_plugin

from resources.lib.api import ApiError, VideolandApi


def _iso(offset_minutes):
    return (datetime.now(timezone.utc).astimezone() + timedelta(minutes=offset_minutes)).isoformat()


def channel(cid, seo, title, image_id, epg=None):
    item = {
        "title": title,
        "channel": {"id": "hash", "title": title,
                    "image": {"id": image_id, "idsByRatio": {"1:1": image_id}}},
        "action": {"target": {"type": "layout", "value_layout": {
            "type": "live", "id": cid, "seo": seo}}},
    }
    if epg:
        item["epgBox"] = epg
    return {"itemContent": item}


EPG_GRID = {
    "blocks": [{
        "content": {"contentTemplateId": "HorizontalEpg", "items": [
            channel("videoland_rtl4", "rtl4", "RTL 4", "390237"),
            channel("videoland_rtl5", "rtl5", "RTL 5", "390238"),
            channel("videoland_telekids", "telekids", "TELEKIDS", "390243"),
            channel("videoland_rtl7", "rtl7", "RTL 7", "390239"),
            channel("videoland_rtl8", "rtl8", "RTL 8", "390240"),
            channel("videoland_rtlz", "rtlz", "RTL Z", "390241"),
            channel("videoland_event4", "event-4", "Boxing Gladiators", "390244"),
        ]},
    }],
}


def epg_program(start, end, title, extra):
    return {"start": {"date": _iso(start), "title": "06:30"},
            "end": {"date": _iso(end), "title": "06:36"},
            "title": title, "extraTitle": extra,
            "action": {"target": {"type": "modal",
                                  "value_modal": {"id": "dmlkZW9sYW5kX3J0bDQrOTk5KzIwMjY="}}},
            "progressBar": None}


EPG_GRID_GUIDE = {
    "blocks": [{
        "content": {"contentTemplateId": "HorizontalEpg", "items": [
            channel("videoland_rtl4", "rtl4", "RTL 4", "390237", epg=[
                epg_program(-30, 10, "EditieNL", "EditieNL"),
                epg_program(10, 40, "RTL Nieuws", "RTL Nieuws - 06:30 uur"),
            ]),
            channel("videoland_rtl5", "rtl5", "RTL 5", "390238"),
        ]},
    }],
}

LIVE_ASSET = {"format": "dashcenc", "provider": "delta", "quality": "hd",
              "path": "https://sr.live.videoland.bedrock.tech/out/v1/videoland/"
                      "videoland-rtl4/cmaf_cenc00/dash-long-hd.mpd",
              "drm": {"type": "software",
                      "config": {"contentId": "dashcenc_videoland_rtl4"}}}

LIVE_PLAYER = {"blocks": [{"content": {"contentTemplateId": "Player", "items": [
    {"itemContent": {"title": "SnowComing",
                     "video": {"id": "videoland_rtl4", "assets": [LIVE_ASSET]}}}
]}}]}


class LiveTvTests(unittest.TestCase):
    def test_channel_rows_are_flat_and_only_real_channels(self):
        plugin = load_plugin()
        rows = plugin._live_channel_rows(EPG_GRID)
        self.assertEqual([c for c, _, _, _ in rows],
                         ["videoland_rtl4", "videoland_rtl5", "videoland_telekids",
                          "videoland_rtl7", "videoland_rtl8", "videoland_rtlz"])
        self.assertFalse(any(c.startswith("videoland_event") for c, _, _, _ in rows))
        self.assertEqual(rows[0][2], "RTL 4")
        self.assertTrue(rows[0][3]["thumb"].endswith("/390237/raw"))

    def test_live_tv_renders_channels_as_playable_entries(self):
        plugin = load_plugin()
        client = MagicMock()
        client.layout.return_value = EPG_GRID
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={"uid": "user"})
        plugin.ensure_profile = MagicMock()
        plugin.add = MagicMock()
        plugin.live_tv()
        self.assertEqual(len(plugin.add.call_args_list), 6)
        for args in plugin.add.call_args_list:
            route = dict(parse_qsl(urlsplit(args.args[1]).query))
            self.assertEqual(route["action"], "play_live")
            self.assertIn("channel_id", route)
            self.assertIn("seo", route)
            self.assertTrue(args.kwargs["playable"])
        plugin.xbmcplugin.setContent.assert_called_once_with(plugin.HANDLE, "videos")
        plugin.xbmcplugin.endOfDirectory.assert_called_once_with(plugin.HANDLE, cacheToDisc=False)

    def test_live_stream_selects_direct_widevine_dash_asset(self):
        plugin = load_plugin()
        client = MagicMock()
        client.layout.return_value = LIVE_PLAYER
        asset = plugin._live_stream(client, "videoland_rtl4", "rtl4")
        client.layout.assert_called_once_with(
            "live", "rtl4", "https://v2.videoland.com/rtl4/live", complete=True)
        self.assertEqual(asset["provider"], "delta")
        self.assertTrue(asset["path"].endswith(".mpd"))

    def test_play_live_resolves_using_live_upfront_token(self):
        plugin = load_plugin()
        helper_module = MagicMock()
        helper = helper_module.Helper.return_value
        helper.inputstream_addon = "inputstream.adaptive"
        helper.check_inputstream.return_value = True
        client = MagicMock()
        client.layout.return_value = LIVE_PLAYER
        client.live_upfront_token.return_value = "live-token"
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={"uid": "user"})
        plugin.ensure_profile = MagicMock()
        with patch.dict(sys.modules, {"inputstreamhelper": helper_module}):
            plugin.play_live("videoland_rtl4", "rtl4")
        client.live_upfront_token.assert_called_once_with("user", "dashcenc_videoland_rtl4")
        plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(
            plugin.HANDLE, True, plugin.xbmcgui.ListItem.return_value)

    def test_legacy_epggrid_layout_redirects_to_live_zapper(self):
        plugin = load_plugin()
        plugin.live_tv = MagicMock()
        plugin.show_layout("frontspace", "epggrid")
        plugin.live_tv.assert_called_once_with()

    def test_live_drm_token_url_uses_videoland_root_service(self):
        api = VideolandApi("test-device")
        api._request = MagicMock(return_value={"token": "token"})
        api.live_upfront_token("uid", "dashcenc_videoland_rtl4")
        url = api._request.call_args.args[0]
        self.assertIn("services/videoland_root/users/uid/live/dashcenc_videoland_rtl4/upfront-token", url)
        with self.assertRaises(ApiError):
            api.live_upfront_token("uid", "bad id/")

    def test_live_tv_is_dispatched_and_play_live_router_works(self):
        plugin = load_plugin()
        plugin.live_tv = MagicMock()
        plugin.play_live = MagicMock()
        plugin.dispatch({"action": "live"})
        plugin.live_tv.assert_called_once_with()
        plugin.dispatch({"action": "play_live", "channel_id": "videoland_rtl4", "seo": "rtl4"})
        plugin.play_live.assert_called_once_with("videoland_rtl4", "rtl4")

    def test_live_guide_rows_picks_current_and_next_program(self):
        plugin = load_plugin()
        guides = plugin._live_guide_rows(EPG_GRID_GUIDE)
        self.assertIn("videoland_rtl4", guides)
        self.assertEqual(guides["videoland_rtl4"]["now"]["title"], "EditieNL")
        self.assertEqual(guides["videoland_rtl4"]["next"]["title"], "RTL Nieuws")
        self.assertNotIn("videoland_rtl5", guides)

    def test_live_tv_puts_current_and_next_program_in_channel_plot(self):
        plugin = load_plugin()
        client = MagicMock()
        client.layout.return_value = EPG_GRID_GUIDE
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={"uid": "user"})
        plugin.ensure_profile = MagicMock()
        plugin.add = MagicMock()
        plugin.live_tv()
        self.assertEqual(len(plugin.add.call_args_list), 2)
        plots = {}
        for c in plugin.add.call_args_list:
            route = dict(parse_qsl(urlsplit(c.args[1]).query))
            self.assertEqual(route.get("action"), "play_live")
            self.assertTrue(c.kwargs.get("playable"))
            self.assertTrue(c.kwargs.get("suppress_watched"))
            plots[route["channel_id"]] = c.args[4]["plot"]
        self.assertIn("Kijk live naar RTL 4.", plots["videoland_rtl4"])
        self.assertIn("Nu: EditieNL (06:30-06:36)", plots["videoland_rtl4"])
        self.assertNotIn("Nu: EditieNL - EditieNL", plots["videoland_rtl4"])
        self.assertIn("Vervolgens: RTL Nieuws - RTL Nieuws - 06:30 uur (06:30-06:36)",
                      plots["videoland_rtl4"])
        self.assertEqual(plots["videoland_rtl5"], "Kijk live naar RTL 5.")

    def test_live_tv_channel_entries_carry_no_watched_state(self):
        plugin = load_plugin()
        client = MagicMock()
        client.layout.return_value = EPG_GRID
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={"uid": "user"})
        plugin.ensure_profile = MagicMock()
        plugin.add = MagicMock()
        plugin.live_tv()
        self.assertEqual(len(plugin.add.call_args_list), 6)
        for c in plugin.add.call_args_list:
            route = dict(parse_qsl(urlsplit(c.args[1]).query))
            if route.get("action") == "play_live":
                self.assertTrue(c.kwargs.get("suppress_watched", False))

    def test_play_live_does_not_set_resume_or_progress(self):
        plugin = load_plugin()
        helper_module = MagicMock()
        helper = helper_module.Helper.return_value
        helper.inputstream_addon = "inputstream.adaptive"
        helper.check_inputstream.return_value = True
        client = MagicMock()
        client.layout.return_value = LIVE_PLAYER
        client.live_upfront_token.return_value = "live-token"
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={"uid": "user"})
        plugin.ensure_profile = MagicMock()
        with patch.dict(sys.modules, {"inputstreamhelper": helper_module}):
            plugin.play_live("videoland_rtl4", "rtl4")
        item = plugin.xbmcgui.ListItem.return_value
        props = [c.args[0] for c in item.setProperty.call_args_list]
        self.assertNotIn("StartOffset", props)
        tag = item.getVideoInfoTag.return_value
        tag.setResumePoint.assert_not_called()
        tag.setPlaycount.assert_not_called()


if __name__ == "__main__":
    unittest.main()