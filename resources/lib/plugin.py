def run_diagnostics():
    """Settings button: check everything playback and the library need."""
    t = diagnostics_mod.texts(xbmc.getLanguage(xbmc.ISO_639_1) or "nl")
    progress = xbmcgui.DialogProgress()
    progress.create("Videoland", t["title"] + "...")
    try:
        auth = auth_data()
        signed_in = all(auth.get(key) for key in ("uid", "signature", "timestamp")) and bool(setting("profile_id"))
        endpoints = [("Videoland", VideolandApi.LAYOUT + "/"), ("TMDb", "https://api.themoviedb.org/3/"),
                     ("TVmaze", "https://api.tvmaze.com/")]
        tmdb_status = None
        if setting_bool("library_enrich", True):
            tmdb_status = metadata_mod.test_tmdb_key(setting("tmdb_api_key"))[0]
        lib = library_mod.Library(None, setting, store=_library_store())
        checks = diagnostics_mod.run_checks(
            t, ADDON.getAddonInfo("version"), signed_in, endpoints, library=lib,
            library_special=(library_mod.DEFAULT_TV_PATH, library_mod.DEFAULT_MOVIES_PATH),
            tmdb_status=tmdb_status,
            kodi_counts=library_art.kodi_counts(lib, "plugin.video.videoland.nl/library"))
        if signed_in:
            try:
                client = api()
                ensure_profile(client, auth)
                for title, loaded, total, shown, feature in watchlist_report(client):
                    complete = not total or loaded >= int(total)
                    detail = t["watchlist_line"].format(loaded, total or "?", shown, feature or "-")
                    if not shown:
                        # Editorial rail on the watchlist page (no titles of yours).
                        status = "info"
                    else:
                        status = "ok" if complete and shown >= loaded else "warn"
                    checks.append((status, t["watchlist"].format(title), detail))
            except Exception as exc:
                checks.append(("warn", t["watchlist"].format("-"), type(exc).__name__ + ": " + str(exc)[:120]))
        log_lines = diagnostics_mod.kodi_log_excerpt(["videoland"], diagnostics_mod.redact)
        text = diagnostics_mod.render(t, checks)
        path = diagnostics_mod.save_report(os.path.join(data_dir(), "diagnostics"), "videoland",
                                           diagnostics_mod.redact(text), log_lines)
        text = diagnostics_mod.render(t, checks, path)
    finally:
        progress.close()
    xbmcgui.Dialog().textviewer("Videoland - " + t["title"], text)


def check_tmdb_key():
    """Settings button: test the saved TMDb key and say exactly what is wrong."""
    status, detail = metadata_mod.test_tmdb_key(setting("tmdb_api_key"))
    if detail:
        xbmc.log("[Videoland] TMDb key test: {} ({})".format(status, detail), xbmc.LOGINFO)
    message = {"ok": 31133, "missing": 31146, "invalid": 31134, "offline": 31147}[status]
    xbmcgui.Dialog().ok("Videoland", ADDON.getLocalizedString(message))


import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from .api import (
    ApiError,
    AuthError,
    VideolandApi,
    action_target,
    block_season,
    is_hero_block,
    is_related_block,
    navigation_entries,
    video_assets,
    walk_item_content,
)
from .crypto import CipherError, decrypt_json, encrypt_json
from . import library as library_mod
from . import metadata as metadata_mod
from . import library_art
from . import errors as errors_mod
from . import diagnostics as diagnostics_mod
from . import search_filters
from . import logo_cache as logo_cache_mod
from . import playback_extras
from .progress import ProgressWriter, heartbeat_config, monitor_class
from . import watch_sync
from . import watch_history
from . import library_resume
from . import corner
from .sync_store import DurableWriter, SyncStore


ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
ADDON_PATH = ADDON.getAddonInfo("path")
FANART = os.path.join(ADDON_PATH, "resources", "media", "fanart-cinema.png")
ADDON_ICON = os.path.join(ADDON_PATH, "icon.png")
BREADCRUMB = ["Videoland"]


def set_breadcrumb(parts):
    global BREADCRUMB
    BREADCRUMB = list(parts)
    # Kodi already displays the addon name before the category heading.
    xbmcplugin.setPluginCategory(HANDLE, " / ".join(BREADCRUMB[1:]))


def read_breadcrumb(value):
    try:
        parts = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parts, list) or not parts or parts[0] != "Videoland":
        return []
    return parts if all(isinstance(part, str) and part.strip() for part in parts) else []


def setting(name, default=""):
    return ADDON.getSettingString(name) or default


def local_history():
    return ADDON.getSettingString("history_source") == "local"


def cloud_sync_enabled():
    return not local_history() and setting_bool("sync_progress", True)


def require_cloud_history():
    if local_history():
        xbmcgui.Dialog().ok("Videoland", ADDON.getLocalizedString(31096))
        return False
    return True


def setting_bool(name, default=False):
    try:
        return ADDON.getSettingBool(name)
    except Exception:
        value = setting(name, "")
        return {"true": True, "false": False}.get(value.lower(), default)


def setting_int(name, default=0):
    try:
        return int(ADDON.getSettingInt(name))
    except Exception:
        value = setting(name, "")
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def save(name, value):
    ADDON.setSettingString(name, value or "")


def cache_dir():
    base = xbmcvfs.translatePath("special://profile/addon_data/plugin.video.videoland.nl")
    path = os.path.join(base, "cache")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def profile_cache_dir():
    """Cache folder of the active profile: lists differ per profile."""
    profile = "".join(ch for ch in setting("profile_id") if ch.isalnum() or ch in "-_")[:64]
    return os.path.join(cache_dir(), profile or "default")


def data_dir():
    """Add-on data directory (holds the device-bound encryption key)."""
    return xbmcvfs.translatePath("special://profile/addon_data/plugin.video.videoland.nl")


_CACHE_TTLS = (1800, 21600, 86400, 259200, 604800)


def cache_ttl():
    index = setting_int("cache_ttl", 0)
    try:
        return _CACHE_TTLS[index]
    except IndexError:
        return 1800


def api():
    device_id = setting("device_id")
    enabled = setting_bool("use_cache", True)
    client = VideolandApi(
        device_id or None,
        cache_dir=profile_cache_dir() if enabled else None,
        cache_ttl=cache_ttl() if enabled else 0,
    )
    if not device_id:
        save("device_id", client.device_id)
    return client


_SORTABLE_ACTIONS = {"layout", "search", "related", "continue_watching", "library"}


def add_sort_methods(action=None, season=None):
    """Kodi's sort menu for list pages; the first option keeps Videoland's order."""
    if action not in _SORTABLE_ACTIONS:
        return
    names = ["SORT_METHOD_UNSORTED"]
    if season not in (None, "", "None"):
        names.append("SORT_METHOD_EPISODE")
    names += ["SORT_METHOD_LABEL_IGNORE_THE", "SORT_METHOD_VIDEO_YEAR"]
    for name in names:
        method = getattr(xbmcplugin, name, None)
        if method is not None:
            try:
                xbmcplugin.addSortMethod(HANDLE, method)
            except Exception:
                pass


def url(**params):
    return BASE_URL + "?" + urlencode(params)


def get_resume_position(layout, video_id):
    """Read the selected video's server resume time, never a related episode's."""
    for item, _block in walk_item_content(layout):
        video = item.get("video")
        if not isinstance(video, dict) or str(video.get("id")) != str(video_id):
            continue
        progress = video.get("progress")
        if not isinstance(progress, dict):
            continue
        position = progress.get("tcResume")
        if (isinstance(position, (int, float)) and not isinstance(position, bool)
                and math.isfinite(position) and position > 0):
            return int(position)
    return 0


def get_video_duration(layout, video_id):
    for item, _block in walk_item_content(layout):
        video = item.get("video")
        if not isinstance(video, dict) or str(video.get("id")) != str(video_id):
            continue
        duration = video.get("duration")
        if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and math.isfinite(duration) and duration > 0):
            return float(duration)
    return 0.0


def add(label, route, folder=True, art=None, info=None, playable=False, icon_key=None, context_menu=None, suppress_watched=False):
    if folder:
        # Carry the actual labels through every route, including seasons/rails.
        # SEO slugs are request identifiers, not names suitable for navigation.
        parsed = urlsplit(route)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["breadcrumb"] = json.dumps(BREADCRUMB + [label], ensure_ascii=False)
        route = urlunsplit(parsed._replace(query=urlencode(params)))
    item = xbmcgui.ListItem(label=label)
    art = dict(art or {})
    art.setdefault("fanart", FANART)
    art.setdefault("icon", ADDON_ICON)
    icon_path = menu_icon(icon_key)
    if icon_path:
        art["icon"] = icon_path
        art.setdefault("thumb", FANART)
        glyph = os.path.join(os.path.dirname(icon_path), "list-" + os.path.basename(icon_path))
        if os.path.isfile(glyph):
            item.setProperty("videoland.menuicon", glyph)
    art.setdefault("thumb", ADDON_ICON)
    if art:
        item.setArt(art)
    if info:
        item.setInfo("video", info)
    if playable:
        item.setProperty("ForceResolvePlugin", "true")
        # Live TV must never surface a watched/resume state, even when local
        # history is enabled: linear channels have no meaningful resume point.
        if suppress_watched or not local_history():
            # Explicit empty state prevents Kodi filling these fields from its DB.
            tag = item.getVideoInfoTag()
            tag.setPlaycount(0)
            tag.setResumePoint(0.0, 1.0)
            item.setProperty("OverrideInfotag", "true")
        # Mark the item as a directly playable video so pressing Enter triggers
        # playback immediately instead of requiring right-click -> Play.
        item.setProperty("IsPlayable", "true")
    if context_menu:
        item.addContextMenuItems(context_menu)
    xbmcplugin.addDirectoryItem(HANDLE, route, item, folder)


# Mapping of menu labels (and localised names) to the flat rounded-tile icon.
_ICON_DIR = os.path.join(ADDON_PATH, "resources", "icons", "tiles")
_ICON_MAP = {
    **{name: name for name in ("top10", "genres", "romance", "crime", "action",
                               "awards", "autumn", "recent", "night", "featured", "collection",
                               "continue", "recommended", "preview")},
    "home": "home",
    "series": "series",
    "serie": "series",
    "films": "films",
    "film": "films",
    "movies": "films",
    "programma": "programmas",
    "programma's": "programmas",
    "programs": "programmas",
    "kids": "kids",
    "kinderen": "kids",
    "trending": "trending",
    "google trends": "trending",
    "zoeken": "zoeken",
    "search": "zoeken",
    "aanmelden": "aanmelden",
    "inloggen": "aanmelden",
    "login": "aanmelden",
    "afmelden": "afmelden",
    "uitloggen": "afmelden",
    "logout": "afmelden",
    "cache": "cache",
    "cache wissen": "cache",
    "profiel": "profiel",
    "mijn kijklijst": "kijklijst",
    "kijklijst": "kijklijst",
    "live tv": "live",
    "tv en gids": "live",
    "bibliotheek": "bibliotheek",
    "library": "bibliotheek",
    "widgets": "widgets",
}


def menu_icon(key):
    """Return the absolute path to a matching flat icon, or None."""
    if not key:
        return None
    stem = _ICON_MAP.get(str(key).strip().lower())
    if not stem:
        return None
    path = os.path.join(_ICON_DIR, stem + ".png")
    return path if os.path.isfile(path) else None


def collection_icon(title, block=None):
    """Recognize recurring functions, leaving editorial collections neutral."""
    title = str(title or "").strip().casefold()
    block = block or {}
    feature = block.get("feature", "")
    # Promotional banners can contain words like 'nieuw' or 'top 10'.
    if block.get("template") == "Banner":
        return "collection"
    if feature == "feature.recommended_videos_by_user" or title == "verder kijken":
        return "continue"
    if feature == "feature.recommended_programs_by_user" or title == "aanbevolen voor jou":
        return "recommended"
    if title == "vooruitkijken":
        return "preview"
    if title in ("genres", "wat wil je kijken?"):
        return "genres"
    if title.startswith("top 10") or (
            feature == "feature.list" and title.startswith("populair bij")):
        return "top10"
    if title.startswith(("onlangs toegevoegd", "recent toegevoegd", "nieuw toegevoegd")) or title == "nieuw bij videoland":
        return "recent"
    if title.startswith("best bekeken"):
        return "trending"
    return "collection" if title else "featured"



def content_art(image):
    """Keep catalogue artwork as thumbnails; backgrounds come from hero_art."""
    if not isinstance(image, dict):
        return {}
    image_id = image.get("id")
    base = "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw"
    art = {}
    if image_id:
        art.update(thumb=base.format(image_id), icon=base.format(image_id))
    return art


def ratio_image(image, ratios):
    """URL of a card image in one of the given aspect ratios ("2:3", "16:9"...)."""
    if not isinstance(image, dict):
        return ""
    by_ratio = image.get("idsByRatio") or {}
    for ratio in ratios:
        image_id = by_ratio.get(ratio) or (image.get("id") if image.get("ratio") == ratio else None)
        if image_id:
            return "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw".format(image_id)
    return ""


def hero_art(layout):
    """Read the title-page Jumbotron, never a catalogue/recommendation card."""
    for block in layout.get("blocks", []):
        content = block.get("content") or {}
        if content.get("contentTemplateId") != "Jumbotron":
            continue
        for item, _section in walk_item_content(content):
            image = item.get("image") or {}
            image_id = (image.get("idsByRatio") or {}).get("16:9")
            if not image_id and image.get("ratio") == "16:9":
                image_id = image.get("id")
            if image_id:
                return {"fanart": "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw".format(image_id)}
    return {}


def auth_data():
    """Return the decrypted session tokens, or {} if absent/unreadable."""
    stored = setting("auth_json", "")
    decrypted = decrypt_json(data_dir(), stored) if stored else {}
    if decrypted:
        return decrypted
    # Migrate a legacy plaintext session (written by older versions) into the
    # encrypted store exactly once, then it is no longer readable in clear text.
    if stored and _looks_like_legacy_session(stored):
        legacy = json.loads(stored)
        store_auth(legacy)
        return legacy
    return {}


def _looks_like_legacy_session(value):
    try:
        candidate = json.loads(value)
    except ValueError:
        return False
    return isinstance(candidate, dict) and all(
        candidate.get(key) for key in ("uid", "signature", "timestamp")
    )


def store_auth(auth):
    """Encrypt and persist the session tokens."""
    if auth:
        save("auth_json", encrypt_json(data_dir(), auth))
    else:
        save("auth_json", "")


def credentials_data():
    """Return stored (email, password) for auto-relogin, or (None, None)."""
    creds = decrypt_json(data_dir(), setting("secret_json", "")) if setting("secret_json", "") else {}
    email = creds.get("email")
    password = creds.get("password")
    if email and password:
        return email, password
    return None, None


def store_credentials(email, password):
    """Encrypt and persist login credentials so sessions can be refreshed."""
    if email and password:
        save("secret_json", encrypt_json(data_dir(), {"email": email, "password": password}))
    else:
        save("secret_json", "")


def refresh_session():
    """Re-authenticate from the stored encrypted credentials.

    Returns fresh (client, auth, profile_id). If credentials were never saved,
    ask for them on Kodi and encrypt them for future renewals.
    """
    email, password = credentials_data()
    client = api()
    if email and password:
        auth = client.login(email, password)
        store_auth(auth)
    else:
        auth = interactive_login()
    profile_id = _resolve_profile(client, auth)
    save("profile_id", profile_id or "")
    return client, auth, profile_id


def ensure_login():
    auth = auth_data()
    if all(auth.get(key) for key in ("uid", "signature", "timestamp")):
        return auth
    # Refresh silently when credentials exist; otherwise ask once on Kodi.
    _client, fresh, _pid = refresh_session()
    return fresh


def interactive_login():
    """Ask for credentials locally and save them encrypted after successful login."""
    email = xbmcgui.Dialog().input("Videoland e-mailadres", type=xbmcgui.INPUT_ALPHANUM)
    if not email:
        raise ApiError("Aanmelden geannuleerd")
    password = xbmcgui.Dialog().input("Videoland wachtwoord", type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT)
    if not password:
        raise ApiError("Aanmelden geannuleerd")
    client = api()
    auth = client.login(email, password)
    store_auth(auth)
    store_credentials(email, password)
    return auth


def ensure_profile(client, auth):
    profile_id = setting("profile_id")
    if profile_id:
        client.jwt(auth, profile_id)
        return profile_id
    # The profiles endpoint requires the account-scoped Bedrock JWT.
    client.jwt(auth)
    profiles = client.profiles(auth["uid"])
    if not profiles:
        raise ApiError("Geen Videoland-profielen gevonden")
    if len(profiles) == 1:
        selected = profiles[0]
    else:
        labels = [p.get("username") or "Profiel {}".format(i + 1) for i, p in enumerate(profiles)]
        index = xbmcgui.Dialog().select("Kies Videoland-profiel", labels)
        if index < 0:
            raise ApiError("Profielkeuze geannuleerd")
        selected = profiles[index]
    profile_id = selected.get("uid")
    if not profile_id:
        raise ApiError("Het gekozen profiel heeft geen ID")
    save("profile_id", profile_id)
    save("profile_name", selected.get("username") or "")
    client.jwt(auth, profile_id)  # Validate and activate the profile session.
    return profile_id


def choose_profile():
    client = api()
    auth = ensure_login()
    client.jwt(auth)
    profiles = client.profiles(auth["uid"])
    if not profiles:
        raise ApiError("Geen Videoland-profielen gevonden")
    labels = [p.get("username") or ADDON.getLocalizedString(31053).format(i + 1)
              for i, p in enumerate(profiles)]
    if len(profiles) == 1:
        xbmcgui.Dialog().ok(ADDON.getLocalizedString(31050),
                           ADDON.getLocalizedString(31051).format(labels[0]))
        return
    index = xbmcgui.Dialog().select(ADDON.getLocalizedString(31050), labels)
    if index < 0:
        return
    profile_id = profiles[index].get("uid")
    if not profile_id:
        raise ApiError("Het gekozen profiel heeft geen ID")
    client.jwt(auth, profile_id)
    save("profile_id", profile_id)
    save("profile_name", labels[index])
    VideolandApi.clear_cache(cache_dir())
    xbmc.executebuiltin("Container.Refresh")
    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31052).format(labels[index]))


def _resolve_profile(client, auth):
    """Non-interactive profile resolution used for silent auto-relogin."""
    profile_id = setting("profile_id")
    if profile_id:
        client.jwt(auth, profile_id)
        return profile_id
    client.jwt(auth)
    profiles = client.profiles(auth["uid"]) or []
    first = profiles[0] if profiles else {}
    pid = first.get("uid")
    if not pid:
        raise ApiError("Geen Videoland-profielen gevonden")
    client.jwt(auth, pid)
    return pid


def active_profile_name(client, auth):
    name = setting("profile_name")
    if name:
        return name
    profile_id = setting("profile_id")
    client.jwt(auth)
    profiles = client.profiles(auth["uid"])
    client.jwt(auth, profile_id)
    name = next((p.get("username") for p in profiles if p.get("uid") == profile_id), None)
    name = name or ADDON.getLocalizedString(31076)
    save("profile_name", name)
    return name


def show_sync_status():
    if not require_cloud_history():
        return
    auth = auth_data()
    state = SyncStore(data_dir()).status(auth.get("uid", ""), setting("profile_id"))
    saved = state.get("saved_at")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(saved)) if saved else ADDON.getLocalizedString(31072)
    position = state.get("position")
    if position is not None:
        stamp += " ({}:{:02d})".format(int(position) // 60, int(position) % 60)
    error = ADDON.getLocalizedString(31074 if state.get("error") == "auth" else 31075) if state.get("error") else ADDON.getLocalizedString(31073)
    lines = [ADDON.getLocalizedString(31060).format(setting("profile_name") or ADDON.getLocalizedString(31076)),
             ADDON.getLocalizedString(31067).format(stamp),
             ADDON.getLocalizedString(31068).format(state['pending']),
             ADDON.getLocalizedString(31069).format(error),
             ADDON.getLocalizedString(31070 if setting_bool("sync_progress", True) else 31071)]
    xbmcgui.Dialog().textviewer(ADDON.getLocalizedString(31062), "\n\n".join(lines))


def continue_removal_id(item):
    for action in item.get("secondaryActions") or []:
        if not isinstance(action, dict):
            continue
        target = action.get("target") or {}
        app = target.get("value_app") or {}
        if target.get("type") == "app" and app.get("reference") == "remove_from_continuous_watching":
            content_id = (app.get("details") or {}).get("id")
            if content_id is not None:
                return str(content_id)
    return None


def remove_continue_watching(content_id, profile_id, title):
    if not require_cloud_history():
        return
    # A context menu from a previously selected profile must never remove from
    # the profile now active in Kodi.
    if not profile_id or setting("profile_id") != profile_id:
        raise ApiError(ADDON.getLocalizedString(31082))
    client = api()
    auth = ensure_login()
    client.jwt(auth, profile_id)
    SyncStore(data_dir()).remove_content(
        auth["uid"], profile_id, content_id, lambda: client.remove_continue_watching(content_id))
    VideolandApi.clear_cache(cache_dir())
    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31081).format(title),
                                 time=3000, sound=False)
    xbmc.executebuiltin("Container.Refresh")


def continue_watching():
    if not require_cloud_history():
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    # This action explicitly reloads from Videoland, including every rail page.
    client.cache_dir = None
    client.cache_ttl = 0
    def is_continue(block):
        metadata = (block.get("analytics") or {}).get("tealium") or {}
        return (metadata.get("from") == "feature.recommended_videos_by_user"
                or str(metadata.get("block_title", "")).casefold() == "verder kijken")
    data = client.layout("alias", "home", complete=True, block_filter=is_continue)
    data = dict(data, blocks=[b for b in data.get("blocks", []) if is_continue(b)])
    set_breadcrumb(["Videoland", ADDON.getLocalizedString(31079)])
    xbmcplugin.setContent(HANDLE, "videos")
    add(ADDON.getLocalizedString(31061), url(action="continue_watching"), True, icon_key="continue")
    rows = _build_rows(data)
    if not rows:
        xbmcgui.Dialog().ok("Videoland", ADDON.getLocalizedString(31078))
    _render_rows(rows, client, hero_art(data))
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def root():
    set_breadcrumb(["Videoland"])
    xbmcplugin.setContent(HANDLE, "files")
    auth = auth_data()
    if not auth:
        add(ADDON.getLocalizedString(31141), url(action="login"), False, icon_key="aanmelden")
    else:
        client = api()
        ensure_profile(client, auth)
        try:
            navigation = client.navigation("desktop")
        except AuthError:
            raise
        except ApiError as exc:
            xbmc.log("[Videoland] Navigation fallback: {}".format(exc), xbmc.LOGWARNING)
            navigation = []
        added = add_navigation(navigation)
        if not added:
            add_default_navigation()
        # Order: browse (from Videoland), own lists, then account entries last.
        if not local_history():
            add(ADDON.getLocalizedString(31061), url(action="continue_watching"), True, icon_key="continue")
        add(ADDON.getLocalizedString(31120), url(action="library"), True, icon_key="bibliotheek")
        add(ADDON.getLocalizedString(31182), url(action="widgets"), True, icon_key="widgets")
        add(ADDON.getLocalizedString(31194), url(action="history"), True, icon_key="continue")
        name = active_profile_name(client, auth)
        add(ADDON.getLocalizedString(31060).format(name), url(action="profiles"), False, icon_key="profiel")
        add(ADDON.getLocalizedString(31142), url(action="logout"), False, icon_key="afmelden")
    add(ADDON.getLocalizedString(31143), url(action="clear_cache"), False, icon_key="cache")
    xbmcplugin.endOfDirectory(HANDLE)


def add_navigation(navigation):
    """Add the useful desktop navigation entries returned by Videoland."""
    added = set()
    live_tv_added = False
    app_routes = {
        "search": ("search", "search", "Zoeken"),
        "account_bookmarks": ("layout", "bookmarks", "Mijn Kijklijst"),
    }
    for entry in navigation_entries(navigation):
        target = entry.get("target") or {}
        label = entry.get("label")
        if target.get("type") == "layout":
            if not label:
                continue
            value = target.get("value_layout") or {}
            kind = value.get("type")
            entity_id = str(value.get("id") or "")
            if kind == "frontspace" and entity_id == "epggrid":
                live_tv_added = True
                add(label, url(action="live"), True, icon_key=label)
                continue
            if kind not in ("alias", "folder") or not entity_id:
                continue
            if label and "live tv" in label.lower():
                live_tv_added = True
            key = (kind, entity_id)
            if key in added:
                continue
            added.add(key)
            add(label, url(
                action="layout", kind=kind, entity_id=entity_id, seo=value.get("seo", "")
            ), True, icon_key=label)
        elif target.get("type") == "app":
            value = target.get("value_app") or {}
            reference = value.get("reference")
            if reference not in app_routes:
                continue
            action, entity_id, default_label = app_routes[reference]
            label = label or (value.get("details") or {}).get("title") or default_label
            key = ("app", reference)
            if key in added:
                continue
            added.add(key)
            if action == "search":
                add(label, url(action="search"), True, icon_key=label)
            else:
                add(label, url(action="layout", kind="frontspace", entity_id=entity_id), True, icon_key=label)
    if not live_tv_added:
        # Add Live TV entry as a fallback if not present in API navigation
        add("Live TV", url(action="live"), True, icon_key="Live TV")
    return bool(added)


def add_default_navigation():
    """Keep the add-on useful during a temporary navigation API outage."""
    add("Home", url(action="layout", kind="alias", entity_id="home"), True, icon_key="home")
    for label, entity_id, seo in (
        ("Series", "580", "series-menu-videoland"),
        ("Films", "581", "films-menu-videoland"),
        ("Programma's", "582", "programmas-menu-videoland"),
        ("Kids", "583", "videoland-kids-menu-videoland"),
        ("Trending", "25", "main-menu-2-mobile"),
        ("Live TV", "epggrid", "epggrid"),
    ):
        if label == "Live TV":
            add(label, url(action="live"), True, icon_key=label)
            continue
        add(label, url(action="layout", kind="frontspace", entity_id=entity_id, seo=seo), True, icon_key=label)
    add("Zoeken", url(action="search"), True, icon_key="zoeken")


PERSONAL_PAGES = {("frontspace", "bookmarks")}


def watchlist_report(client):
    """Per watchlist block: (title, items loaded, total Videoland reports, rows shown)."""
    client.cache_dir = None
    client.cache_ttl = 0
    data = client.layout("frontspace", "bookmarks", "https://v2.videoland.com/", complete=True)
    report = []
    for block in data.get("blocks", []):
        content = block.get("content") or {}
        items = content.get("items") if isinstance(content.get("items"), list) else []
        pagination = content.get("pagination") or {}
        total = pagination.get("totalItems") or content.get("totalItems") or block.get("totalItems")
        title = str(block.get("block_title") or (block.get("analytics") or {}).get("tealium", {}).get("block_title")
                    or block.get("feature") or "?")
        shown = len(_build_rows({"blocks": [block]}))
        report.append((title, len(items), total, shown, str(block.get("feature") or "")))
    return report


def show_layout(kind, entity_id, seo="", season=None, section=None, group=None):
    if kind == "frontspace" and entity_id == "epggrid":
        # Legacy favourites/URLs target the EPG grid directly; the Live TV
        # page renders the channels as directly playable entries instead.
        return live_tv()
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/"
    location_suffixes = {"program": "p", "video": "c", "folder": "f"}
    if kind in location_suffixes and seo:
        location += "{}-{}_{}".format(seo, location_suffixes[kind], entity_id.replace("clip_", ""))
    catalog = (kind == "folder" or (kind == "alias" and entity_id == "home")) and group != "genre"

    def load_block(block):
        tealium = (block.get("analytics") or {}).get("tealium") or {}
        if not catalog:
            return not is_related_block({"feature": tealium.get("from"), "block_title": tealium.get("block_title")})
        title = str(tealium.get("block_title") or "").strip()
        if group == "genres" or (group is None and section is None):
            # Menus need all genre folders, but only a preview of each rail
            # to create its submenu. Load titles when that submenu is opened.
            return title.casefold() in ("genres", "genre", "categorieën", "categorieen", "wat wil je kijken?")
        return title == ("" if group == "featured" else section)

    if (kind, str(entity_id)) in PERSONAL_PAGES:
        # The watchlist changes whenever you add a title: always load it fresh.
        client.cache_dir = None
        client.cache_ttl = 0
    data = client.layout(kind, entity_id, location, complete=True, block_filter=load_block)
    if BREADCRUMB == ["Videoland"]:
        # Compatibility with old favourites/URLs that lack a breadcrumb.
        label = {("alias", "home"): "Home", ("folder", "580"): "Series",
                 ("folder", "581"): "Films", ("folder", "582"): "Programma's",
                 ("folder", "583"): "Kids", ("folder", "25"): "Trending",
                 ("frontspace", "bookmarks"): "Mijn Kijklijst"}.get((kind, str(entity_id)))
        if not label:
            entity = data.get("entity") or {}
            label = entity.get("title") if isinstance(entity, dict) else None
        if not label:
            for block in data.get("blocks", []):
                content = block.get("content") or {}
                if content.get("contentTemplateId") == "Jumbotron":
                    label = next(((item.get("image") or {}).get("caption") or item.get("title")
                                  for item, _ in walk_item_content(content)), None)
                    if label:
                        break
        parts = ["Videoland"] + ([label] if isinstance(label, str) and label else [])
        if section:
            parts.append(section)
        if season is not None:
            parts.append("Seizoen {}".format(season))
        set_breadcrumb(parts)
    show_items(data, season=season, section=section, client=client,
               grouped_catalog=catalog, genres_only=group == "genres",
               collection_section="" if group == "featured" else section,
               catalog_route={"kind": kind, "entity_id": entity_id, "seo": seo})



def is_recommendation_block(block):
    feature = str(block.get("feature") or "").casefold()
    title = str(block.get("block_title") or "").strip().casefold()
    if any(word in feature or word in title for word in ("trailer", "advertis")):
        return False
    return (title in ("anderen kijken ook", "others also watch")
            or (feature.endswith("by_program")
                and any(word in feature for word in ("recommend", "related", "similar"))))


def show_related(kind, entity_id, seo="", title=""):
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    def load_block(block):
        metadata = (block.get("analytics") or {}).get("tealium") or {}
        return is_recommendation_block({"feature": metadata.get("from"),
                                        "block_title": metadata.get("block_title")})
    location = program_location(seo, entity_id) if kind == "program" else "https://v2.videoland.com/"
    data = client.layout(kind, entity_id, location, complete=True, block_filter=load_block)
    # Older video cards may lack a parent in their action. Resolve it from the
    # detail hero so recommendations still come from the containing programme.
    if kind == "video":
        parent = _program_identity(data)
        if parent and parent.get("kind") == "program":
            data = client.layout("program", parent["entity_id"],
                                 program_location(parent.get("seo", ""), parent["entity_id"]),
                                 complete=True, block_filter=load_block)
    heading = ADDON.getLocalizedString(31100)
    set_breadcrumb(["Videoland"] + ([title] if title else []) + [heading])
    xbmcplugin.setContent(HANDLE, "videos")
    rows = _build_rows(data, recommendations_only=True)
    if not rows:
        xbmcgui.Dialog().ok(heading, ADDON.getLocalizedString(31101))
    _render_rows(rows, client)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def _episode_number(item):
    """Return the episode number from item metadata when present.

    Bedrock episode items use ``extraTitle`` like "1. Aflevering 1"; the leading
    integer is the episode number. Some items expose an explicit ``episode`` field.
    """
    episode = item.get("episode") or (item.get("metadata") or {}).get("episode")
    if episode is not None:
        try:
            return int(episode)
        except (TypeError, ValueError):
            pass
    label = item.get("extraTitle") or item.get("title") or ""
    if isinstance(label, str):
        tokens = label.lstrip().split()
        if tokens:
            token = tokens[0].lstrip("#")
            digits = ""
            for ch in token:
                if ch.isdigit():
                    digits += ch
                elif ch in (".", ")", "-", ":"):
                    continue
                else:
                    break
            if digits:
                return int(digits)
    return None


def _season_episode(item, block):
    """Return a (season, episode) tuple when enough metadata is available.

    The season comes from the containing block title (e.g. "Seizoen 1") because
    individual episode items in the Bedrock payload do not carry a season field.
    """
    season = block_season(block)
    episode = _episode_number(item)
    if episode is None:
        return None
    return (season if season is not None else 0, episode)


def _clean_episode_label(text):
    """Remove a leading episode marker ('1. ', '2)', '3 - ') from a label.

    Bedrock prefixes episode ``extraTitle`` with the episode number, e.g.
    "1. Extreme Gebedsgenezers"; artwork captions already hold the clean name.
    Stripping the marker lets items without artwork be labelled correctly.
    """
    text = (text or "").strip()
    if not text:
        return ""
    token = text.split(None, 1)[0].lstrip("#")
    length = 0
    for char in token:
        if char.isdigit() or char in ".-):":
            length += 1
        else:
            break
    if length and length == len(token):
        rest = text[len(token):].lstrip(" .-):")
        return rest.strip() or text
    return text


def _episode_details(layout):
    """Return the (title, synopsis) of the requested episode from its detail page.

    Video-detail layouts put the clean episode name in ``entity.metadata.title``
    and the episode synopsis on the playable item inside the player block.
    """
    title = ""
    entity = layout.get("entity") or {}
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
    candidate = metadata.get("title") if metadata else None
    if isinstance(candidate, str) and candidate.strip():
        title = candidate.strip()
    if not title:
        seo = layout.get("seo") if isinstance(layout.get("seo"), dict) else {}
        candidate = seo.get("title")
        if isinstance(candidate, str) and candidate.strip():
            title = candidate.strip()
    plot = ""
    for item, block in walk_item_content(layout):
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            continue
        if str((block or {}).get("feature") or "") == "feature.videos_for_player":
            return title, description.strip()
        if not plot:
            plot = description.strip()
    return title, plot


def _needs_episode_detail(item, target, target_kind):
    """True when a video (episode) row lacks a synopsis on its card.

    Season cards carry ``null`` descriptions; the episode's own video layout
    holds the real synopsis (and a clean title). Fetch it lazily so lists mirror
    what Videoland's player page shows.
    """
    return target_kind == "video" and not str(item.get("description") or "").strip()


def program_location(seo, entity_id):
    """Build the web location string used to render a program detail page."""
    location = "https://v2.videoland.com/"
    if seo:
        location += "{}-p_{}".format(seo, entity_id)
    return location


def video_location(target):
    """Build the web location string used to render an episode/clip detail page."""
    target = target or {}
    parent = target.get("parent") or {}
    location = "https://v2.videoland.com/"
    if parent.get("id") and parent.get("seo") and target.get("seo"):
        location += "{}-p_{}/{}-c_{}".format(
            parent.get("seo"), parent.get("id"), target.get("seo"),
            str(target.get("id") or "").replace("clip_", ""))
    return location


def _play_target(client, item, target, target_kind, program_data=None):
    """Return the target to play (video id/seo/parent), or None.

    ``video`` items (episodes/clips) play directly. ``program`` items can be a
    single film whose program page resolves to exactly one playable clip; we peek
    at the cached program layout to detect that and play it straight away instead
    of presenting the film as a navigable series folder. Series keep their
    folder/season UI.
    """
    if target_kind in ("video", "live"):
        return target
    if target_kind not in ("program", "details"):
        return None
    video = item.get("video") or {}
    target_id = str(target.get("id") or "")
    own_id = str(video.get("id") or "")
    # Item that already carries an inline clip id or stream assets.
    if target_id.startswith("clip_") or own_id.startswith("clip_") or bool(video.get("assets") or video.get("path")):
        return target
    if client is None:
        return None
    # Inspect the program page: a real film resolves to one playable clip with no
    # season grouping, whereas a series resolves to seasons/episodes.
    data = program_data if program_data is not None else client.layout("program", target_id, program_location(target.get("seo", ""), target_id))
    rows = _build_rows(data)
    video_rows = [r for r in rows if r[2] == "video"]
    if len(rows) == 1 and video_rows and not _all_seasons(rows):
        clip_target = video_rows[0][1]
        if clip_target and clip_target.get("id"):
            return clip_target
    return None


def _build_rows(data, per_section=False, recommendations_only=False):
    """Collect and de-duplicate the real content items from a layout.

    De-duplication is scoped per block (its title) when ``per_section`` is set,
    or across the whole page otherwise. The Home page groups output into titled
    rails that legitimately repeat popular programs (e.g. a program can appear in
    both "Onlangs toegevoegd" and "Top 10 van vandaag"); a page-global de-dup
    there would wrongly empty those rails, so Home builds with per-section de-dup.
    Flat collection pages (Films/Series/Programma's) use global de-dup to avoid
    listing the same title twice.
    """
    seen = {}
    rows = []
    for item, block in walk_item_content(data):
        if local_history() and (continue_removal_id(item)
                or block.get("feature") == "feature.recommended_videos_by_user"
                or str(block.get("block_title", "")).casefold() in ("verder kijken", "continue watching")):
            continue
        target = action_target(item)
        if not target:
            continue
        target_id = str(target.get("id") or "")
        target_kind = target.get("type")
        if not target_id or target_kind not in (
            "program", "video", "alias", "folder", "service", "season", "details", "live"
        ):
            continue
        # Drop recommendation/trailer/hero/ad rails; keep only real content.
        if recommendations_only:
            if not is_recommendation_block(block):
                continue
        elif is_related_block(block):
            continue
        if per_section:
            bucket = str((block or {}).get("block_title") or "")
            key = (bucket, target_kind, target_id)
        else:
            key = (target_kind, target_id)
        if key in seen:
            # The page hero (Jumbotron) re-uses the featured/latest episode id and
            # would shadow the real card from its season block; prefer the actual
            # listing card over the hero duplicate.
            old = rows[seen[key]]
            if is_hero_block(old[3]) and not is_hero_block(block):
                rows[seen[key]] = (item, target, target_kind, block)
            continue
        seen[key] = len(rows)
        rows.append((item, target, target_kind, block))

    season_episode = [_season_episode(item, block) for item, _t, _k, block in rows]
    if all(se is not None for se in season_episode):
        rows = [r for _, r in sorted(zip(season_episode, rows), key=lambda x: ((x[0][0] or 0), (x[0][1] or 0)))]
    return rows


def _needs_program_peek(item, target, target_kind):
    """True when a ``program`` row carries no inline clip/assets and must be
    resolved against its program page to decide film-vs-series."""
    if target_kind not in ("program", "details"):
        return False
    video = item.get("video") or {}
    target_id = str(target.get("id") or "")
    own_id = str(video.get("id") or "")
    if target_id.startswith("clip_") or own_id.startswith("clip_") or bool(video.get("assets") or video.get("path")):
        return False
    return True


def _item_label(item, fallback=""):
    """Display name of a catalogue card (title, caption or cleaned extraTitle)."""
    image = item.get("image") or {}
    caption = image.get("caption") if isinstance(image.get("caption"), str) else ""
    label = (
        item.get("title")
        or item.get("name")
        or caption
        or _clean_episode_label(item.get("extraTitle"))
        or item.get("extraTitle")
        or fallback
    )
    return label if isinstance(label, str) else str(label)


def _render_rows(rows, client=None, page_art=None, only_kind=None):
    """Add every collected row as a directory/playable entry."""
    # Resolve film-vs-series for whole program-list pages in parallel so a big
    # list (e.g. Films, ~90 movies) does not serialize one slow page fetch per
    # item. Program pages are cached, so repeat loads are cheap. Episode rows
    # whose cards carry no synopsis are also resolved against their own (cached)
    # video page to recover the per-episode title and description.
    resolve = {}
    backgrounds = {}
    episodes = {}
    pending = []
    if client is not None:
        for item, target, target_kind, _block in rows:
            parent = target.get("parent") or {}
            target_id = str(target.get("id") or "")
            needs_background = not page_art and (
                target_kind in ("program", "details") or
                (target_kind == "video" and parent.get("type") == "program" and parent.get("id"))
            )
            if (_needs_program_peek(item, target, target_kind) or needs_background) and target_id not in resolve:
                resolve[target_id] = None
                pending.append(("program", target_id, item, target, target_kind))
            if _needs_episode_detail(item, target, target_kind) and target_id not in episodes:
                episodes[target_id] = None
                pending.append(("episode", target_id, item, target, target_kind))

    if pending:
        if len(pending) >= 25 and setting("loading_notice_shown") != "true":
            xbmcgui.Dialog().notification(
                "Videoland — {} titels laden".format(len(pending)),
                "Bij veel films of series kan de eerste keer laden even duren.",
                time=8000, sound=False,
            )
            save("loading_notice_shown", "true")

        def _peek(args):
            kind, target_id, item, target, target_kind = args
            try:
                if kind == "episode":
                    data = client.layout("video", target_id, video_location(target))
                    return kind, target_id, _episode_details(data)
                program = (target.get("parent") or {}) if target_kind == "video" else target
                program_id = str(program.get("id") or target_id)
                data = client.layout("program", program_id, program_location(program.get("seo", ""), program_id))
                play_target = _play_target(client, item, target, target_kind, program_data=data)
                return kind, target_id, (play_target, hero_art(data))
            except AuthError:
                raise
            except Exception:
                return kind, target_id, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for kind, target_id, result in pool.map(_peek, pending):
                if result is None:
                    continue
                if kind == "episode":
                    episodes[target_id] = result
                else:
                    resolve[target_id], backgrounds[target_id] = result

    for item, target, target_kind, block in rows:
        target_id = str(target.get("id") or "")
        image = item.get("image") or {}
        # Folder/category items (e.g. genre rails like "Competitie") and episodes
        # carry their display name in the artwork caption; title/name are often
        # null. Prefer the caption over extraTitle because Bedrock prefixes
        # extraTitle with "N. " (e.g. "1. Het feest") while the caption holds the
        # clean episode/category name.
        caption = image.get("caption") if isinstance(image.get("caption"), str) else ""
        label = _item_label(item, target_id)
        episode_details = episodes.get(target_id)
        episode_title = episode_details[0] if isinstance(episode_details, tuple) else None
        episode_plot = episode_details[1] if isinstance(episode_details, tuple) else None
        if not (item.get("title") or item.get("name") or caption) and episode_title:
            label = episode_title
        art = content_art(image)
        art.update(page_art or {})
        art.update(backgrounds.get(target_id, {}))
        plot = (item.get("description") or "").strip() or episode_plot or ""
        info = {"title": label, "plot": plot}
        context_menu = []
        if target_kind in ("program", "details", "video"):
            related_target = target
            related_kind = "video" if target_kind == "video" or target_id.startswith("clip_") else "program"
            parent = target.get("parent") or {}
            if related_kind == "video" and parent.get("id"):
                related_target = parent
                related_kind = "program"
            context_menu.append((ADDON.getLocalizedString(31100), "Container.Update({})".format(url(
                action="related", kind=related_kind, entity_id=related_target.get("id", target_id),
                seo=related_target.get("seo", ""), title=label))))
        content_id = continue_removal_id(item)
        if content_id and not local_history():
            context_menu.append((ADDON.getLocalizedString(31080), "RunPlugin({})".format(url(
                action="remove_continue_watching", content_id=content_id,
                profile_id=setting("profile_id"), title=label))))
        episode_no = _episode_number(item)
        season_no = block_season(block)
        if episode_no is not None:
            info["episode"] = episode_no
        if season_no is not None:
            info["season"] = season_no
        if target_kind in ("program", "details") and target_id in resolve:
            play_target = resolve[target_id]
        else:
            play_target = _play_target(client, item, target, target_kind)
        if only_kind:
            if target_kind == "live":
                row_kind = "live"
            elif play_target:
                row_kind = "movie" if target_kind in ("program", "details") else "episode"
            else:
                row_kind = "series" if target_kind == "program" else "other"
            if row_kind != only_kind:
                continue
        library_kind = None
        if target_kind in ("program", "details") and play_target:
            library_kind = "movie"
        elif target_kind == "program" and not play_target:
            library_kind = "series"
        if library_kind:
            logo = _library_logos().get((library_kind, target_id))
            if not logo and _browse_logo_cache() is not None:
                logo = _browse_logo_cache().get(library_kind, label)
            if logo:
                art["clearlogo"] = logo
            in_library = _library_has(library_kind, target_id)
            context_menu.append((
                ADDON.getLocalizedString(31111 if in_library else 31110),
                "RunPlugin({})".format(url(
                    action="library_toggle", kind=library_kind, id=target_id,
                    seo=target.get("seo", ""), title=label,
                    poster=ratio_image(image, ("2:3", "3:4")) or art.get("thumb", ""),
                    fanart=backgrounds.get(target_id, {}).get("fanart") or ratio_image(image, ("16:9",)))),
            ))
        if target_kind == "live":
            add(label, url(
                action="play_live", channel_id=target.get("id", target_id),
                seo=target.get("seo", ""),
            ), False, art, info, playable=True, context_menu=context_menu)
        elif play_target:
            parent = play_target.get("parent") or {}
            add(label, url(
                action="play", video_id=play_target.get("id", target_id),
                seo=play_target.get("seo", ""),
                parent_id=parent.get("id", ""), parent_seo=parent.get("seo", "")
            ), False, art, info, playable=True, context_menu=context_menu)
        else:
            route = {}
            if is_genre((item, target, target_kind, block)):
                route["group"] = "genre"
            add(label, url(
                action="layout", kind=target_kind, entity_id=target_id, seo=target.get("seo", ""), **route
            ), True, art, info, context_menu=context_menu)


def _all_seasons(rows):
    seasons = set()
    for _item, _target, _kind, block in rows:
        s = block_season(block)
        if s is not None:
            seasons.add(s)
    return sorted(seasons)


def _program_identity(data):
    """Find the containing program from the hero item for re-fetching a series."""
    for item, block in walk_item_content(data):
        if (block or {}).get("feature") == "feature.info_by_program":
            target = action_target(item)
            parent = target.get("parent") or {}
            if parent.get("type") == "program" and parent.get("id"):
                return {"kind": "program", "entity_id": str(parent["id"]), "seo": str(parent.get("seo") or "")}
            if parent.get("id"):
                return {"kind": str(parent.get("type") or "program"), "entity_id": str(parent["id"]), "seo": str(parent.get("seo") or "")}
    return None


def _section_groups(rows):
    """Group collected rows by their block title, preserving first-seen order.

    The Videoland home page is composed of several titled horizontal rails (e.g.
    "Verder kijken", "Best bekeken programma's", "Top 10 van vandaag"). Grouping
    the items by those titles mirrors the real homepage's sectioned layout.
    Returns an ordered list of ``(title, [row...])`` using only sections that
    carry a human-readable title.
    """
    ordered = []
    index = {}
    for row in rows:
        title = str((row[3] or {}).get("block_title") or "").strip()
        if not title:
            continue
        if title not in index:
            index[title] = len(ordered)
            ordered.append((title, []))
        ordered[index[title]][1].append(row)
    return ordered


def show_sections(sections, program=None, season=None):
    """Present the titled homepage rails as folders, matching Videoland's layout."""
    for title, _rows in sections:
        add(title, url(
            action="layout",
            kind=(program or {}).get("kind", "alias"),
            entity_id=(program or {}).get("entity_id", "home"),
            seo=(program or {}).get("seo", ""),
            season="" if season is None else season,
            section=title,
        ), True, info={"title": title, "plot": "Ontdek {} op Videoland.".format(title)}, icon_key="home")


GENRES = {
    "true crime", "drama", "actie", "komedie", "nederlands", "animatie",
    "lhbti", "thriller", "misdaad", "mysterie", "familie", "avontuur",
    "fantasy", "romantiek", "documentaire", "documentaires",
}


def is_genre(row):
    item, _target, kind, block = row
    label = (item.get("title") or item.get("name") or
             (item.get("image") or {}).get("caption") or item.get("extraTitle") or "")
    return kind == "folder" and (str(label).strip().casefold() in GENRES or
                                 str((block or {}).get("block_title") or "").strip().casefold()
                                 in ("genres", "genre", "categorieën", "categorieen"))


def show_items(data, season=None, section=None, client=None, sectioned=False,
               grouped_catalog=False, genres_only=False, collection_section=None, catalog_route=None):
    xbmcplugin.setContent(HANDLE, "videos")
    rows = _build_rows(data)
    seasons = _all_seasons(rows)
    program = _program_identity(data)
    page_art = hero_art(data)
    if page_art:
        xbmcplugin.setPluginFanart(HANDLE, page_art["fanart"])

    if grouped_catalog:
        source = dict(catalog_route or {"kind": "folder", "entity_id": "581"})
        # Keep titles in every collection they belong to, even when repeated.
        rows = _build_rows(data, per_section=True)
        genres = [row for row in rows if is_genre(row)]
        if genres_only:
            xbmcplugin.setContent(HANDLE, "files")
            _render_rows(genres, client, page_art)
        elif collection_section is not None:
            _render_rows([row for row in rows if not is_genre(row)
                          and str((row[3] or {}).get("block_title") or "").strip() == collection_section],
                         client, page_art)
        else:
            xbmcplugin.setContent(HANDLE, "files")
            if genres:
                add("Genres", url(action="layout", group="genres", **source),
                    True, info={"title": "Genres", "plot": "Kies een genre."}, icon_key="genres")
            sections = {}
            for row in rows:
                if not is_genre(row):
                    title = str((row[3] or {}).get("block_title") or "").strip()
                    sections.setdefault(title, []).append(row)
            for title in sections:
                label = "Top 10" if title.casefold().startswith("top 10") else title or "Uitgelicht"
                add(label, url(action="layout", group="collection" if title else "featured", section=title, **source),
                    True, art=content_art(sections[title][0][0].get("image")),
                    info={"title": label, "plot": title or "Uitgelicht op Videoland."},
                    icon_key=collection_icon(title, sections[title][0][3]))
    elif section is not None:
        # Inside a chosen homepage rail: list only that section's items. Built and
        # de-duplicated per section so overlapping rails keep their full items.
        section_rows = [r for (t, rs) in _section_groups(_build_rows(data, per_section=True))
                        if t == section for r in rs]
        _render_rows(section_rows, client, page_art)
    elif sectioned:
        # Home layout: present the titled rails as folders, mirroring the grouped
        # appearance of the real homepage instead of one flat list. Only enabled
        # for the Home page; collection pages keep their plain flat lists.
        sections = _section_groups(_build_rows(data, per_section=True))
        if len(sections) > 1:
            show_sections(sections, program)
        else:
            _render_rows(rows, client, page_art)
    elif season is not None:
        # Inside a chosen season folder: show only that season's episodes.
        rows = [r for r in rows if block_season(r[3]) == season]
        _render_rows(rows, client, page_art)
    elif len(seasons) > 1:
        # Multi-season series: present only the "Seizoen N" folders. Episodes
        # live inside each season folder and are not listed on the show page.
        for s in seasons:
            season_art = next((content_art(item.get("image"))
                               for item, _target, _kind, block in rows
                               if block_season(block) == s and item.get("image")), {})
            season_art.update(page_art)
            add("Seizoen {}".format(s), url(
                action="layout",
                kind=(program or {}).get("kind", "program"),
                entity_id=(program or {}).get("entity_id", ""),
                seo=(program or {}).get("seo", ""),
                season=s,
            ), True, art=season_art, info={"title": "Seizoen {}".format(s)}, icon_key="series")
    else:
        # Single season (or no season info): list the episodes directly.
        _render_rows(rows, client, page_art)
    xbmcplugin.endOfDirectory(HANDLE)


def search(query="", period=None, genre=None, kind=None):
    query = (query or xbmcgui.Dialog().input("Zoeken in Videoland")).strip()
    if not query:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    if len(query) < 3:
        raise ApiError("Gebruik minimaal 3 tekens om te zoeken")
    set_breadcrumb(["Videoland", "Zoeken", query])
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    data = _search_layout(client, query)
    if not (period or genre or kind):
        _add_other_service_search(query)
        # Without a filter keep the familiar sectioned result page, with the
        # Filter entry on top.
        _add_search_filter_entry(query)
        show_items(data, client=client)
        return
    xbmcplugin.setContent(HANDLE, "videos")
    _add_search_filter_entry(query, period, genre, kind)
    rows = _build_rows(data)
    wanted = {id(item) for item in search_filters.apply([row[0] for row in rows], period, genre)}
    rows = [row for row in rows if id(row[0]) in wanted]
    t = search_filters.texts(xbmc.getLanguage(xbmc.ISO_639_1) or "nl")
    if not rows:
        xbmcgui.Dialog().notification("Videoland", t["empty"], time=3000)
    _render_rows(rows, client, hero_art(data), only_kind=kind)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def _search_layout(client, query):
    location = "https://v2.videoland.com/zoeken?" + urlencode({"query": query})
    return client.layout("frontspace", "search", location, {"query": query}, complete=True)


def _add_search_filter_entry(query, period=None, genre=None, kind=None):
    t = search_filters.texts(xbmc.getLanguage(xbmc.ISO_639_1) or "nl")
    params = {"action": "search_filter", "query": query}
    for key, value in (("period", period), ("genre", genre), ("kind", kind)):
        if value:
            params[key] = value
    add("{}  [{}]".format(t["filter"], search_filters.describe(t, period, genre, kind)),
        url(**params), False, icon_key="zoeken")


def search_filter(query, period=None, genre=None, kind=None):
    """Ask for a type, period or genre and reopen the search results with it."""
    t = search_filters.texts(xbmc.getLanguage(xbmc.ISO_639_1) or "nl")
    client = api()
    ensure_profile(client, ensure_login())
    items = [row[0] for row in _build_rows(_search_layout(client, query))]
    periods, genres = search_filters.options(items)
    choices, actions = [t["kind"]], ["kind"]
    if periods:
        choices.append(t["period"])
        actions.append("period")
    if genres:
        choices.append(t["genre"])
        actions.append("genre")
    if period or genre or kind:
        choices.append(t["clear"])
        actions.append("clear")
    picked = xbmcgui.Dialog().select(t["filter"], choices)
    if picked < 0:
        return
    action = actions[picked]
    if action == "kind":
        kinds = ["series", "movie", "episode"]
        index = xbmcgui.Dialog().select(t["kind"], [t["all"]] + [t[k] for k in kinds])
        if index < 0:
            return
        kind = kinds[index - 1] if index > 0 else None
    elif action == "period":
        index = xbmcgui.Dialog().select(t["period"], [t["all"]] + [t[k] for k in periods])
        if index < 0:
            return
        period = periods[index - 1] if index > 0 else None
    elif action == "genre":
        index = xbmcgui.Dialog().select(t["genre"], [t["all"]] + genres)
        if index < 0:
            return
        genre = genres[index - 1] if index > 0 else None
    else:
        period = genre = kind = None
    params = {"action": "search", "query": query}
    for key, value in (("period", period), ("genre", genre), ("kind", kind)):
        if value:
            params[key] = value
    xbmc.executebuiltin("Container.Update({},replace)".format(url(**params)))


def progress_tracker(client, auth, layout, video_id, location, stream):
    if local_history():
        return None
    config = heartbeat_config(layout, video_id)
    if not config:
        xbmc.log("[Videoland] No cloud progress metadata for selected video", xbmc.LOGWARNING)
        return None
    # Bind writes to the profile that resolved this video, even if settings change.
    writer = DurableWriter(
        ProgressWriter(client, auth, setting("profile_id"), config, location),
        SyncStore(data_dir()), cloud_sync_enabled)
    client.timeout = 8

    def notify(success, position):
        if not cloud_sync_enabled() or not setting_bool("sync_notifications", False):
            return
        message = ADDON.getLocalizedString(31044 if success else 31045)
        if success:
            seconds = int(position)
            message = message.format("{}:{:02d}".format(seconds // 60, seconds % 60))
        xbmcgui.Dialog().notification("Videoland", message, time=2500, sound=False)

    return monitor_class(xbmc)(
        writer, stream, cloud_sync_enabled, notify,
        lambda message, error: xbmc.log("[Videoland] " + message,
                                      xbmc.LOGWARNING if error else xbmc.LOGINFO))


def hd_capable():
    """Videoland only grants its HD key (720p/1080p) to Widevine L1, which in
    Kodi exists only on Android. Linux/LibreELEC, Windows and macOS use the
    software Widevine (L3): there the HD stream can never be decrypted."""
    try:
        return xbmc.getCondVisibility("System.Platform.Android") is True
    except Exception:
        return False


def choose_asset(dash):
    """Pick the DASH asset to play.

    "Highest available" uses the hardware-protected (HD) asset only where it
    can work; elsewhere it falls back to the best software stream instead of
    starting a stream that cannot be decrypted.
    """
    software = [a for a in dash if (a.get("drm") or {}).get("type") == "software"]
    hardware = [a for a in dash if (a.get("drm") or {}).get("type") != "software"]
    want_best = setting_int("preferred_quality", 1) == 0
    if want_best and hd_capable():
        return (hardware or dash)[0]
    if want_best and hardware and setting("hd_fallback_notice_shown") != "true":
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31172), time=8000)
        save("hd_fallback_notice_shown", "true")
    return software[0] if software else dash[0]


def _dash_item(helper, asset, drm_token):
    """Build the inputstream.adaptive ListItem for a Widevine DASH asset."""
    item = xbmcgui.ListItem(path=asset["path"])
    item.setMimeType("application/dash+xml")
    item.setContentLookup(False)
    item.setProperty("inputstream", helper.inputstream_addon)
    item.setProperty("inputstream.adaptive.manifest_type", "mpd")
    item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
    # DRMtoday is strict about this request shape. In particular, its CENC
    # endpoint expects an explicitly empty Content-Type for the raw CDM
    # challenge rather than application/x-www-form-urlencoded.
    license_headers = urlencode({
        "Content-Type": "",
        "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Host": "lic.drmtoday.com",
        "Origin": "https://v2.videoland.com",
        "Referer": "https://v2.videoland.com/",
        "x-dt-auth-token": drm_token,
    })
    item.setProperty(
        "inputstream.adaptive.license_key",
        VideolandApi.LICENSE_URL + "?specConform=true|" + license_headers + "|R{SSM}|R",
    )
    return item


def _video_item(layout, video_id):
    for card, _block in walk_item_content(layout):
        video = card.get("video")
        if isinstance(video, dict) and str(video.get("id")) == str(video_id):
            return card
    return {}


def _next_episode(client, video_id, parent_id, parent_seo):
    """(current_row, next_row) in the series' episode order, or (None, None)."""
    if not parent_id:
        return None, None

    def load_block(block):
        tealium = (block.get("analytics") or {}).get("tealium") or {}
        return not is_related_block({"feature": tealium.get("from"), "block_title": tealium.get("block_title")})

    data = client.layout("program", parent_id, program_location(parent_seo, parent_id),
                         complete=True, block_filter=load_block)
    rows = [row for row in _build_rows(data) if row[2] == "video" and not is_hero_block(row[3])]
    ids = [str(row[1].get("id") or "") for row in rows]
    if str(video_id) not in ids:
        return None, None
    index = ids.index(str(video_id))
    following = rows[index + 1] if index + 1 < len(rows) else None
    return rows[index], following


def _episode_info(row, showtitle):
    item, target, _kind, block = row
    label = _clean_episode_label(_item_label(item, str(target.get("id") or "")))
    return playback_extras.episode_info(
        label, showtitle, block_season(block) or 1, _episode_number(item) or 0,
        plot=str(item.get("description") or ""), art=content_art(item.get("image")),
        episode_id=str(target.get("id") or ""))


def _start_playback_extras(client, layout, asset, video_id, seo, parent_id, parent_seo):
    """Skip-intro question and Up Next, without delaying playback."""
    card = _video_item(layout, video_id)
    raw_duration = (card.get("video") or {}).get("duration") if isinstance(card, dict) else None
    duration = float(raw_duration) if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool) else 0.0
    # Videoland's own intro/credits markers (the app's "Overslaan") live in
    # video.chapters as a typed list: [{tcStart, tcEnd, type}]. Use those; fall
    # back to the generic finder only when the chapter list is missing.
    video = card.get("video") if isinstance(card, dict) else None
    chapters = (video or {}).get("chapters")
    markers = playback_extras.markers_from_typed_chapters(chapters)
    if not markers:
        markers = playback_extras.find_markers([card, asset], duration)
    # Also log the raw chapter types, so an unrecognised recap/intro type shows
    # up and can be mapped.
    try:
        raw_types = [str((c or {}).get("type")) for c in (chapters or []) if isinstance(c, dict)]
    except Exception:
        raw_types = []
    xbmc.log("[Videoland] {}: markers found: {} | chapter types: {}".format(
        video_id, playback_extras.marker_summary(markers), raw_types), xbmc.LOGINFO)

    # Videoland delivers no separate "recap" chapter: the web layout gives only
    # intro + ending_credits, and the mobile layout gives no chapters at all
    # (confirmed from logs). What the Videoland app calls "Terugblik overslaan"
    # is the opening segment the backend simply types as `intro` when it is long
    # enough to be a recap ("wat voorafging"). So a long opening marker (>= 45s)
    # with no explicit recap is relabelled as a recap, matching the app.
    RECAP_MIN_SECONDS = 45
    intro = markers.get("intro") if isinstance(markers, dict) else None
    if (intro and "recap" not in markers
            and (intro[1] - intro[0]) >= RECAP_MIN_SECONDS):
        markers["recap"] = markers.pop("intro")
        xbmc.log("[Videoland] {}: long intro {:.0f}-{:.0f}s shown as recap".format(
            video_id, intro[0], intro[1]), xbmc.LOGINFO)
    if setting_bool("skip_markers", True) and markers:
        def ask(kind, seconds=12):
            # A small corner button (like the Videoland app), not a full-screen
            # yes/no dialog. It stays until the intro/recap is over.
            label = ADDON.getLocalizedString(31234 if kind == "recap" else 31233)
            return corner.ask(label, seconds=seconds)
        playback_extras.start_skip_watcher(markers, ask)
    next_mode = setting("next_episode", "upnext")
    if next_mode not in ("upnext", "ask"):
        return

    # Kodi can start the same playback more than once. Set a per-episode flag
    # here, in the play call itself, so a second start sees it before anything
    # runs and the question/notice isn't doubled. The flag is keyed on the
    # episode id (overwritten by the next episode), so it needs no clearing.
    if next_mode == "ask":
        win = xbmcgui.Window(10000)
        if win.getProperty("videoland.next_armed") == str(video_id):
            return
        win.setProperty("videoland.next_armed", str(video_id))

    def announce():
        try:
            current, following = _next_episode(client, video_id, parent_id, parent_seo)
            if not following:
                xbmc.log("[Videoland] Next episode: none for {}".format(video_id), xbmc.LOGINFO)
                if next_mode == "ask":
                    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31232),
                                                  xbmcgui.NOTIFICATION_INFO, 4000)
                return
            credits = markers.get("credits")
            credits_start = credits[0] if credits and credits[0] else None
            if next_mode == "ask":
                # A small corner card (like the Videoland app): press it to play
                # the next episode, ignore it to stay. No full-screen dialog.
                def _ask():
                    return corner.ask(ADDON.getLocalizedString(31235), seconds=15)

                def _play():
                    xbmc.executebuiltin("RunPlugin({})".format(url(
                        action="play_next", video_id=video_id,
                        parent_id=parent_id, parent_seo=parent_seo, background="1")))

                playback_extras.start_next_prompt(_play, _ask, credits_start=credits_start)
                xbmc.log("[Videoland] Next episode: own prompt armed (credits_start={})".format(
                    credits_start), xbmc.LOGINFO)
                return
            # next_mode == "upnext": hand the next episode to the Up Next add-on.
            if not playback_extras.upnext_available():
                return
            showtitle = _layout_title(client.layout("program", parent_id, program_location(parent_seo, parent_id)))
            target = following[1]
            parent = target.get("parent") or {}
            play_url = url(action="play", video_id=target.get("id", ""), seo=target.get("seo", ""),
                           parent_id=parent.get("id") or parent_id, parent_seo=parent.get("seo") or parent_seo)
            notify_at = duration - credits_start if credits_start and duration else None
            if playback_extras.wait_for_playback(xbmc.Player()):
                playback_extras.send_upnext(ADDON.getAddonInfo("id"), _episode_info(current, showtitle),
                                            _episode_info(following, showtitle), play_url, notify_at)
        except Exception as exc:
            xbmc.log("[Videoland] Next episode skipped: {}".format(exc), xbmc.LOGINFO)

    # Not a daemon thread: the play handler returns right after handing Kodi
    # the stream, and Kodi would kill a daemon thread before it could arm the
    # prompt. start_background uses a non-daemon thread that ends on its own.
    playback_extras.start_background(announce, "VideolandNextEpisode")


def kodi_library_resume():
    """True when Kodi already offers its own resume for this item, so the
    add-on must not ask a second time.

    This is the case when Kodi has a resume point for the item (it shows its
    own "Resume from ...?" prompt and applies the seek) -- whether the item
    comes from the Kodi video library or from one of the add-on's own pages
    that Kodi has a local bookmark for. A library item without a resume point
    also counts, so playback there starts at 0 just like Kodi would.
    """
    try:
        if xbmc.getCondVisibility("ListItem.IsResumable"):
            return True
        dbid = xbmc.getInfoLabel("ListItem.DBID")
        has_dbid = isinstance(dbid, str) and dbid.isdigit() and int(dbid) > 0
        folder = xbmc.getInfoLabel("Container.FolderPath")
        in_library_view = isinstance(folder, str) and folder.startswith("videodb://")
        return bool(has_dbid or in_library_view)
    except Exception:
        return False


def play(video_id, seo="", parent_id="", parent_seo="", from_library=False):
    import inputstreamhelper

    # Run setup before requesting the short-lived playback/DRM credentials.
    helper = inputstreamhelper.Helper("mpd", drm="com.widevine.alpha")
    if not helper.check_inputstream():
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/"
    if parent_id and parent_seo and seo:
        location += "{}-p_{}/{}-c_{}".format(parent_seo, parent_id, seo, video_id.replace("clip_", ""))
    layout = client.layout("video", video_id, location)

    # Check for resume position
    use_local = local_history()
    # Started from Kodi's own library with a Kodi resume point: Kodi has just
    # asked "Resume from ...?" itself, so do not ask a second time.
    # A .strm from the Kodi library (inlib=1) means Kodi owns the resume prompt,
    # so the add-on must not ask again. The infolabel check is a fallback for
    # items Kodi already has a resume point for.
    kodi_resumes = from_library or kodi_library_resume()
    # The add-on no longer shows its own "Verder kijken?" dialog: Kodi already
    # offers its own resume prompt (from the library bookmark, or from the
    # resume point we set below), and a second dialog on top of it was
    # confusing. We just carry the server resume position onto the item so
    # Kodi's own prompt/auto-resume lands in the right place.
    resume_position = 0 if (use_local or kodi_resumes) else get_resume_position(layout, video_id)

    assets = list(video_assets(layout, video_id))
    dash = [a for a in assets if a.get("format") == "dash" or ".mpd" in a.get("path", "")]
    if not dash:
        raise ApiError("Geen DASH-stream gevonden")
    # Some devices (e.g. Pi 5 / Widevine on LibreELEC) require the software-L3
    # rendition and fail to decrypt the hardware (L1) rendition (CDM "kNoKey").
    # Software-L3 is the default; "best available" opts into the highest stream.
    asset = choose_asset(dash)
    drm_token = client.upfront_token(auth["uid"], video_id)
    item = _dash_item(helper, asset, drm_token)

    # Kodi's plugin resolver forces resume from the resolved video info tag.
    # StartOffset alone is not carried through that resolver on Kodi 21.
    # CBookmark::IsSet requires a positive total duration, even for restart.
    tracker = None
    if not use_local:
        if not kodi_resumes:
            duration = get_video_duration(layout, video_id)
            item.getVideoInfoTag().setResumePoint(
                float(resume_position), max(duration, float(resume_position) + 1.0))
            item.setProperty("StartOffset", str(resume_position))
        xbmc.log("[Videoland] {}: selected playback position {} seconds".format(
            video_id, resume_position), xbmc.LOGINFO)
        tracker = progress_tracker(client, auth, layout, video_id, location, asset["path"])
    card = _video_item(layout, video_id)
    title = _layout_title(layout) or (card.get("title") if isinstance(card, dict) else "") or ""
    now_playing = {"video_id": video_id, "seo": seo, "parent_id": parent_id, "parent_seo": parent_seo,
                   "title": title, "thumb": content_art((card or {}).get("image")).get("thumb", "")}
    try:
        xbmcgui.Window(10000).setProperty("videoland.now_playing", json.dumps(now_playing))
        xbmcgui.Window(10000).clearProperty("videoland.stop_after")
    except Exception:
        pass
    try:
        watch_history.record(_history_path(), {"id": video_id, "video_id": video_id, "seo": seo,
                                               "parent_id": parent_id, "parent_seo": parent_seo,
                                               "title": title, "thumb": now_playing.get("thumb", "")})
    except Exception:
        pass
    xbmcplugin.setResolvedUrl(HANDLE, True, item)
    _start_playback_extras(client, layout, asset, video_id, seo, parent_id, parent_seo)
    if tracker:
        tracker.run()
        # Kodi updates the visible item with its local bookmark on stop/end.
        # Rebuild only our active listing, restoring cloud-only browse metadata.
        if (not local_history() and not xbmc.Player().isPlaying()
                and xbmc.getInfoLabel("Container.FolderPath").startswith(BASE_URL)):
            xbmc.executebuiltin("Container.Refresh")


def _live_display_name(channel_id):
    """Friendly channel name from its Bedrock id as a fallback for the title."""
    name = str(channel_id or "").replace("videoland_", "")
    if name.startswith("rtl"):
        return "RTL " + name[3:].upper()
    return " ".join(name.replace("-", " ").split()).title()


def _live_channel_rows(data):
    """Collect the linear TV channels from the EPG-grid layout as flat rows.

    Returns a list of ``(channel_id, seo, channel_name, art)`` tuples. Only the
    real channels are kept; special events (e.g. pay-per-view boxing) are
    excluded so the list stays a plain channel zapper instead of sub-folders.
    """
    channels = {}
    order = []
    for item, _block in walk_item_content(data):
        target = action_target(item)
        if not target or target.get("type") != "live":
            continue
        channel_id = str(target.get("id") or "")
        if not channel_id or channel_id.startswith("videoland_event"):
            continue
        if channel_id not in channels:
            channels[channel_id] = {"seo": target.get("seo") or "", "title": None, "image": None}
            order.append(channel_id)
        row = channels[channel_id]
        # The EPG strip item carries the canonical channel name and logo; the
        # card item only shows the currently airing program as its caption.
        channel = item.get("channel")
        if row["title"] is None and isinstance(channel, dict):
            row["title"] = str(channel.get("title") or "").strip()
            image = (channel.get("image") or {}).get("id")
            if image:
                row["image"] = str(image)
    rows = []
    for channel_id in order:
        row = channels[channel_id]
        title = row["title"] or _live_display_name(channel_id)
        art = {}
        if row["image"]:
            image_url = "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw".format(row["image"])
            art.update(thumb=image_url, icon=image_url)
        rows.append((channel_id, row["seo"], title, art))
    return rows


def _live_guide_rows(data):
    """Collect the current and next EPG program per live channel.

    Returns ``{channel_id: {"now": program, "next": program}}`` where each
    program is a dict with ``title``, ``extra``, ``start_time`` and
    ``end_time`` (display-only time strings).  Channels without a schedule or
    with unparseable timestamps are omitted.
    """
    guides = {}
    for block in data.get("blocks") or []:
        content = block.get("content") or {}
        if content.get("contentTemplateId") != "HorizontalEpg":
            continue
        for wrapper in content.get("items") or []:
            item = wrapper.get("itemContent") or {}
            target = (item.get("action") or {}).get("target") or {}
            waypoint = target.get("value_layout") or {}
            if waypoint.get("type") != "live":
                continue
            channel_id = str(waypoint.get("id") or "")
            if not channel_id or channel_id.startswith("videoland_event"):
                continue
            programs = []
            for entry in item.get("epgBox") or []:
                start = entry.get("start") or {}
                end = entry.get("end") or {}
                try:
                    start_dt = datetime.fromisoformat(start.get("date") or "")
                    end_dt = datetime.fromisoformat(end.get("date") or "")
                except (TypeError, ValueError):
                    continue
                programs.append({
                    "title": str(entry.get("title") or "").strip(),
                    "extra": str(entry.get("extraTitle") or "").strip(),
                    "start_time": str(start.get("title") or ""),
                    "end_time": str(end.get("title") or ""),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                })
            programs.sort(key=lambda p: p["start_dt"])
            # Determine the reference time using the first parseable entry's
            # timezone so comparisons are always zone-aware.
            tz = None
            for p in programs:
                if p["start_dt"].tzinfo is not None:
                    tz = p["start_dt"].tzinfo
                    break
            now = datetime.now(tz) if tz else datetime.now()
            first_open_index = None
            for idx, program in enumerate(programs):
                if program["end_dt"] > program["start_dt"] and program["end_dt"] > now:
                    first_open_index = idx
                    break
            if first_open_index is None:
                continue
            first_open = programs[first_open_index]
            if first_open["start_dt"] <= now:
                current = first_open
                nxt = programs[first_open_index + 1] if first_open_index + 1 < len(programs) else None
            else:
                current = None
                nxt = first_open
            guides[channel_id] = {"now": current, "next": nxt}
    return guides


def live_tv():
    """Show only the live TV channels; each entry starts playback immediately."""
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    set_breadcrumb(["Videoland", "Live TV"])
    xbmcplugin.setContent(HANDLE, "videos")
    data = client.layout("frontspace", "epggrid", "https://v2.videoland.com/tv-programmagids", complete=True)
    channels = _live_channel_rows(data)
    if not channels:
        xbmcgui.Dialog().ok("Videoland", "Geen live tv-zenders gevonden")
    guides = _live_guide_rows(data)
    for channel_id, seo, title, art in channels:
        plot = "Kijk live naar {}.".format(title)
        guide = guides.get(channel_id) or {}
        for prefix, key in (("Nu", "now"), ("Vervolgens", "next")):
            program = guide.get(key)
            if not program or not program.get("title"):
                continue
            headline = program["title"]
            extra = program.get("extra") or ""
            if extra and extra.strip().casefold() != headline.strip().casefold():
                headline += " - " + extra
            plot += "\n{}: {} ({}-{})".format(
                prefix, headline, program["start_time"], program["end_time"])
        add(title, url(action="play_live", channel_id=channel_id, seo=seo),
            False, art, {"title": title, "plot": plot},
            playable=True, suppress_watched=True)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def _live_stream(client, channel_id, seo):
    """Resolve the playable Widevine DASH asset of a live channel."""
    location = "https://v2.videoland.com/"
    if seo:
        location += "{}/live".format(seo)
    layout = client.layout("live", seo or channel_id, location, complete=True)
    assets = list(video_assets(layout, channel_id))
    dash = [a for a in assets if a.get("provider") != "yospace"
            and (a.get("format") == "dashcenc" or ".mpd" in a.get("path", ""))]
    if not dash:
        raise ApiError("Geen live DASH-stream gevonden")
    return choose_asset(dash)


def play_live(channel_id, seo=""):
    """Start instant playback of a live TV channel."""
    import inputstreamhelper

    helper = inputstreamhelper.Helper("mpd", drm="com.widevine.alpha")
    if not helper.check_inputstream():
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    asset = _live_stream(client, channel_id, seo)
    config = (asset.get("drm") or {}).get("config") or {}
    asset_id = config.get("contentId") or "dashcenc_" + channel_id
    drm_token = client.live_upfront_token(auth["uid"], asset_id)
    item = _dash_item(helper, asset, drm_token)
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


# --------------------------------------------------------------------------
# Kodi library
# --------------------------------------------------------------------------

def _http_status(exc):
    cause = getattr(exc, "__cause__", None)
    return getattr(cause, "code", None) or getattr(cause, "status", None)


def _layout_title(data):
    entity = data.get("entity") or {}
    title = entity.get("title") if isinstance(entity, dict) else None
    if isinstance(title, str) and title.strip():
        return title.strip()
    metadata = entity.get("metadata") if isinstance(entity, dict) and isinstance(entity.get("metadata"), dict) else {}
    if isinstance(metadata.get("title"), str) and metadata["title"].strip():
        return metadata["title"].strip()
    seo = data.get("seo") if isinstance(data.get("seo"), dict) else {}
    if isinstance(seo.get("title"), str) and seo["title"].strip():
        return seo["title"].strip()
    return ""


def _hero_details(data):
    """Plot and poster of a title page, read from its Jumbotron."""
    plot, poster = "", ""
    base = "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw"
    for block in data.get("blocks", []):
        content = block.get("content") or {}
        if content.get("contentTemplateId") != "Jumbotron":
            continue
        for item, _section in walk_item_content(content):
            if not plot and isinstance(item.get("description"), str):
                plot = item["description"].strip()
            ratios = (item.get("image") or {}).get("idsByRatio") or {}
            image_id = ratios.get("2:3") or ratios.get("3:4")
            if not poster and image_id:
                poster = base.format(image_id)
    return plot, poster


class LibrarySource:
    """Reads series and films from Videoland for the library module."""

    def __init__(self, client):
        self.client = client

    def _program(self, program_id, seo):
        def load_block(block):
            tealium = (block.get("analytics") or {}).get("tealium") or {}
            return not is_related_block({"feature": tealium.get("from"), "block_title": tealium.get("block_title")})
        try:
            return self.client.layout("program", program_id, program_location(seo, program_id),
                                      complete=True, block_filter=load_block)
        except AuthError:
            raise
        except ApiError as exc:
            if _http_status(exc) in (404, 410):
                raise library_mod.TitleGone(str(exc))
            raise

    def series(self, series_id, seo):
        data = self._program(series_id, seo)
        episodes = []
        for item, target, kind, block in _build_rows(data):
            if kind != "video" or is_hero_block(block):
                continue
            parent = target.get("parent") or {}
            episode_id = str(target.get("id") or "")
            episodes.append({
                "id": episode_id,
                "seo": target.get("seo", ""),
                "parent_id": str(parent.get("id") or series_id),
                "parent_seo": parent.get("seo") or seo,
                "title": _clean_episode_label(_item_label(item, episode_id)),
                "plot": str(item.get("description") or "").strip(),
                "season": block_season(block),
                "episode": _episode_number(item),
                "thumb": content_art(item.get("image")).get("thumb", ""),
            })
        plot, poster = _hero_details(data)
        return {"title": _layout_title(data), "plot": plot, "poster": poster,
                "fanart": hero_art(data).get("fanart", ""), "episodes": episodes}

    def movie(self, movie_id, seo):
        data = self._program(movie_id, seo)
        target = _play_target(self.client, {}, {"id": movie_id, "seo": seo}, "program", program_data=data)
        if not target:
            return None
        parent = target.get("parent") or {}
        plot, poster = _hero_details(data)
        return {
            "title": _layout_title(data), "plot": plot, "poster": poster,
            "fanart": hero_art(data).get("fanart", ""),
            "play": {"video_id": str(target.get("id") or ""), "seo": target.get("seo", ""),
                     "parent_id": str(parent.get("id") or movie_id), "parent_seo": parent.get("seo") or seo},
        }


_LIBRARY_STORE = None


def _library_store():
    global _LIBRARY_STORE
    if _LIBRARY_STORE is None:
        _LIBRARY_STORE = library_mod.LibraryStore(library_mod.store_path())
    return _LIBRARY_STORE


_LOGOS = None
_LOGO_CACHE = None


def _browse_logo_cache():
    """Logo cache for titles outside the library (needs a TMDb key)."""
    global _LOGO_CACHE
    if _LOGO_CACHE is None:
        if setting_bool("browse_logos", True) and setting_bool("library_enrich", True) and setting("tmdb_api_key").strip():
            _LOGO_CACHE = logo_cache_mod.LogoCache(data_dir())
        else:
            _LOGO_CACHE = False
    return _LOGO_CACHE or None


def _library_logos():
    """Clearlogos of library titles, so browse lists show them too."""
    global _LOGOS
    if _LOGOS is None:
        try:
            _LOGOS = library_art.logo_index(_library_store())
        except Exception:
            _LOGOS = {}
    return _LOGOS


def _library_has(kind, item_id):
    try:
        return _library_store().has(kind, item_id)
    except Exception:
        return False


def _library_enricher():
    """Fills empty library fields from TMDb/TVmaze, or None when turned off."""
    if not setting_bool("library_enrich", True):
        return None
    language = "nl-NL"
    try:
        if not str(xbmc.getLanguage(xbmc.ISO_639_1) or "nl").lower().startswith("nl"):
            language = "en-US"
    except Exception:
        pass
    return metadata_mod.Enricher(os.path.join(data_dir(), "metadata_cache.json"),
                                 tmdb_key=setting("tmdb_api_key"), language=language,
                                 user_agent="plugin.video.videoland.nl")


def _library(client=None):
    return library_mod.Library(
        LibrarySource(client or api()), setting, store=_library_store(), enricher=_library_enricher(),
        downloader=lambda image_url: library_art.http_download(image_url, "plugin.video.videoland.nl"))


def repair_library_art(background=True):
    """Give titles Kodi already scanned their missing poster and background."""
    try:
        lib = library_mod.Library(None, setting, store=_library_store())
        fixed = library_art.repair_kodi_art(lib, marker="plugin.video.videoland.nl/library")
    except Exception as exc:
        xbmc.log("[Videoland] Library artwork repair failed: {}".format(exc), xbmc.LOGWARNING)
        fixed = 0
    if not background:
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31144).format(fixed), time=3000)
    return fixed


def check_tmdb_key():
    key = setting("tmdb_api_key").strip()
    enricher = metadata_mod.Enricher("", tmdb_key=key, user_agent="plugin.video.videoland.nl")
    ok = bool(key) and enricher._tmdb("/configuration") is not None
    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31133 if ok else 31134), time=4000)


def _library_special_paths():
    """The two library folders in Kodi's preferred special:// form."""
    base = "special://profile/addon_data/plugin.video.videoland.nl/library"
    return [(base + "/TV Shows", "tvshows"), (base + "/Movies", "movies")]


def _ensure_sources_xml():
    """Write the library folders into sources.xml (idempotent, no UI).
    Returns how many entries were added."""
    import xml.etree.ElementTree as ET
    lib = library_mod.Library(None, setting, store=_library_store())
    paths = [p for p in (lib.tv_root(), lib.movies_root()) if p]
    names = ["Videoland Series", "Videoland Films"]
    src_path = xbmcvfs.translatePath("special://userdata/sources.xml")
    added = 0
    try:
        if os.path.exists(src_path):
            tree = ET.parse(src_path)
            root = tree.getroot()
        else:
            root = ET.Element("sources")
            tree = ET.ElementTree(root)
        video = root.find("video")
        if video is None:
            video = ET.SubElement(root, "video")
            ET.SubElement(video, "default", {"pathversion": "1"})
        existing = set()
        for source in video.findall("source"):
            node = source.find("path")
            if node is not None and node.text:
                existing.add(node.text.rstrip("/"))
        for name, path in zip(names, paths):
            if path.rstrip("/") in existing:
                continue
            source = ET.SubElement(video, "source")
            ET.SubElement(source, "name").text = name
            ET.SubElement(source, "path", {"pathversion": "1"}).text = path.rstrip("/") + "/"
            ET.SubElement(source, "allowsharing").text = "true"
            added += 1
        if added:
            tree.write(src_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        xbmc.log("[Videoland] ensure sources failed: {}".format(exc), xbmc.LOGERROR)
    return added


def _fix_library_sources_db():
    """Set content type + local scraper on the library paths in Kodi's DB, so
    series/films land under "Series"/"Films" without the manual wizard."""
    import glob
    import sqlite3
    lib = library_mod.Library(None, setting, store=_library_store())
    pairs = [
        (lib.tv_root(), _library_special_paths()[0][0], "tvshows"),
        (lib.movies_root(), _library_special_paths()[1][0], "movies"),
    ]
    db_dir = xbmcvfs.translatePath("special://userdata/Database/")
    dbs = sorted(glob.glob(os.path.join(db_dir, "MyVideos*.db")))
    if not dbs:
        return
    db_path = dbs[-1]
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        # NOTE: never DELETE path rows here. Removing a path row cascades to the
        # episodes/movies beneath it and their resume bookmarks, which wiped the
        # user's "continue watching". Only set the content type/scraper on the
        # existing rows and insert a row when it is missing.
        for abs_path, special_path, content in pairs:
            for base in (abs_path, special_path):
                if not base:
                    continue
                norm = base.rstrip("/") + "/"
                cur.execute(
                    "UPDATE path SET strContent=?, strScraper=?, scanRecursive=1, "
                    "useFolderNames=0, noUpdate=0, exclude=0, strSettings=? "
                    "WHERE strPath=? OR strPath=?",
                    (content, "metadata.local", "", norm, base))
            cur.execute("SELECT 1 FROM path WHERE strPath=? OR strPath=?",
                        (special_path.rstrip("/") + "/", abs_path.rstrip("/") + "/"))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO path (strPath, strContent, strScraper, scanRecursive, "
                    "useFolderNames, noUpdate, exclude, strSettings, dateAdded) "
                    "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                    (special_path.rstrip("/") + "/", content, "metadata.local", 1, 0, 0, 0, ""))
        conn.commit()
        conn.close()
        xbmc.log("[Videoland] library sources fixed in DB", xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log("[Videoland] fix library sources DB failed: {}".format(exc), xbmc.LOGERROR)


def _register_sources_quiet():
    """Best-effort source registration without any dialog, for the automatic
    path (runs right before a library scan)."""
    try:
        _ensure_sources_xml()
    except Exception:
        pass
    try:
        _fix_library_sources_db()
    except Exception:
        pass


def register_library_sources():
    """Manual action: add the library folders as Kodi video sources."""
    _fix_library_sources_db()
    added = _ensure_sources_xml()
    library_mod.run_library_jobs(scan=True)
    message = "Bibliotheekbronnen toegevoegd ({})".format(added) if added else "Bronnen bestaan al"
    xbmcgui.Dialog().notification("Videoland", message, xbmcgui.NOTIFICATION_INFO)


def _after_library_change(scan=True, clean=False):
    scan = scan and setting_bool("library_scan_after", True)
    clean = clean and setting_bool("library_clean_after", True)
    if scan or clean:
        if scan:
            _register_sources_quiet()
        library_mod.run_library_jobs(scan=scan, clean=clean)


def library_add(kind, item_id, seo="", title="", poster="", fanart=""):
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    lib = _library(client)
    progress = xbmcgui.DialogProgressBG()
    progress.create("Videoland", ADDON.getLocalizedString(31112).format(title))
    try:
        if kind == "series":
            result = lib.add_series(item_id, seo, title, poster, fanart)
        else:
            result = lib.add_movie(item_id, seo, title, poster, fanart)
    finally:
        progress.close()
    if not result.get("ok"):
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31113), xbmcgui.NOTIFICATION_WARNING)
        return
    lib.store.save()
    if kind == "series":
        message = ADDON.getLocalizedString(31114).format(result.get("title") or title, result.get("total", 0))
    else:
        message = ADDON.getLocalizedString(31115).format(result.get("title") or title)
    xbmcgui.Dialog().notification("Videoland", message, time=4000)
    _after_library_change(scan=True)


def library_remove(kind, item_id, title=""):
    lib = library_mod.Library(None, setting, store=_library_store())
    if lib.remove(kind, item_id):
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31116).format(title), time=3000)
        _after_library_change(scan=False, clean=True)
        xbmc.executebuiltin("Container.Refresh")


def library_toggle(kind, item_id, seo="", title="", poster="", fanart=""):
    kind = "series" if kind == "series" else "movie"
    if _library_has(kind, item_id):
        library_remove(kind, item_id, title)
    else:
        library_add(kind, item_id, seo, title, poster, fanart)
        xbmc.executebuiltin("Container.Refresh")


def library_update(background=False):
    if not background:
        return _library_update(False)
    # The background run must never show dialogs or ask for a login/profile.
    if xbmc.Player().isPlaying() or not setting("profile_id"):
        return
    try:
        _library_update(True)
    except Exception as exc:
        xbmc.log("[Videoland] Background library update skipped ({}: {})".format(
            type(exc).__name__, exc), xbmc.LOGWARNING)


def _library_update(background):
    if _library_store().is_empty() and not setting_bool("library_watchlist_sync", False):
        if not background:
            xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31117), time=3000)
        return
    client = api()
    if background:
        auth = auth_data()
        if not all(auth.get(key) for key in ("uid", "signature", "timestamp")):
            return
    else:
        auth = ensure_login()
    ensure_profile(client, auth)
    lib = _library(client)
    if setting_bool("library_watchlist_sync", False):
        try:
            sync_watchlist_to_library(client, lib)
        except AuthError:
            raise
        except Exception as exc:
            xbmc.log("[Videoland] Watchlist sync skipped: {}".format(exc), xbmc.LOGWARNING)
    progress = None
    if not background:
        progress = xbmcgui.DialogProgressBG()
        progress.create("Videoland", ADDON.getLocalizedString(31118))

    def report(index, total, kind, item_id):
        if progress is not None and total:
            entry = lib.store.get(kind, item_id) or {}
            progress.update(int(index * 100 / total), "Videoland", entry.get("title") or item_id)
        return True

    try:
        totals = lib.update_all(progress=report, stop_on=(AuthError,))
    finally:
        if progress is not None:
            progress.close()
    changed = bool(totals["added"] or totals["removed"])
    if changed or not background:
        # A manual update always scans, so titles a busy Kodi skipped get in too.
        _register_sources_quiet()
        library_mod.run_library_jobs(scan=True, clean=bool(totals["removed"]) and setting_bool("library_clean_after", True))
    repair_library_art()
    if not background or (changed and setting_bool("sync_notifications", False)):
        xbmcgui.Dialog().notification(
            "Videoland", ADDON.getLocalizedString(31119).format(totals["added"], totals["removed"]), time=4000)


def watchlist_titles(client):
    """The titles in My watchlist as [(kind, id, seo, title, poster, fanart)].

    ``kind`` is "series" or "movie"; a bookmarked episode counts as its series.
    """
    client.cache_dir = None
    client.cache_ttl = 0
    data = client.layout("frontspace", "bookmarks", "https://v2.videoland.com/", complete=True)
    titles, seen = [], set()
    for item, target, target_kind, _block in _build_rows(data):
        image = item.get("image") or {}
        poster = ratio_image(image, ("2:3", "3:4")) or content_art(image).get("thumb", "")
        fanart = ratio_image(image, ("16:9",))
        label = _item_label(item, str(target.get("id") or ""))
        if target_kind == "video":
            parent = target.get("parent") or {}
            if parent.get("type") != "program" or not parent.get("id"):
                continue
            entry = ("series", str(parent["id"]), parent.get("seo", ""), label, poster, fanart)
        elif target_kind in ("program", "details"):
            try:
                play_target = _play_target(client, item, target, target_kind)
            except AuthError:
                raise
            except Exception:
                play_target = None
            kind = "movie" if play_target else "series"
            entry = (kind, str(target.get("id") or ""), target.get("seo", ""), label, poster, fanart)
        else:
            continue
        if entry[1] and (entry[0], entry[1]) not in seen:
            seen.add((entry[0], entry[1]))
            titles.append(entry)
    return titles


def _watchlist_of_library_profile(client):
    """Watchlist of the profile chosen for the library (default: the active one)."""
    profile_id = setting("library_profile_id")
    active = setting("profile_id")
    if not profile_id or profile_id == active:
        return watchlist_titles(client)
    auth = auth_data()
    client.jwt(auth, profile_id)
    try:
        return watchlist_titles(client)
    finally:
        client.jwt(auth, active)


def choose_library_profile():
    """Settings: which profile's watchlist the library follows."""
    client = api()
    auth = ensure_login()
    client.jwt(auth)
    profiles = client.profiles(auth["uid"]) or []
    labels = [ADDON.getLocalizedString(31165)] + [
        p.get("username") or ADDON.getLocalizedString(31053).format(i + 1) for i, p in enumerate(profiles)]
    index = xbmcgui.Dialog().select(ADDON.getLocalizedString(31164), labels)
    if index < 0:
        return
    if index == 0:
        save("library_profile_id", "")
        save("library_profile_name", ADDON.getLocalizedString(31165))
    else:
        save("library_profile_id", profiles[index - 1].get("uid") or "")
        save("library_profile_name", labels[index])
    ensure_profile(client, auth)
    xbmcgui.Dialog().notification("Videoland", setting("library_profile_name"), time=3000)


def sync_watchlist_to_library(client, lib, progress=None):
    """Add every watchlist title that is not in the library yet; optionally
    remove titles that were added from the watchlist and left it.
    Returns (added, removed, failed)."""
    titles = _watchlist_of_library_profile(client)
    added = failed = removed = 0
    wanted = set()
    for index, (kind, item_id, seo, title, poster, fanart) in enumerate(titles):
        wanted.add((kind, item_id))
        if lib.is_in_library(kind, item_id):
            continue
        if progress is not None:
            progress(index, len(titles), title)
        try:
            if kind == "series":
                result = lib.add_series(item_id, seo, title, poster, fanart)
            else:
                result = lib.add_movie(item_id, seo, title, poster, fanart)
        except AuthError:
            raise
        except Exception as exc:
            xbmc.log("[Videoland] Watchlist title {} not added: {}".format(item_id, exc), xbmc.LOGWARNING)
            result = {}
        if result.get("ok"):
            entry = lib.store.get(kind, item_id)
            if entry is not None:
                entry["source"] = "watchlist"
            added += 1
        else:
            failed += 1
    if setting_bool("library_watchlist_remove", False) and titles:
        for kind in ("series", "movie"):
            for item_id, entry in list(lib.items(kind)):
                if entry.get("source") == "watchlist" and (kind, item_id) not in wanted:
                    if lib.remove(kind, item_id, save=False):
                        removed += 1
    lib.store.save()
    return added, removed, failed


def library_from_watchlist(background=False):
    """Menu/settings action: put the whole watchlist in the Kodi library."""
    client = api()
    if background:
        auth = auth_data()
        if not all(auth.get(key) for key in ("uid", "signature", "timestamp")) or not setting("profile_id"):
            return
    else:
        auth = ensure_login()
    ensure_profile(client, auth)
    lib = _library(client)
    dialog = None
    if not background:
        dialog = xbmcgui.DialogProgressBG()
        dialog.create("Videoland", ADDON.getLocalizedString(31150))

    def report(index, total, title):
        if dialog is not None and total:
            dialog.update(int(index * 100 / total), "Videoland", title)

    try:
        added, removed, failed = sync_watchlist_to_library(client, lib, report)
    finally:
        if dialog is not None:
            dialog.close()
    if added or removed:
        _register_sources_quiet()
        library_mod.run_library_jobs(scan=True, clean=bool(removed) and setting_bool("library_clean_after", True))
    if not background or ((added or removed) and setting_bool("sync_notifications", False)):
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31151).format(added, removed, failed), time=5000)
    if not background:
        xbmc.executebuiltin("Container.Refresh")


def choose_tmdb(kind, item_id):
    """Library menu: pick the right TMDb series/film for a title by hand."""
    kind = "series" if kind == "series" else "movie"
    store = _library_store()
    entry = store.get(kind, item_id)
    enricher = _library_enricher()
    if entry is None:
        return
    if enricher is None or not enricher.tmdb_key:
        xbmcgui.Dialog().ok("Videoland", ADDON.getLocalizedString(31146))
        return
    query = entry.get("title") or ""
    while True:
        found = enricher.search_candidates(kind, query)
        labels = [ADDON.getLocalizedString(31162)] + [
            "{} ({})".format(name, year) if year else name for _id, name, year in found]
        picked = xbmcgui.Dialog().select(ADDON.getLocalizedString(31161), labels)
        if picked < 0:
            return
        if picked == 0:
            query = xbmcgui.Dialog().input(ADDON.getLocalizedString(31162), query)
            if not query:
                return
            continue
        tmdb_id = found[picked - 1][0]
        break
    entry["ids"] = {"tmdb": str(tmdb_id)}  # other ids are looked up again from TMDb
    store.section(kind)[str(item_id)] = entry
    client = api()
    ensure_profile(client, ensure_login())
    lib = _library(client)
    if kind == "series":
        lib.add_series(item_id, entry.get("seo", ""), entry.get("title", ""))
    else:
        lib.add_movie(item_id, entry.get("seo", ""), entry.get("title", ""))
    lib.store.save()
    repair_library_art()
    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31163), time=4000)
    xbmc.executebuiltin("Container.Refresh")


def browse_library():
    set_breadcrumb(["Videoland", ADDON.getLocalizedString(31120)])
    xbmcplugin.setContent(HANDLE, "videos")
    add(ADDON.getLocalizedString(31121), url(action="library_update"), False, icon_key="recent")
    add(ADDON.getLocalizedString(31152), url(action="library_from_watchlist"), False, icon_key="kijklijst")
    lib = library_mod.Library(None, setting, store=_library_store())
    for kind, label_id in (("series", 31122), ("movie", 31123)):
        for item_id, entry in lib.items(kind):
            title = entry.get("title") or item_id
            remove = [(ADDON.getLocalizedString(31111), "RunPlugin({})".format(url(
                action="library_remove", kind=kind, id=item_id, title=title))),
                      (ADDON.getLocalizedString(31161), "RunPlugin({})".format(url(
                action="choose_tmdb", kind=kind, id=item_id)))]
            art = {"thumb": entry["thumb"], "poster": entry["thumb"]} if entry.get("thumb") else {}
            if entry.get("clearlogo"):
                art["clearlogo"] = entry["clearlogo"]
            art = art or None
            label = "{} [COLOR grey]({})[/COLOR]".format(title, ADDON.getLocalizedString(label_id))
            seo = entry.get("seo", "")
            if kind == "series":
                remove = [(ADDON.getLocalizedString(31192), "RunPlugin({})".format(url(
                    action="shuffle", series_id=item_id, seo=seo))),
                          (ADDON.getLocalizedString(31206), "RunPlugin({})".format(url(
                    action="mark_series_watched", series_id=item_id, seo=seo)))] + remove
                add(label, url(action="layout", kind="program", entity_id=item_id, seo=seo), True,
                    art, {"title": title}, context_menu=remove)
            else:
                add(label, url(action="library_play", id=item_id, seo=seo), False,
                    art, {"title": title}, playable=True, context_menu=remove)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def library_play(movie_id, seo=""):
    """Play a library film from the Library menu (the clip id may change)."""
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    data = LibrarySource(client).movie(movie_id, seo)
    if not data:
        raise ApiError(ADDON.getLocalizedString(31113))
    play_target = data["play"]
    play(play_target["video_id"], play_target.get("seo", ""), play_target.get("parent_id", ""),
         play_target.get("parent_seo", ""))


OTHER_SERVICE_ID = "plugin.video.nlziet"


def _add_other_service_search(query):
    """Top line of the search results: the same search in NLZiet."""
    try:
        if not xbmc.getCondVisibility("System.HasAddon({})".format(OTHER_SERVICE_ID)):
            return
    except Exception:
        return
    target = "plugin://{}/?{}".format(OTHER_SERVICE_ID, urlencode({"mode": "search", "q": query}))
    item = xbmcgui.ListItem(label="[B]{}[/B]: {}".format(ADDON.getLocalizedString(31184), query))
    icon = "special://home/addons/{}/icon.png".format(OTHER_SERVICE_ID)
    item.setArt({"icon": icon, "thumb": icon})
    xbmcplugin.addDirectoryItem(HANDLE, target, item, isFolder=True)


def widgets_menu():
    """Ready-made lists for the skin's home screen widgets."""
    xbmcplugin.setContent(HANDLE, "files")
    help_text = ADDON.getLocalizedString(31183)
    entries = []
    if not local_history():
        entries.append((ADDON.getLocalizedString(31079), url(action="continue_watching"), "continue"))
    entries.append((ADDON.getLocalizedString(31186), url(action="layout", kind="frontspace", entity_id="bookmarks"), "kijklijst"))
    entries.append((ADDON.getLocalizedString(31120), url(action="library"), "bibliotheek"))
    entries.append((ADDON.getLocalizedString(31216), url(action="both_continue"), "continue"))
    entries.append((ADDON.getLocalizedString(31212), url(action="recommended"), "recommended"))
    entries.append((ADDON.getLocalizedString(31194), url(action="history"), "continue"))
    for label, route, icon in entries:
        add(label, route, True, icon_key=icon, info={"plot": help_text})
    xbmcplugin.endOfDirectory(HANDLE)


def mark_watched_on_service(video_id, seo="", parent_id="", parent_seo="", watched="1"):
    """Send a watched/unwatched change from the Kodi library back to Videoland."""
    if setting("history_source") == "local" or not setting_bool("watched_to_service", True):
        return
    if not cloud_sync_enabled() or not video_id:
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/"
    if parent_id and parent_seo and seo:
        location += "{}-p_{}/{}-c_{}".format(parent_seo, parent_id, seo, video_id.replace("clip_", ""))
    layout = client.layout("video", video_id, location)
    config = heartbeat_config(layout, video_id)
    if not config:
        xbmc.log("[Videoland] No progress metadata to mark watched for {}".format(video_id), xbmc.LOGWARNING)
        return
    writer = ProgressWriter(client, auth, setting("profile_id"), config, location)
    client.timeout = 8
    want_watched = str(watched) not in ("0", "false", "")
    if want_watched:
        # tc at the clip duration, reported as the end of the session.
        writer.save(writer.duration, "end")
    else:
        # Back to the start so Videoland no longer counts it as watched.
        writer.save(0, "seek")
    xbmc.log("[Videoland] Watched status {} for {} sent".format(
        "on" if want_watched else "off", video_id), xbmc.LOGINFO)



def _history_path():
    return os.path.join(data_dir(), "watch_history.json")


def play_next(video_id, parent_id="", parent_seo="", background=False):
    """Start the next episode in a series (used by binge mode)."""
    if not video_id or not parent_id:
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    current, following = _next_episode(client, video_id, parent_id, parent_seo)
    if not following:
        xbmc.log("[Videoland] play_next: no next episode for {}".format(video_id), xbmc.LOGINFO)
        if not background:
            xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31232),
                                          xbmcgui.NOTIFICATION_INFO, 4000)
        return
    target = following[1]
    next_id = str(target.get("id") or "")
    # Never replay the same episode: if the "next" resolves to what is playing,
    # there is nothing to advance to.
    if not next_id or next_id == str(video_id):
        xbmc.log("[Videoland] play_next: next equals current ({}), skipping".format(video_id),
                 xbmc.LOGINFO)
        return
    parent = target.get("parent") or {}
    query = {"action": "play", "video_id": next_id, "seo": target.get("seo", ""),
             "parent_id": parent.get("id") or parent_id, "parent_seo": parent.get("seo") or parent_seo}
    xbmc.log("[Videoland] play_next: {} -> {}".format(video_id, next_id), xbmc.LOGINFO)
    xbmc.executebuiltin("PlayMedia({})".format(url(**query)))


def shuffle_series(series_id, seo=""):
    """Play a random episode of a library/browse series."""
    if not series_id:
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    data = LibrarySource(client).series(series_id, seo)
    episodes = (data or {}).get("episodes") or []
    choice = watch_history.pick_random(episodes)
    if not choice:
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31193), xbmcgui.NOTIFICATION_INFO)
        return
    query = {"action": "play", "video_id": choice["id"], "seo": choice.get("seo", ""),
             "parent_id": choice.get("parent_id") or series_id, "parent_seo": choice.get("parent_seo") or seo}
    xbmc.executebuiltin("PlayMedia({})".format(url(**query)))


def browse_history():
    xbmcplugin.setContent(HANDLE, "videos")
    items = watch_history.entries(_history_path())
    if not items:
        add(ADDON.getLocalizedString(31195), url(action="history"), False, icon_key="continue")
    else:
        add(ADDON.getLocalizedString(31196), url(action="clear_history"), False, icon_key="cache")
    for row in items:
        label = row.get("title") or row.get("video_id") or row.get("id") or ""
        art = {"thumb": row.get("thumb")} if row.get("thumb") else None
        query = {"action": "play", "video_id": row.get("video_id") or row.get("id") or "",
                 "seo": row.get("seo", ""), "parent_id": row.get("parent_id", ""),
                 "parent_seo": row.get("parent_seo", "")}
        add(label, url(**query), False, art, {"title": label}, playable=True)
    xbmcplugin.endOfDirectory(HANDLE)


def clear_history():
    watch_history.clear(_history_path())
    xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31197), xbmcgui.NOTIFICATION_INFO, 3000)
    xbmc.executebuiltin("Container.Refresh")



def mark_series_watched(series_id, seo="", background=False):
    """Send a watched status to Videoland for each episode of a series.

    Each episode needs its own playback metadata, so this is capped to keep it
    from making hundreds of calls; the user is told when a series is larger.
    """
    if setting("history_source") == "local" or not setting_bool("watched_to_service", True):
        return
    if not cloud_sync_enabled() or not series_id:
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    data = LibrarySource(client).series(series_id, seo)
    episodes = (data or {}).get("episodes") or []
    cap = 60
    capped = len(episodes) > cap
    episodes = episodes[:cap]
    if not episodes:
        return
    progress = None
    if not background:
        progress = xbmcgui.DialogProgressBG()
        progress.create("Videoland", ADDON.getLocalizedString(31208))
    done = 0
    for index, episode in enumerate(episodes):
        try:
            mark_watched_on_service(episode.get("id", ""), episode.get("seo", ""),
                                    episode.get("parent_id", "") or series_id,
                                    episode.get("parent_seo", "") or seo, "1")
            done += 1
        except Exception:
            pass
        if progress:
            progress.update(int((index + 1) * 100 / len(episodes)))
    if progress:
        progress.close()
    if not background:
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31207).format(done),
                                     xbmcgui.NOTIFICATION_INFO, 4000)


def _notify_state_path():
    return os.path.join(data_dir(), "new_episode_state.json")


def notify_new(background=True):
    """Kodi notification for watchlist series that gained an episode."""
    if not setting_bool("notify_new_episodes", True) or not auth_data():
        return
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    try:
        series = [(sid, seo, title) for kind, sid, seo, title, _p, _f in watchlist_titles(client)
                  if kind == "series"][:15]
    except Exception:
        return
    path = _notify_state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            previous = json.load(handle) or {}
    except (OSError, ValueError):
        previous = {}
    current, new_titles = {}, []
    for sid, seo, title in series:
        try:
            episodes = (LibrarySource(client).series(sid, seo) or {}).get("episodes") or []
        except Exception:
            continue
        count = len(episodes)
        current[str(sid)] = count
        if str(sid) in previous and count > previous[str(sid)]:
            new_titles.append(title)
    for title in new_titles[:3]:
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31209).format(title),
                                      xbmcgui.NOTIFICATION_INFO, 7000)
    # Place the new episodes in the Kodi library right away (for library series).
    if new_titles and setting_bool("auto_add_episodes", True) and not _library_store().is_empty():
        xbmc.executebuiltin("RunPlugin({})".format(url(action="library_update", background="1")))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(current, handle)
    except OSError:
        pass


def _library_rpc(method, params):
    """Run one JSON-RPC call and return its ``result`` (or ``{}``)."""
    answer = json.loads(xbmc.executeJSONRPC(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})))
    return answer.get("result") or {}


def _service_resume_positions(client):
    """``{str(video_id): (position_seconds, duration_seconds)}`` from Videoland's
    "Verder kijken" rail, for cross-device resume."""
    def is_continue(block):
        meta = (block.get("analytics") or {}).get("tealium") or {}
        return (meta.get("from") == "feature.recommended_videos_by_user"
                or str(meta.get("block_title", "")).casefold() == "verder kijken")
    client.cache_dir = None
    client.cache_ttl = 0
    layout = client.layout("alias", "home", complete=True, block_filter=is_continue)
    positions = {}
    for item, _block in walk_item_content(layout):
        video = item.get("video")
        if not isinstance(video, dict):
            continue
        video_id = video.get("id")
        progress = video.get("progress") if isinstance(video.get("progress"), dict) else {}
        position = progress.get("tcResume")
        duration = video.get("duration")
        if not video_id or not isinstance(position, (int, float)) or isinstance(position, bool):
            continue
        if position <= 0:
            continue
        total = int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0 else 0
        positions[str(video_id)] = (int(position), total)
    return positions


def sync_resume(background=True):
    """Copy Videoland's own watch positions into the Kodi library.

    So an episode or film you started on your phone or in the Videoland app also
    shows up in the skin's "Afleveringen die je kijkt" row here, which reads the
    Kodi library.
    """
    if (not setting_bool("sync_resume_from_service", True) or local_history()
            or not auth_data()):
        return
    addon_id = "plugin.video.videoland.nl"
    try:
        client = api()
        auth = ensure_login()
        ensure_profile(client, auth)
        positions = _service_resume_positions(client)
    except Exception as exc:
        xbmc.log("[Videoland] Resume sync could not reach the service ({})".format(
            type(exc).__name__), xbmc.LOGWARNING)
        return
    if not positions:
        return

    def _cid_for(item):
        file_path = item.get("file") or ""
        cid = library_resume.plugin_content_id(file_path, addon_id, "video_id")
        if cid:
            return cid
        if library_resume.is_strm(file_path):
            try:
                handle = xbmcvfs.File(file_path)
                try:
                    text = handle.read()
                finally:
                    handle.close()
            except Exception:
                return None
            return library_resume.plugin_content_id(text, addon_id, "video_id")
        return None

    # Stored with each changed item so freshly-progressed episodes sort to the
    # front of the skin's "Afleveringen die je kijkt" row (ordered by lastplayed).
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    calls = []
    try:
        episodes = _library_rpc("VideoLibrary.GetEpisodes",
                                {"properties": ["file", "runtime", "resume"]}).get("episodes", [])
        calls += library_resume.build_calls(
            episodes, positions, "episodeid", "VideoLibrary.SetEpisodeDetails", _cid_for, now_text)
        movies = _library_rpc("VideoLibrary.GetMovies",
                              {"properties": ["file", "runtime", "resume"]}).get("movies", [])
        calls += library_resume.build_calls(
            movies, positions, "movieid", "VideoLibrary.SetMovieDetails", _cid_for, now_text)
    except Exception as exc:
        xbmc.log("[Videoland] Resume sync could not read the library ({})".format(
            type(exc).__name__), xbmc.LOGWARNING)
        return
    done = 0
    for method, params in calls:
        try:
            _library_rpc(method, params)
            done += 1
        except Exception:
            pass
    # No Container.Refresh: SetEpisodeDetails/SetMovieDetails already fire
    # VideoLibrary.OnUpdate, which reloads the library rows on Home on its own.
    # A manual refresh would disturb whatever list the user is browsing.
    xbmc.log("[Videoland] Resume sync updated {} library item(s)".format(done), xbmc.LOGINFO)


def recommended():
    """A row of Videoland's own recommendations from the home page."""
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    def keep(block):
        meta = (block.get("analytics") or {}).get("tealium") or {}
        return is_recommendation_block({"feature": meta.get("from"), "block_title": meta.get("block_title")})
    xbmcplugin.setContent(HANDLE, "videos")
    try:
        data = client.layout("alias", "home", complete=True, block_filter=keep)
        data = dict(data, blocks=[b for b in data.get("blocks", []) if keep(b)])
        _render_rows(_build_rows(data), client, hero_art(data))
    except Exception as exc:
        xbmc.log("[Videoland] recommended failed ({})".format(type(exc).__name__), xbmc.LOGWARNING)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)



def both_continue():
    """Videoland Continue watching, with a jump to NLZiet's at the top."""
    xbmcplugin.setContent(HANDLE, "videos")
    if xbmc.getCondVisibility("System.HasAddon(plugin.video.nlziet)"):
        target = "plugin://plugin.video.nlziet/?mode=widget&list=continue"
        li = xbmcgui.ListItem(label="[B]{}[/B]".format(ADDON.getLocalizedString(31217)))
        icon = "special://home/addons/plugin.video.nlziet/icon.png"
        li.setArt({"icon": icon, "thumb": icon})
        xbmcplugin.addDirectoryItem(HANDLE, target, li, isFolder=True)
    try:
        client = api()
        auth = ensure_login()
        ensure_profile(client, auth)
        client.cache_dir = None
        client.cache_ttl = 0
        def is_continue(block):
            meta = (block.get("analytics") or {}).get("tealium") or {}
            return (meta.get("from") == "feature.recommended_videos_by_user"
                    or str(meta.get("block_title", "")).casefold() == "verder kijken")
        data = client.layout("alias", "home", complete=True, block_filter=is_continue)
        data = dict(data, blocks=[b for b in data.get("blocks", []) if is_continue(b)])
        _render_rows(_build_rows(data), client, hero_art(data))
    except Exception as exc:
        xbmc.log("[Videoland] both_continue failed ({})".format(type(exc).__name__), xbmc.LOGWARNING)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)



def dispatch(params):
    set_breadcrumb(read_breadcrumb(params.get("breadcrumb")) or ["Videoland"])
    action = params.get("action")
    add_sort_methods(action, params.get("season"))
    if not action:
        return root()
    if action == "login":
        ensure_login()
        xbmc.executebuiltin("Container.Refresh")
    elif action == "clear_cache":
        removed = VideolandApi.clear_cache(cache_dir())
        if params.get("refresh") != "false":
            xbmc.executebuiltin("Container.Refresh")
        xbmcgui.Dialog().notification("Videoland", "Cache gewist ({})".format(removed), time=3000)
    elif action == "logout":
        store_auth({})
        store_credentials(None, None)
        save("profile_id", "")
        save("profile_name", "")
        SyncStore(data_dir()).clear()
        # Older installations may still contain the original login fields.
        save("email", "")
        save("password", "")
        VideolandApi.clear_cache(cache_dir())
        xbmc.executebuiltin("Container.Refresh")
        xbmcgui.Dialog().notification("Videoland", ADDON.getLocalizedString(31008))
    elif action == "profiles":
        choose_profile()
    elif action == "sync_status":
        show_sync_status()
    elif action == "continue_watching":
        continue_watching()
    elif action == "remove_continue_watching":
        remove_continue_watching(params.get("content_id", ""), params.get("profile_id", ""), params.get("title", ""))
    elif action == "related":
        show_related(params.get("kind", "program"), params.get("entity_id", ""),
                     params.get("seo", ""), params.get("title", ""))
    elif action == "layout":
        season = params.get("season")
        show_layout(
            params.get("kind", "alias"),
            params.get("entity_id", "home"),
            params.get("seo", ""),
            season if season in (None, "", "None") else int(season),
            params.get("section"),
            params.get("group"),
        )
    elif action == "search":
        search(params.get("query", ""), params.get("period"), params.get("genre"), params.get("kind"))
    elif action == "search_filter":
        search_filter(params.get("query", ""), params.get("period"), params.get("genre"), params.get("kind"))
    elif action == "play":
        play(params["video_id"], params.get("seo", ""), params.get("parent_id", ""),
             params.get("parent_seo", ""), from_library=params.get("inlib") == "1")
    elif action == "live":
        live_tv()
    elif action == "play_live":
        play_live(params["channel_id"], params.get("seo", ""))
    elif action == "library":
        browse_library()
    elif action == "library_toggle":
        library_toggle(params.get("kind", ""), params.get("id", ""), params.get("seo", ""),
                       params.get("title", ""), params.get("poster") or params.get("thumb", ""),
                       params.get("fanart", ""))
    elif action == "library_remove":
        library_remove(params.get("kind", ""), params.get("id", ""), params.get("title", ""))
    elif action == "library_update":
        library_update(background=params.get("background") == "1")
    elif action == "register_library_sources":
        register_library_sources()
    elif action == "repair_library_art":
        repair_library_art(background=params.get("background") == "1")
    elif action == "diagnostics":
        run_diagnostics()
    elif action == "check_tmdb_key":
        check_tmdb_key()
    elif action == "choose_library_profile":
        choose_library_profile()
    elif action == "choose_tmdb":
        choose_tmdb(params.get("kind", ""), params.get("id", ""))
    elif action == "library_from_watchlist":
        library_from_watchlist(background=params.get("background") == "1")
    elif action == "library_play":
        library_play(params.get("id", ""), params.get("seo", ""))
    elif action == "widgets":
        widgets_menu()
    elif action == "mark_watched":
        mark_watched_on_service(params.get("video_id", ""), params.get("seo", ""),
                                params.get("parent_id", ""), params.get("parent_seo", ""),
                                params.get("watched", "1"))
    elif action == "play_next":
        play_next(params.get("video_id", ""), params.get("parent_id", ""),
                  params.get("parent_seo", ""), params.get("background") == "1")
    elif action == "shuffle":
        shuffle_series(params.get("series_id", ""), params.get("seo", ""))
    elif action == "history":
        browse_history()
    elif action == "clear_history":
        clear_history()
    elif action == "mark_series_watched":
        mark_series_watched(params.get("series_id", ""), params.get("seo", ""), params.get("background") == "1")
    elif action == "notify_new":
        notify_new(params.get("background") == "1")
    elif action == "sync_resume":
        sync_resume(params.get("background") == "1")
    elif action == "recommended":
        recommended()
    elif action == "both_continue":
        both_continue()


def run():
    try:
        _run()
    finally:
        if _LOGO_CACHE:
            _LOGO_CACHE.flush()


def _run():
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    xbmcplugin.setPluginFanart(HANDLE, FANART)
    try:
        _dispatch_with_retry(params)
    except (ApiError, CipherError) as exc:
        xbmc.log("[Videoland] {}".format(exc), xbmc.LOGERROR)
        if params.get("background") != "1":
            message = str(exc)
            if errors_mod.classify(exc) != "unknown":
                message = errors_mod.user_message(exc, "Videoland", xbmc.getLanguage(xbmc.ISO_639_1) or "nl")
            xbmcgui.Dialog().ok("Videoland", message)
        if params.get("action") == "play":
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    except Exception as exc:
        # Unexpected problem: one clear sentence for the user, details in the log.
        xbmc.log("[Videoland] Unexpected error\n" + errors_mod.log_text(exc), xbmc.LOGERROR)
        if params.get("action") in ("play", "play_live", "library_play"):
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        if params.get("background") != "1":
            xbmcgui.Dialog().notification("Videoland", errors_mod.user_message(
                exc, "Videoland", xbmc.getLanguage(xbmc.ISO_639_1) or "nl"), xbmcgui.NOTIFICATION_ERROR, 7000)


def _dispatch_with_retry(params, retried=False):
    """Dispatch, and on an expired-session AuthError silently refresh and retry once."""
    try:
        dispatch(params)
    except AuthError:
        if retried:
            raise
        # Retry once: silent auto-relogin from the stored encrypted credentials.
        _, _, _ = refresh_session()
        xbmc.log("[Videoland] Session verlopen; opnieuw aangemeld en lijst opnieuw geladen", xbmc.LOGINFO)
        dispatch(params)
