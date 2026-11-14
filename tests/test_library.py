import os
import tempfile
import unittest
from unittest.mock import MagicMock
from urllib.error import HTTPError

from resources.lib import library
from resources.lib.api import ApiError
from test_auth import load_plugin


def _files(root):
    found = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            found.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
    return sorted(found)


class FakeSource:
    def __init__(self):
        self.shows = {}
        self.films = {}
        self.gone = set()

    def series(self, series_id, seo):
        if series_id in self.gone:
            raise library.TitleGone(series_id)
        return self.shows.get(series_id)

    def movie(self, movie_id, seo):
        if movie_id in self.gone:
            raise library.TitleGone(movie_id)
        return self.films.get(movie_id)


def episode(ep_id, season, number, title=None):
    return {"id": ep_id, "seo": "ep-" + ep_id, "parent_id": "p1", "parent_seo": "show",
            "title": title or ep_id, "plot": "Plot", "season": season, "episode": number, "thumb": ""}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.settings = {"library_tv_path": os.path.join(self.root, "TV Shows"),
                         "library_movies_path": os.path.join(self.root, "Movies")}
        self.source = FakeSource()
        self.clock = [1_700_000_000]
        store = library.LibraryStore(os.path.join(self.root, "library.json"))
        self.lib = library.Library(self.source, self.settings.get, store=store, now=lambda: self.clock[0])

    def test_series_export_with_stable_numbers(self):
        self.source.shows["p1"] = {"title": "Mijn Show", "plot": "Over", "poster": "https://img/p.jpg",
                                   "fanart": "", "episodes": [episode("a", 1, 1), episode("b", 1, 2), episode("c", None, None)]}
        result = self.lib.add_series("p1", "show")
        self.assertTrue(result["ok"])
        self.assertEqual(_files(os.path.join(self.root, "TV Shows")), [
            "Mijn Show/Season 1/Mijn Show S01E01.nfo", "Mijn Show/Season 1/Mijn Show S01E01.strm",
            "Mijn Show/Season 1/Mijn Show S01E02.nfo", "Mijn Show/Season 1/Mijn Show S01E02.strm",
            "Mijn Show/Season 1/Mijn Show S01E03.nfo", "Mijn Show/Season 1/Mijn Show S01E03.strm",
            "Mijn Show/tvshow.nfo"])
        with open(os.path.join(self.root, "TV Shows/Mijn Show/Season 1/Mijn Show S01E02.strm")) as handle:
            self.assertEqual(handle.read().strip(),
                             "plugin://plugin.video.videoland.nl/?action=play&video_id=b&seo=ep-b&parent_id=p1&parent_seo=show")

        # 'a' leaves Videoland, 'd' arrives: the others keep their numbers.
        self.source.shows["p1"]["episodes"] = [episode("b", 1, 2), episode("c", None, None), episode("d", 2, 1)]
        totals = self.lib.update_all()
        self.assertEqual((totals["added"], totals["removed"], totals["failed"]), (1, 1, 0))
        names = _files(os.path.join(self.root, "TV Shows/Mijn Show"))
        self.assertIn("Season 1/Mijn Show S01E03.strm", names)
        self.assertIn("Season 2/Mijn Show S02E01.strm", names)
        self.assertNotIn("Season 1/Mijn Show S01E01.strm", names)

    def test_title_removed_only_after_three_misses(self):
        self.source.films["m1"] = {"title": "Film", "plot": "", "year": 2020,
                                   "play": {"video_id": "clip_9", "seo": "film", "parent_id": "m1", "parent_seo": "film"}}
        self.lib.add_movie("m1", "film")
        self.assertEqual(_files(os.path.join(self.root, "Movies")),
                         ["Film (2020)/Film (2020).nfo", "Film (2020)/Film (2020).strm"])
        self.source.gone.add("m1")
        self.lib.update_all()
        self.lib.update_all()
        self.assertTrue(self.lib.is_in_library("movie", "m1"))
        totals = self.lib.update_all()
        self.assertEqual(totals["removed"], 1)
        self.assertFalse(self.lib.is_in_library("movie", "m1"))
        self.assertEqual(_files(os.path.join(self.root, "Movies")), [])

    def test_errors_do_not_count_as_missing(self):
        self.source.shows["p1"] = {"title": "Show", "episodes": [episode("a", 1, 1)]}
        self.lib.add_series("p1")
        self.source.series = MagicMock(side_effect=ApiError("offline"))
        for _ in range(5):
            totals = self.lib.update_all()
        self.assertEqual(totals["failed"], 1)
        self.assertTrue(self.lib.is_in_library("series", "p1"))
        self.assertEqual(self.lib.store.get("series", "p1").get("missing", 0), 0)

    def test_remove_and_update_due(self):
        self.source.shows["p1"] = {"title": "Show", "episodes": [episode("a", 1, 1)]}
        self.lib.add_series("p1")
        self.assertTrue(library.update_due(self.lib.store, 12, now=self.clock[0]))
        self.lib.update_all()
        self.assertFalse(library.update_due(self.lib.store, 12, now=self.clock[0]))
        self.assertTrue(library.update_due(self.lib.store, 12, now=self.clock[0] + 12 * 3600))
        self.assertTrue(self.lib.remove("series", "p1"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "TV Shows", "Show")))
        self.assertFalse(library.update_due(self.lib.store, 12, now=self.clock[0] + 99 * 3600))


class PluginLibraryTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()
        self.plugin.menu_icon = MagicMock(return_value=None)
        self.plugin.ADDON.getLocalizedString.side_effect = lambda sid: "s{}".format(sid)
        self.plugin._library_has = MagicMock(return_value=False)
        self.plugin.add = MagicMock()

    def _menu(self, rows):
        self.plugin._render_rows(rows)
        return self.plugin.add.call_args.kwargs["context_menu"]

    def test_series_folder_gets_add_to_library(self):
        self.plugin._play_target = MagicMock(return_value=None)
        menu = self._menu([({"title": "Show"}, {"id": "p1", "type": "program", "seo": "show"}, "program", {})])
        entry = [m for m in menu if "library_toggle" in m[1]]
        self.assertEqual(entry[0][0], "s31110")
        self.assertIn("kind=series", entry[0][1])

    def test_film_gets_movie_kind_and_remove_label_when_present(self):
        self.plugin._play_target = MagicMock(return_value={"id": "clip_1", "seo": "film"})
        self.plugin._library_has.return_value = True
        menu = self._menu([({"title": "Film"}, {"id": "m1", "type": "program", "seo": "film"}, "program", {})])
        entry = [m for m in menu if "library_toggle" in m[1]]
        self.assertEqual(entry[0][0], "s31111")
        self.assertIn("kind=movie", entry[0][1])

    def test_episode_has_no_library_entry(self):
        menu = self._menu([({"title": "Ep"}, {"id": "clip_1", "type": "video"}, "video", {})])
        self.assertFalse(any("library_toggle" in m[1] for m in menu))

    def test_source_reads_episodes_and_marks_404_as_gone(self):
        client = MagicMock()
        block = {"block_title": "Seizoen 2"}
        data = {"entity": {"title": "Show"}, "blocks": []}
        client.layout.return_value = data
        self.plugin._build_rows = MagicMock(return_value=[
            ({"extraTitle": "3. De val", "description": "Spannend"},
             {"id": "clip_5", "seo": "de-val", "parent": {"id": "p1", "seo": "show"}}, "video", block)])
        result = self.plugin.LibrarySource(client).series("p1", "show")
        self.assertEqual(result["title"], "Show")
        self.assertEqual(result["episodes"][0]["season"], 2)
        self.assertEqual(result["episodes"][0]["episode"], 3)
        self.assertEqual(result["episodes"][0]["title"], "De val")

        error = ApiError("not found")
        error.__cause__ = HTTPError("https://x.invalid", 404, "nf", {}, None)
        self.addCleanup(error.__cause__.close)
        client.layout.side_effect = error
        with self.assertRaises(library.TitleGone):
            self.plugin.LibrarySource(client).series("p1", "show")

    def test_background_update_never_raises(self):
        self.plugin.xbmc.Player.return_value.isPlaying.return_value = False
        self.plugin.setting = MagicMock(return_value="profile")
        self.plugin._library_update = MagicMock(side_effect=ApiError("boom"))
        self.plugin.library_update(background=True)
        self.plugin.xbmcgui.Dialog.return_value.ok.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class EnrichmentTests(unittest.TestCase):
    def test_local_data_first_and_gaps_filled(self):
        from resources.lib import metadata

        routes = {
            "/search/shows": [{"show": {"id": 7, "name": "Mijn Show"}}],
            "/shows/7": {"summary": "<p>Van TVmaze</p>", "image": {"original": "https://maze/p.jpg"},
                         "premiered": "2020-05-01", "genres": ["Drama"], "externals": {"thetvdb": 42}},
            "/shows/7/episodes": [{"season": 1, "number": 1, "name": "Begin", "summary": "<p>Plot 1</p>",
                                   "airdate": "2020-05-01", "image": {"original": "https://maze/e.jpg"}}],
        }

        def http(url, headers):
            from urllib.parse import urlsplit
            return routes[urlsplit(url).path]

        with tempfile.TemporaryDirectory() as root:
            enricher = metadata.Enricher(os.path.join(root, "cache.json"), http=http)
            source = FakeSource()
            source.shows["p1"] = {"title": "Mijn Show", "plot": "Eigen tekst", "poster": "", "fanart": "",
                                  "episodes": [dict(episode("a", 1, 1), title="Aflevering 1", plot="")]}
            settings = {"library_tv_path": os.path.join(root, "TV")}
            lib = library.Library(source, settings.get, store=library.LibraryStore(os.path.join(root, "l.json")),
                                  enricher=enricher)
            lib.add_series("p1")
            with open(os.path.join(root, "TV/Mijn Show/tvshow.nfo")) as handle:
                show = handle.read()
            self.assertIn("<plot>Eigen tekst</plot>", show)
            self.assertIn('<thumb aspect="poster">https://maze/p.jpg</thumb>', show)
            self.assertIn('<uniqueid type="tvdb">42</uniqueid>', show)
            with open(os.path.join(root, "TV/Mijn Show/Season 1/Mijn Show S01E01.nfo")) as handle:
                ep = handle.read()
            self.assertIn("<title>Begin</title>", ep)
            self.assertIn("<plot>Plot 1</plot>", ep)
            self.assertIn('<uniqueid type="videoland" default="true">a</uniqueid>', ep)


class ArtworkTests(unittest.TestCase):
    def test_card_poster_used_and_saved_when_page_has_none(self):
        with tempfile.TemporaryDirectory() as root:
            source = FakeSource()
            source.shows["p1"] = {"title": "Show", "poster": "", "fanart": "", "episodes": [episode("a", 1, 1)]}
            settings = {"library_tv_path": os.path.join(root, "TV")}
            downloads = []
            lib = library.Library(source, settings.get, store=library.LibraryStore(os.path.join(root, "l.json")),
                                  downloader=lambda url: downloads.append(url) or b"img")
            lib.add_series("p1", "show", "Show", poster="https://img/card.jpg", fanart="https://img/hero.jpg")
            folder = os.path.join(root, "TV", "Show")
            self.assertTrue(os.path.isfile(os.path.join(folder, "poster.jpg")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "fanart.jpg")))
            with open(os.path.join(folder, "tvshow.nfo")) as handle:
                self.assertIn("https://img/card.jpg", handle.read())
            lib.update_all()
            self.assertEqual(len(downloads), 2)  # hints kept, nothing downloaded twice

    def test_ratio_image_picks_portrait(self):
        plugin = load_plugin()
        image = {"id": "land", "idsByRatio": {"2:3": "tall", "16:9": "wide"}}
        self.assertTrue(plugin.ratio_image(image, ("2:3",)).endswith("/tall/raw"))
        self.assertTrue(plugin.ratio_image(image, ("16:9",)).endswith("/wide/raw"))
        self.assertEqual(plugin.ratio_image({"id": "x"}, ("2:3",)), "")


class SearchKindFilterTests(unittest.TestCase):
    def test_only_kind_keeps_matching_rows(self):
        plugin = load_plugin()
        plugin.menu_icon = MagicMock(return_value=None)
        plugin.add = MagicMock()
        plugin._library_has = MagicMock(return_value=False)
        plugin._play_target = lambda client, item, target, kind, program_data=None: (
            {"id": "clip_1"} if target["id"] == "film" else (target if kind == "video" else None))
        rows = [({"title": "Serie"}, {"id": "serie", "type": "program"}, "program", {}),
                ({"title": "Film"}, {"id": "film", "type": "program"}, "program", {}),
                ({"title": "Afl"}, {"id": "clip_9", "type": "video"}, "video", {})]
        for kind, expected in (("series", "Serie"), ("movie", "Film"), ("episode", "Afl")):
            plugin.add.reset_mock()
            plugin._render_rows(rows, only_kind=kind)
            self.assertEqual([c.args[0] for c in plugin.add.call_args_list], [expected])


class WatchlistTests(unittest.TestCase):
    def test_watchlist_is_loaded_fresh_and_reported_per_block(self):
        plugin = load_plugin()
        client = MagicMock()
        client.cache_dir = "/cache"
        client.cache_ttl = 1800
        card = lambda n: {"itemContent": {"title": "T{}".format(n), "action": {"target": {
            "type": "layout", "value_layout": {"type": "program", "id": str(n), "seo": "t{}".format(n)}}}}}
        client.layout.return_value = {"blocks": [{
            "block_title": "Series", "feature": "feature.bookmarks",
            "content": {"items": [card(1), card(2)], "pagination": {"totalItems": 5}}}]}
        report = plugin.watchlist_report(client)
        self.assertIsNone(client.cache_dir)
        self.assertEqual(client.cache_ttl, 0)
        self.assertEqual(report, [("Series", 2, 5, 2, "feature.bookmarks")])

    def test_cache_is_kept_per_profile(self):
        plugin = load_plugin()
        plugin.cache_dir = MagicMock(return_value="/data/cache")
        plugin.setting = MagicMock(return_value="abc-123")
        self.assertEqual(plugin.profile_cache_dir(), os.path.join("/data/cache", "abc-123"))
        plugin.setting = MagicMock(return_value="")
        self.assertEqual(plugin.profile_cache_dir(), os.path.join("/data/cache", "default"))


class WatchlistSyncTests(unittest.TestCase):
    def test_new_titles_added_and_left_titles_removed_only_if_from_watchlist(self):
        plugin = load_plugin()
        plugin.watchlist_titles = MagicMock(return_value=[
            ("series", "s1", "s-1", "Serie", "p.jpg", "f.jpg"),
            ("movie", "m1", "m-1", "Film", "", ""),
            ("series", "own", "o", "Eigen", "", ""),
        ])
        plugin.setting_bool = MagicMock(side_effect=lambda name, default=False: name == "library_watchlist_remove")
        added_calls = []
        with tempfile.TemporaryDirectory() as root:
            store = library.LibraryStore(os.path.join(root, "l.json"))
            store.section("series")["own"] = {"title": "Eigen"}            # added by hand
            store.section("series")["gone"] = {"title": "Weg", "source": "watchlist"}
            lib = library.Library(None, {}.get, store=store)

            def add_series(item_id, seo, title, poster, fanart):
                added_calls.append(("series", item_id, poster))
                store.section("series")[item_id] = {"title": title}
                return {"ok": True}

            def add_movie(item_id, seo, title, poster, fanart):
                added_calls.append(("movie", item_id, poster))
                store.section("movie")[item_id] = {"title": title}
                return {"ok": True}

            lib.add_series, lib.add_movie = add_series, add_movie
            added, removed, failed = plugin.sync_watchlist_to_library(MagicMock(), lib)
            self.assertEqual((added, removed, failed), (2, 1, 0))
            self.assertEqual(added_calls, [("series", "s1", "p.jpg"), ("movie", "m1", "")])
            self.assertEqual(store.get("series", "s1")["source"], "watchlist")
            self.assertTrue(store.has("series", "own"))
            self.assertFalse(store.has("series", "gone"))


class LibraryProfileTests(unittest.TestCase):
    def test_watchlist_of_chosen_profile_then_back_to_active(self):
        plugin = load_plugin()
        values = {"library_profile_id": "kids", "profile_id": "me"}
        plugin.setting = lambda name, default="": values.get(name, default)
        plugin.auth_data = lambda: {"uid": "u"}
        seen = []
        plugin.watchlist_titles = lambda client: seen.append(client.jwt.call_args.args[1]) or ["x"]
        client = MagicMock()
        self.assertEqual(plugin._watchlist_of_library_profile(client), ["x"])
        self.assertEqual(seen, ["kids"])
        self.assertEqual(client.jwt.call_args.args, ({"uid": "u"}, "me"))

        values["library_profile_id"] = ""
        plugin.watchlist_titles = lambda client: []
        client = MagicMock()
        plugin._watchlist_of_library_profile(client)
        client.jwt.assert_not_called()


class QualityTests(unittest.TestCase):
    def test_software_stream_is_always_chosen(self):
        plugin = load_plugin()
        dash = [{"path": "hd.mpd", "drm": {"type": "hardware"}}, {"path": "sd.mpd", "drm": {"type": "software"}}]
        self.assertEqual(plugin.choose_asset(dash)["path"], "sd.mpd")
        self.assertEqual(plugin.choose_asset([{"path": "only.mpd"}])["path"], "only.mpd")
