import unittest

from resources.lib.api import (
    VideolandApi,
    action_target,
    is_related_block,
    navigation_entries,
    video_assets,
    walk_item_content,
)


SAMPLE = {
    "blocks": [{"content": {"items": [{"itemContent": {
        "title": "Example",
        "action": {"target": {"type": "layout", "value_layout": {"type": "video", "id": "clip_1"}}},
        "video": {"id": "clip_1", "assets": [{"format": "dash", "path": "https://example.invalid/test.mpd"}]},
    }}]}}]
}


class LayoutParsingTests(unittest.TestCase):
    def test_walk_and_target(self):
        items = list(walk_item_content(SAMPLE))
        self.assertEqual(1, len(items))
        self.assertEqual("clip_1", action_target(items[0][0])["id"])

    def test_video_assets(self):
        self.assertEqual("dash", list(video_assets(SAMPLE))[0]["format"])

    def test_video_assets_filters_related_videos(self):
        layout = {
            "blocks": [
                {
                    "title": "Afleveringen",
                    "content": {"items": [{"itemContent": {
                        "video": {"id": "clip_1", "assets": [{"format": "dash", "path": "a.mpd"}]},
                    }}]},
                },
                {
                    "title": "Klanten kijken ook",
                    "content": {"items": [{"itemContent": {
                        "video": {"id": "clip_999", "assets": [{"format": "dash", "path": "b.mpd"}]},
                    }}]},
                },
            ]
        }
        assets = [a["path"] for a in video_assets(layout, "clip_1")]
        self.assertIn("a.mpd", assets)
        self.assertNotIn("b.mpd", assets)

    def test_is_related_block(self):
        self.assertTrue(is_related_block({"feature": "feature.recommended_programs_by_program"}))
        self.assertTrue(is_related_block({"feature": "feature.advertising_parallax"}))
        # info_by_program is the primary program block (holds the playable film
        # clip), not an auxiliary/related rail, so it must be kept.
        self.assertFalse(is_related_block({"feature": "feature.info_by_program"}))
        self.assertTrue(is_related_block({"feature": "feature.videos_by_program", "block_title": "Trailers"}))
        self.assertFalse(is_related_block({"feature": "feature.recommended_videos_by_user"}))
        self.assertFalse(is_related_block({"feature": "feature.videos_by_season_by_program"}))
        self.assertFalse(is_related_block({}))

    def test_public_api_key_matches_web_client(self):
        self.assertEqual("4_hRanGnYDFjdiZQfh-ghhhg", VideolandApi.API_KEY)

    def test_bearer_header_is_added_after_jwt(self):
        api = VideolandApi("test-device")
        self.assertNotIn("Authorization", api._headers())
        api.token = "test-token"
        self.assertEqual("Bearer test-token", api._headers()["Authorization"])
        self.assertNotIn("Authorization", api._headers(authenticated=False))

    def test_navigation_entries_flattens_groups(self):
        navigation = [{"entries": [{"label": "Home"}]}, {"entries": [{"label": "Films"}]}]
        self.assertEqual(["Home", "Films"], [item["label"] for item in navigation_entries(navigation)])

    def test_layout_adds_search_query_parameters(self):
        api = VideolandApi("test-device")
        requests = []
        api._request = lambda request_url, headers: requests.append(request_url) or {}
        api.layout("frontspace", "search", query={"query": "saving private ryan"})
        self.assertIn("frontspace/search/layout?", requests[0])
        self.assertIn("query=saving+private+ryan", requests[0])
        self.assertIn("blockPage=1", requests[0])


if __name__ == "__main__":
    unittest.main()
