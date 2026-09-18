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
from .progress import ProgressWriter, heartbeat_config, monitor_class
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
        cache_dir=cache_dir() if enabled else None,
        cache_ttl=cache_ttl() if enabled else 0,
    )
    if not device_id:
        save("device_id", client.device_id)
    return client


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
_ICON_DIR = os.path.join(ADDON_PATH, "resources", "icons", "polished")
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
    "live tv": "collection",
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
        add("Aanmelden", url(action="login"), False, icon_key="aanmelden")
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
        name = active_profile_name(client, auth)
        add(ADDON.getLocalizedString(31060).format(name), url(action="profiles"), False, icon_key="profiel")
        if not local_history():
            add(ADDON.getLocalizedString(31061), url(action="continue_watching"), True, icon_key="continue")
        add("Afmelden", url(action="logout"), False, icon_key="afmelden")
    add("Cache wissen", url(action="clear_cache"), False, icon_key="cache")
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


def _render_rows(rows, client=None, page_art=None):
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
        label = (
            item.get("title")
            or item.get("name")
            or caption
            or _clean_episode_label(item.get("extraTitle"))
            or item.get("extraTitle")
            or target_id
        )
        if not isinstance(label, str):
            label = str(label)
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


def search(query=""):
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
    location = "https://v2.videoland.com/zoeken?" + urlencode({"query": query})
    data = client.layout("frontspace", "search", location, {"query": query}, complete=True)
    show_items(data, client=client)


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


def play(video_id, seo="", parent_id="", parent_seo=""):
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
    resume_position = 0 if use_local else get_resume_position(layout, video_id)
    if resume_position > 0:
        # Ask user if they want to resume
        dialog = xbmcgui.Dialog()
        ret = dialog.yesnocustom(
            "Verder kijken",
            f"Er is een hervatingspunt gevonden op {resume_position // 60}:{resume_position % 60:02d}. " +
            "Wilt u vanaf hier verder kijken?",
            customlabel="Annuleren",
            yeslabel="Hervatten",
            nolabel="Vanaf het begin"
        )
        # yesno() conflates Back/Escape with the explicit restart button.
        # Only the two playback choices may resolve a stream or start syncing.
        if ret not in (0, 1):
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        if ret == 0:
            resume_position = 0  # Explicitly selected "Vanaf het begin".

    assets = list(video_assets(layout, video_id))
    dash = [a for a in assets if a.get("format") == "dash" or ".mpd" in a.get("path", "")]
    if not dash:
        raise ApiError("Geen DASH-stream gevonden")
    # Some devices (e.g. Pi 5 / Widevine on LibreELEC) require the software-L3
    # rendition and fail to decrypt the hardware (L1) rendition (CDM "kNoKey").
    # Software-L3 is the default; "best available" opts into the highest stream.
    software = [a for a in dash if (a.get("drm") or {}).get("type") == "software"]
    prefer_software = setting_int("preferred_quality", 1) == 1
    asset = (software[0] if software else dash[0]) if prefer_software else (dash[0] if dash else software[0])
    drm_token = client.upfront_token(auth["uid"], video_id)
    item = _dash_item(helper, asset, drm_token)

    # Kodi's plugin resolver forces resume from the resolved video info tag.
    # StartOffset alone is not carried through that resolver on Kodi 21.
    # CBookmark::IsSet requires a positive total duration, even for restart.
    tracker = None
    if not use_local:
        duration = get_video_duration(layout, video_id)
        item.getVideoInfoTag().setResumePoint(
            float(resume_position), max(duration, float(resume_position) + 1.0))
        item.setProperty("StartOffset", str(resume_position))
        xbmc.log("[Videoland] {}: selected playback position {} seconds".format(
            video_id, resume_position), xbmc.LOGINFO)
        tracker = progress_tracker(client, auth, layout, video_id, location, asset["path"])
    xbmcplugin.setResolvedUrl(HANDLE, True, item)
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
    software = [a for a in dash if (a.get("drm") or {}).get("type") == "software"]
    prefer_software = setting_int("preferred_quality", 1) == 1
    return (software[0] if software else dash[0]) if prefer_software else (dash[0] if dash else software[0])


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


def dispatch(params):
    set_breadcrumb(read_breadcrumb(params.get("breadcrumb")) or ["Videoland"])
    action = params.get("action")
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
        search(params.get("query", ""))
    elif action == "play":
        play(params["video_id"], params.get("seo", ""), params.get("parent_id", ""), params.get("parent_seo", ""))
    elif action == "live":
        live_tv()
    elif action == "play_live":
        play_live(params["channel_id"], params.get("seo", ""))


def run():
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    xbmcplugin.setPluginFanart(HANDLE, FANART)
    try:
        _dispatch_with_retry(params)
    except (ApiError, CipherError) as exc:
        xbmc.log("[Videoland] {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Videoland", str(exc))
        if params.get("action") == "play":
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


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
