import unittest
import io
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from resources.lib.api import (
    VideolandApi,
    ApiError,
    AuthError,
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
    def test_cached_get_retries_temporary_server_errors_only(self):
        for status, attempts in [(500, 3), (503, 3), (403, 1)]:
            with self.subTest(status=status):
                api = VideolandApi("test")
                error = ApiError("server error")
                error.__cause__ = HTTPError("https://example.invalid", status, "error", {}, io.BytesIO())
                api._request = Mock(side_effect=error)
                with patch("resources.lib.api.time.sleep"), self.assertRaises(ApiError):
                    api.layout(complete=True)
                self.assertEqual(api._request.call_count, attempts)
                error.__cause__.close()
        api._request = Mock(side_effect=[error, {}])
        error.__cause__.code = 502
        with patch("resources.lib.api.time.sleep"):
            self.assertEqual(api.layout(complete=True), {"blocks": []})

    @staticmethod
    def paginated_block(block_id, items, next_page):
        return {"blockId": block_id, "content": {
            "items": [{"itemContent": {"title": title}} for title in items],
            "pagination": {"nextPage": next_page},
        }}

    def test_complete_layout_follows_sections_and_items_preserving_query(self):
        first = {"blocks": [self.paginated_block("genres", ["A", "B"], 3)],
                 "pagination": {"nextPage": 2}}
        api = VideolandApi("test")
        api._request = Mock(side_effect=[
            first,
            {"blocks": [self.paginated_block("episodes", ["E1"], 3)],
             "pagination": {"nextPage": None}},
            self.paginated_block("genres", ["B", "C"], 5),
            self.paginated_block("genres", ["D"], None),
            self.paginated_block("episodes", ["E2"], None),
        ])
        result = api.layout("folder", "581", "https://v2.videoland.com/test",
                            {"query": "some title"}, complete=True)
        self.assertEqual([i["title"] for i, _ in walk_item_content(result)],
                         ["A", "B", "C", "D", "E1", "E2"])
        self.assertEqual(len(first["blocks"][0]["content"]["items"]), 2)
        urls = [call.args[0] for call in api._request.call_args_list]
        self.assertEqual(parse_qs(urlsplit(urls[1]).query)["blockPage"], ["2"])
        self.assertIn("/folder/581/block/genres?", urls[2])
        self.assertEqual(parse_qs(urlsplit(urls[3]).query)["page"], ["5"])
        for call in api._request.call_args_list:
            self.assertEqual(parse_qs(urlsplit(call.args[0]).query)["query"], ["some title"])
            self.assertEqual(call.args[1]["X-Location"], "https://v2.videoland.com/test")

    def test_metadata_lookup_does_not_fetch_additional_pages(self):
        api = VideolandApi("test")
        api._request = Mock(return_value={"blocks": [self.paginated_block("a", ["A"], 3)]})
        api.layout("program", "1")
        api._request.assert_called_once()

    def test_pagination_failures_are_not_silently_truncated(self):
        for following in [self.paginated_block("a", ["B"], 3),
                          AuthError("expired")]:
            with self.subTest(following=following):
                api = VideolandApi("test")
                api._request = Mock(side_effect=[
                    {"blocks": [self.paginated_block("a", ["A"], 3)]}, following])
                expected = AuthError if isinstance(following, AuthError) else ApiError
                with self.assertRaises(expected):
                    api.layout("folder", "1", complete=True)

    def test_layout_repeated_section_cursor_is_rejected(self):
        api = VideolandApi("test")
        api._request = Mock(return_value={"blocks": [], "pagination": {"nextPage": 1}})
        with self.assertRaises(ApiError):
            api.layout(complete=True)

    def test_sparse_pages_and_overstated_totals_follow_cursor(self):
        api = VideolandApi("test")
        api._request = Mock(side_effect=[
            {"blocks": [self.paginated_block("a", ["A"], 3)]},
            self.paginated_block("a", [], 11),
            self.paginated_block("a", ["A", "B"], None),
        ])
        result = api.layout(complete=True)
        self.assertEqual([i["title"] for i, _ in walk_item_content(result)], ["A", "B"])

    def test_menu_only_completes_selected_blocks(self):
        api = VideolandApi("test")
        api._request = Mock(side_effect=[
            {"blocks": [self.paginated_block("genres", ["A"], 3),
                        self.paginated_block("movies", ["M"], 3)]},
            self.paginated_block("genres", ["B"], None),
        ])
        result = api.layout(complete=True, block_filter=lambda block: block["blockId"] == "genres")
        self.assertEqual([i["title"] for i, _ in walk_item_content(result)], ["A", "B", "M"])
        self.assertEqual(api._request.call_count, 2)

    def test_failed_batch_falls_back_to_single_pages_at_same_cursor(self):
        api = VideolandApi("test")
        error = ApiError("batch failed")
        error.__cause__ = HTTPError("https://example.invalid", 500, "error", {}, io.BytesIO())
        api._request = Mock(side_effect=[
            {"blocks": [self.paginated_block("a", ["A"], 3)]},
            error, error, error,
            self.paginated_block("a", ["B"], 4),
            self.paginated_block("a", ["C"], None),
        ])
        with patch("resources.lib.api.time.sleep"):
            result = api.layout(complete=True)
        self.assertEqual([i["title"] for i, _ in walk_item_content(result)], ["A", "B", "C"])
        calls = api._request.call_args_list
        self.assertEqual(parse_qs(urlsplit(calls[4].args[0]).query)["page"], ["3"])
        self.assertEqual(parse_qs(urlsplit(calls[5].args[0]).query)["nbPages"], ["1"])
        error.__cause__.close()

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
