"""Kodi library integration for Videoland.

Series and films the user adds are written as ``.strm`` + ``.nfo`` files so
Kodi's video library (and skin widgets) can show them. Added titles are kept
in ``library.json`` in the add-on data folder so a background update can add
new episodes and remove titles that left Videoland.

Episode numbers are assigned once and stored per episode id, so file names
stay the same between updates and Kodi keeps watched status and resume points.

The module does not talk to Videoland itself. ``plugin.py`` passes a *source*
with two methods:

* ``series(series_id, seo)`` -> ``{"title", "plot", "poster", "fanart",
  "episodes": [{"id", "seo", "parent_id", "parent_seo", "title", "plot",
  "season", "episode", "thumb"}]}``
* ``movie(movie_id, seo)`` -> ``{"title", "plot", "poster", "fanart", "year",
  "play": {"video_id", "seo", "parent_id", "parent_seo"}}``

Both may return ``None`` (title not available) or raise.
"""

import json
import os
import re
import time
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from . import library_art, metadata

try:
    import xbmc
except ImportError:  # pragma: no cover - outside Kodi
    xbmc = None

try:
    import xbmcvfs
except ImportError:  # pragma: no cover - outside Kodi
    xbmcvfs = None


ADDON_ID = "plugin.video.videoland.nl"
DATA_PATH = "special://profile/addon_data/{}".format(ADDON_ID)
DEFAULT_TV_PATH = DATA_PATH + "/library/TV Shows"
DEFAULT_MOVIES_PATH = DATA_PATH + "/library/Movies"
# A title is only removed after it is missing this many updates in a row,
# so a temporary Videoland problem never empties the library.
MISSING_LIMIT = 3


class TitleGone(Exception):
    """The source is sure the title is no longer on Videoland."""


def log(message, level=None):
    if xbmc is None:
        return
    try:
        xbmc.log("[Videoland] Library: {}".format(message), xbmc.LOGINFO if level is None else level)
    except Exception:
        pass


def translate_path(path):
    if path and xbmcvfs is not None and str(path).startswith("special://"):
        try:
            return xbmcvfs.translatePath(path)
        except Exception:
            pass
    return path


def safe_filename(value):
    value = re.sub(r'[\\/:*?"<>|]+', " ", str(value or "")).strip()
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "Videoland"


def _int_or_none(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None
    except Exception:
        return None



def inject_dateadded(nfo_text, existing_text="", now=None):
    """Make sure an episode .nfo carries a <dateadded> so Kodi's "recently
    added" views pick up new episodes. A freshly created .nfo (no existing
    text) gets the current time; an existing one keeps its original value so
    the file does not churn and old episodes stay where they are."""
    import re as _re
    import time as _time
    if "<dateadded>" in nfo_text:
        return nfo_text
    match = _re.search(r"<dateadded>([^<]+)</dateadded>", existing_text or "")
    if match:
        value = match.group(1)
    else:
        aired = _re.search(r"<aired>(\d{4}-\d{2}-\d{2})</aired>", nfo_text or "")
        if aired:
            value = aired.group(1) + " 12:00:00"
        else:
            value = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(now if now is not None else _time.time()))
    line = "  <dateadded>{}</dateadded>\n".format(value)
    if "</episodedetails>" in nfo_text:
        return nfo_text.replace("</episodedetails>", line + "</episodedetails>", 1)
    return nfo_text


class LocalFS:
    """Plain ``os`` for local folders, ``xbmcvfs`` for smb:// and nfs://."""

    @staticmethod
    def _remote(path):
        return "://" in str(path) and xbmcvfs is not None

    def join(self, *parts):
        if self._remote(parts[0]):
            return "/".join([str(parts[0]).rstrip("/")] + [str(p).strip("/") for p in parts[1:]])
        return os.path.join(*parts)

    def read(self, path):
        try:
            if self._remote(path):
                handle = xbmcvfs.File(path)
                try:
                    return handle.read()
                finally:
                    handle.close()
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except Exception:
            return None

    def write(self, path, text):
        """Write ``text``; return False (and touch nothing) when unchanged."""
        if self.read(path) == text:
            return False
        if self._remote(path):
            xbmcvfs.mkdirs(path.rsplit("/", 1)[0] + "/")
            handle = xbmcvfs.File(path, "w")
            try:
                handle.write(text)
            finally:
                handle.close()
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        return True

    def delete(self, path):
        try:
            if self._remote(path):
                return bool(xbmcvfs.delete(path))
            os.remove(path)
            return True
        except Exception:
            return False

    def walk_files(self, folder):
        if self._remote(folder):
            dirs, files = xbmcvfs.listdir(folder.rstrip("/") + "/")
            for name in files:
                yield self.join(folder, name)
            for name in dirs:
                for path in self.walk_files(self.join(folder, name)):
                    yield path
            return
        if not os.path.isdir(folder):
            return
        for root, _dirs, files in os.walk(folder):
            for name in files:
                yield os.path.join(root, name)

    def remove_empty_dirs(self, folder):
        if self._remote(folder):
            dirs, _files = xbmcvfs.listdir(folder.rstrip("/") + "/")
            for name in dirs:
                self.remove_empty_dirs(self.join(folder, name))
            dirs, files = xbmcvfs.listdir(folder.rstrip("/") + "/")
            if not dirs and not files:
                xbmcvfs.rmdir(folder.rstrip("/") + "/")
            return
        if not os.path.isdir(folder):
            return
        for root, _dirs, _files in os.walk(folder, topdown=False):
            if not os.listdir(root):
                try:
                    os.rmdir(root)
                except OSError:
                    pass

    def remove_tree(self, folder):
        for path in list(self.walk_files(folder)):
            self.delete(path)
        self.remove_empty_dirs(folder)


class LibraryStore:
    """Remembers which series and films are in the library."""

    def __init__(self, path):
        self.path = path
        self.data = self._load()

    @staticmethod
    def _empty():
        return {"version": 1, "series": {}, "movies": {}, "last_update": 0}

    def _load(self):
        base = self._empty()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return base
        if isinstance(data, dict):
            base.update(data)
        for key in ("series", "movies"):
            if not isinstance(base.get(key), dict):
                base[key] = {}
        return base

    def save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(temporary, self.path)

    def section(self, kind):
        return self.data["series" if kind == "series" else "movies"]

    def get(self, kind, item_id):
        return self.section(kind).get(str(item_id))

    def has(self, kind, item_id):
        return str(item_id) in self.section(kind)

    def is_empty(self):
        return not self.data["series"] and not self.data["movies"]


def store_path():
    return os.path.join(translate_path(DATA_PATH) or "", "library.json")


class Library:
    def __init__(self, source, settings, store=None, fs=None, now=None, enricher=None, downloader=None):
        """``settings(name)`` returns a setting value as a string;
        ``downloader(url)`` returns image bytes (None: artwork stays URLs)."""
        self.enricher = enricher
        self.downloader = downloader
        self._pending_hints = {}
        self.source = source
        self.settings = settings
        self.fs = fs or LocalFS()
        self.now = now or time.time
        self.store = store or LibraryStore(store_path())

    # ------------------------------------------------------------------ paths
    def _setting(self, name):
        try:
            return str(self.settings(name) or "").strip()
        except Exception:
            return ""

    def tv_root(self):
        return translate_path(self._setting("library_tv_path") or DEFAULT_TV_PATH)

    def tmdb_art_first(self):
        """Posters/backgrounds from TMDb before Videoland's own (default on)."""
        return self._setting("art_tmdb_first").lower() not in ("false", "0")

    def movies_root(self):
        return translate_path(self._setting("library_movies_path") or DEFAULT_MOVIES_PATH)

    @staticmethod
    def play_url(play):
        # inlib=1 marks the .strm as coming from the Kodi library, so playback
        # defers to Kodi's own resume prompt (no second "continue" dialog).
        query = {"action": "play", "video_id": play.get("video_id") or play.get("id") or "", "inlib": "1"}
        for key in ("seo", "parent_id", "parent_seo"):
            if play.get(key):
                query[key] = play[key]
        return "plugin://{}/?{}".format(ADDON_ID, urlencode(query))

    # ------------------------------------------------------------------ state
    def is_in_library(self, kind, item_id):
        return bool(item_id) and self.store.has(kind, item_id)

    def items(self, kind):
        section = self.store.section(kind)
        return sorted(section.items(), key=lambda pair: str(pair[1].get("title") or "").lower())

    # ----------------------------------------------------------------- series
    def add_series(self, series_id, seo="", title="", poster="", fanart=""):
        """``poster``/``fanart`` come from the card the user picked; they are
        used when the title page has no artwork of its own."""
        self._pending_hints[("series", str(series_id))] = {"poster_hint": poster, "fanart_hint": fanart}
        return self._sync_series(str(series_id), seo=seo, title=title, is_update=False)

    def _apply_hints(self, kind, item_id, entry, data):
        for key, value in self._pending_hints.pop((kind, str(item_id)), {}).items():
            if value:
                entry[key] = value
        data = dict(data)
        if not data.get("poster") and entry.get("poster_hint"):
            data["poster"] = entry["poster_hint"]
        if not data.get("fanart") and entry.get("fanart_hint"):
            data["fanart"] = entry["fanart_hint"]
        return data

    def _assign_numbers(self, entry, episodes):
        mapping = entry.setdefault("episodes", {})
        taken = {tuple(value) for value in mapping.values()
                 if isinstance(value, (list, tuple)) and len(value) == 2}

        def next_free(season, wanted):
            if wanted and (season, wanted) not in taken:
                return wanted
            used = [number for (s, number) in taken if s == season]
            number = (max(used) if used else 0) + 1
            while (season, number) in taken:
                number += 1
            return number

        numbered = []
        for episode in episodes:
            episode_id = str(episode.get("id") or "")
            if not episode_id:
                continue
            stored = mapping.get(episode_id)
            if isinstance(stored, (list, tuple)) and len(stored) == 2:
                numbered.append((episode, int(stored[0]), int(stored[1])))
                continue
            season = _int_or_none(episode.get("season"))
            if not season:
                season = 1
            number = next_free(season, _int_or_none(episode.get("episode")))
            taken.add((season, number))
            mapping[episode_id] = [season, number]
            numbered.append((episode, season, number))
        return numbered

    def _sync_series(self, series_id, seo="", title="", is_update=False):
        result = {"kind": "series", "id": series_id, "added": 0, "removed": 0, "total": 0, "ok": False}
        section = self.store.section("series")
        entry = dict(section.get(series_id) or {})
        seo = seo or entry.get("seo") or ""
        try:
            data = self.source.series(series_id, seo)
        except TitleGone:
            data = None
        episodes = [ep for ep in ((data or {}).get("episodes") or []) if ep.get("id")]
        if not episodes:
            result["reason"] = "no_episodes"
            if is_update and series_id in section:
                self._count_missing("series", series_id, entry, result)
            return result

        if title:
            entry["card_title"] = metadata.clean_title(title)
        series_title = (metadata.clean_title(data.get("title")) or entry.get("card_title")
                        or entry.get("title") or series_id)
        entry.update({"title": series_title, "seo": seo, "missing": 0})
        entry.setdefault("added", int(self.now()))
        data = self._apply_hints("series", series_id, entry, data)
        data = self._enrich_show(entry, series_title, data)
        if data.get("poster"):
            entry["thumb"] = data["poster"]
        if not entry.get("folder"):
            entry["folder"] = safe_filename(series_title)
        show_dir = self.fs.join(self.tv_root(), entry["folder"])
        self.fs.write(self.fs.join(show_dir, "tvshow.nfo"), self._tvshow_nfo(series_id, series_title, data))
        _saved = library_art.save_art(self, entry, show_dir,
                                      {k: data.get(k) for k in ("poster", "fanart", "clearlogo")},
                                      library_art.art_names("series", entry["folder"]), self.downloader)
        entry["clearlogo"] = _saved.get("clearlogo") or data.get("clearlogo") or ""

        wanted = set()
        seasons_used = set()
        for episode, season, number in self._assign_numbers(entry, episodes):
            seasons_used.add(season)
            base = "{} S{:02d}E{:02d}".format(entry["folder"], season, number)
            season_dir = self.fs.join(show_dir, "Season {}".format(season))
            strm = self.fs.join(season_dir, base + ".strm")
            nfo = self.fs.join(season_dir, base + ".nfo")
            wanted.update((os.path.normcase(strm), os.path.normcase(nfo)))
            play = {"video_id": episode["id"], "seo": episode.get("seo"),
                    "parent_id": episode.get("parent_id") or series_id,
                    "parent_seo": episode.get("parent_seo") or seo}
            if self.fs.write(strm, self.play_url(play) + "\n"):
                result["added"] += 1
            self.fs.write(nfo, inject_dateadded(self._episode_nfo(
                self._enrich_episode(entry, episode, season, number), series_title, season, number),
                self.fs.read(nfo)))

        for path in list(self.fs.walk_files(show_dir)):
            name = os.path.basename(path).lower()
            if name == "tvshow.nfo" or not name.endswith((".strm", ".nfo")):
                continue
            if os.path.normcase(path) not in wanted and self.fs.delete(path) and name.endswith(".strm"):
                result["removed"] += 1
        self.fs.remove_empty_dirs(show_dir)

        library_art.save_season_posters(self, entry, show_dir, data.get("season_posters"),
                                        seasons_used, self.downloader)
        self._save_metadata()
        entry.update({"updated": int(self.now()), "episode_count": len(episodes)})
        section[series_id] = entry
        result.update({"ok": True, "total": len(episodes), "title": series_title})
        return result

    # --------------------------------------------------------------- metadata
    def _enrich_show(self, entry, title, local):
        if self.enricher is None:
            return local
        try:
            extra = self.enricher.show(title, known=entry.get("ids"))
            card_title = entry.get("card_title")
            if not (extra.get("ids") or {}).get("tmdb") and card_title and card_title != title:
                # The page title can differ from the card the user picked.
                second = self.enricher.show(card_title, known=entry.get("ids"))
                if (second.get("ids") or {}).get("tmdb"):
                    extra = second
        except Exception as exc:
            log("metadata lookup failed for {}: {}".format(title, exc))
            return local
        found = extra.get("ids") or {}
        log("metadata for '{}': tmdb={} tvmaze={}".format(title, found.get("tmdb") or "-", found.get("tvmaze") or "-"))
        ids = {key: str(value) for key, value in (extra.get("ids") or {}).items() if value}
        if ids:
            entry["ids"] = ids
        extra.pop("episodes", None)
        return metadata.merge_art_first(local, extra, self.tmdb_art_first())

    def _enrich_episode(self, entry, episode, season, number):
        if self.enricher is None or not entry.get("ids"):
            return episode
        try:
            extra = self.enricher.episode(entry["ids"], season, number, by_number=True)
        except Exception:
            return episode
        merged = metadata.merge(episode, extra)
        merged["id"] = episode["id"]
        return merged

    def _save_metadata(self):
        if self.enricher is not None:
            try:
                self.enricher.save()
            except Exception:
                pass

    @staticmethod
    def _art_lines(data, poster_aspect=True):
        lines = []
        if data.get("poster"):
            lines.append('  <thumb aspect="poster">{}</thumb>'.format(escape(data["poster"])) if poster_aspect
                         else "  <thumb>{}</thumb>".format(escape(data["poster"])))
        if data.get("fanart"):
            lines.append("  <fanart><thumb>{}</thumb></fanart>".format(escape(data["fanart"])))
        return lines

    def _tvshow_nfo(self, series_id, title, data):
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<tvshow>",
                 "  <title>{}</title>".format(escape(title)),
                 "  <plot>{}</plot>".format(escape(data.get("plot") or "")),
                 '  <uniqueid type="videoland" default="true">{}</uniqueid>'.format(escape(series_id))]
        if data.get("year"):
            lines.append("  <year>{}</year>".format(data["year"]))
        lines += self._art_lines(data)
        lines += metadata.nfo_extra_lines(data, escape)
        lines.append("</tvshow>")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _episode_nfo(episode, series_title, season, number):
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<episodedetails>",
                 "  <title>{}</title>".format(escape(episode.get("title") or "Aflevering {}".format(number))),
                 "  <showtitle>{}</showtitle>".format(escape(series_title)),
                 "  <season>{}</season>".format(season),
                 "  <episode>{}</episode>".format(number),
                 "  <plot>{}</plot>".format(escape(episode.get("plot") or "")),
                 '  <uniqueid type="videoland" default="true">{}</uniqueid>'.format(escape(str(episode["id"])))]
        if episode.get("aired"):
            lines.append("  <aired>{}</aired>".format(escape(episode["aired"])))
        if episode.get("thumb"):
            lines.append("  <thumb>{}</thumb>".format(escape(episode["thumb"])))
        lines.append("</episodedetails>")
        return "\n".join(lines) + "\n"

    # ----------------------------------------------------------------- movies
    def add_movie(self, movie_id, seo="", title="", poster="", fanart=""):
        self._pending_hints[("movie", str(movie_id))] = {"poster_hint": poster, "fanart_hint": fanart}
        return self._sync_movie(str(movie_id), seo=seo, title=title, is_update=False)

    def _sync_movie(self, movie_id, seo="", title="", is_update=False):
        result = {"kind": "movie", "id": movie_id, "added": 0, "removed": 0, "total": 0, "ok": False}
        section = self.store.section("movie")
        entry = dict(section.get(movie_id) or {})
        seo = seo or entry.get("seo") or ""
        try:
            data = self.source.movie(movie_id, seo)
        except TitleGone:
            data = None
        if not data or not (data.get("play") or {}).get("video_id"):
            result["reason"] = "not_playable"
            if is_update and movie_id in section:
                self._count_missing("movie", movie_id, entry, result)
            return result

        movie_title = data.get("title") or entry.get("title") or title or movie_id
        data = self._apply_hints("movie", movie_id, entry, data)
        if self.enricher is not None:
            try:
                extra = self.enricher.movie(movie_title, _int_or_none(data.get("year")), known=entry.get("ids"))
                ids = {key: str(value) for key, value in (extra.get("ids") or {}).items() if value}
                if ids:
                    entry["ids"] = ids
                data = metadata.merge_art_first(data, extra, self.tmdb_art_first())
            except Exception as exc:
                log("metadata lookup failed for {}: {}".format(movie_title, exc))
            self._save_metadata()
        year = _int_or_none(data.get("year") or entry.get("year"))
        if year and not 1900 <= year <= 2100:
            year = None
        if not entry.get("folder"):
            entry["folder"] = safe_filename("{} ({})".format(movie_title, year) if year else movie_title)
        movie_dir = self.fs.join(self.movies_root(), entry["folder"])
        base = self.fs.join(movie_dir, entry["folder"])
        if self.fs.write(base + ".strm", self.play_url(data["play"]) + "\n"):
            result["added"] = 1
        self.fs.write(base + ".nfo", self._movie_nfo(movie_id, movie_title, data, year))
        _saved = library_art.save_art(self, entry, movie_dir,
                                      {k: data.get(k) for k in ("poster", "fanart", "clearlogo")},
                                      library_art.art_names("movie", entry["folder"]), self.downloader)
        entry["clearlogo"] = _saved.get("clearlogo") or data.get("clearlogo") or ""

        entry.update({"title": movie_title, "seo": seo, "missing": 0, "updated": int(self.now())})
        entry.setdefault("added", int(self.now()))
        if year:
            entry["year"] = year
        if data.get("poster"):
            entry["thumb"] = data["poster"]
        section[movie_id] = entry
        result.update({"ok": True, "total": 1, "title": movie_title})
        return result

    def _movie_nfo(self, movie_id, title, data, year):
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<movie>",
                 "  <title>{}</title>".format(escape(title)),
                 "  <plot>{}</plot>".format(escape(data.get("plot") or "")),
                 '  <uniqueid type="videoland" default="true">{}</uniqueid>'.format(escape(movie_id))]
        if year:
            lines.append("  <year>{}</year>".format(year))
        lines += self._art_lines(data)
        lines += metadata.nfo_extra_lines(data, escape, kind="movie")
        lines.append("</movie>")
        return "\n".join(lines) + "\n"

    # ----------------------------------------------------------------- common
    def _count_missing(self, kind, item_id, entry, result):
        entry["missing"] = int(entry.get("missing") or 0) + 1
        if entry["missing"] >= MISSING_LIMIT:
            log("{} {} no longer available, removing".format(kind, item_id))
            self.store.section(kind)[item_id] = entry
            if self.remove(kind, item_id, save=False):
                result.update({"removed": max(1, result.get("removed", 0)), "ok": True, "reason": "gone"})
            return
        self.store.section(kind)[item_id] = entry

    def remove(self, kind, item_id, save=True):
        kind = "series" if kind == "series" else "movie"
        entry = self.store.section(kind).pop(str(item_id), None)
        if entry is None:
            return False
        if entry.get("folder"):
            root = self.tv_root() if kind == "series" else self.movies_root()
            self.fs.remove_tree(self.fs.join(root, entry["folder"]))
        if save:
            self.store.save()
        return True

    def update_all(self, progress=None, stop_on=()):
        """Refresh every title. Exceptions listed in ``stop_on`` abort the run."""
        totals = {"added": 0, "removed": 0, "failed": 0, "checked": 0}
        jobs = [("series", key) for key, _ in self.items("series")] + \
               [("movie", key) for key, _ in self.items("movie")]
        for index, (kind, item_id) in enumerate(jobs):
            if progress is not None and progress(index, len(jobs), kind, item_id) is False:
                break
            try:
                if kind == "series":
                    result = self._sync_series(item_id, is_update=True)
                else:
                    result = self._sync_movie(item_id, is_update=True)
            except tuple(stop_on):
                self.store.save()
                raise
            except Exception as exc:
                log("update of {} {} failed: {}".format(kind, item_id, exc))
                totals["failed"] += 1
                continue
            totals["checked"] += 1
            totals["added"] += result.get("added", 0)
            totals["removed"] += result.get("removed", 0)
            if not result.get("ok"):
                totals["failed"] += 1
        self.store.data["last_update"] = int(self.now())
        self.store.save()
        return totals


def update_due(store, hours, now=None):
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return False
    if hours <= 0 or store.is_empty():
        return False
    current = time.time() if now is None else now
    return current - (store.data.get("last_update") or 0) >= hours * 3600


def scan_flag_path():
    return os.path.join(translate_path("special://profile/addon_data/plugin.video.videoland.nl") or "", "scan_pending.json")


def run_library_jobs(scan=True, clean=False):
    """Ask Kodi to clean and/or scan the video library without dialogs. When
    Kodi is already scanning, the request waits until that scan is done."""
    library_art.request_scan(scan_flag_path(), scan=scan, clean=clean)
