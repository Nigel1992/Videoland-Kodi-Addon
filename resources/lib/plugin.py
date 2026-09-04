import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode

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
    is_related_block,
    navigation_entries,
    video_assets,
    walk_item_content,
)
from .crypto import CipherError, decrypt_json, encrypt_json


ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]


def setting(name, default=""):
    return ADDON.getSettingString(name) or default


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


def add(label, route, folder=True, art=None, info=None, playable=False, icon_key=None):
    item = xbmcgui.ListItem(label=label)
    art = dict(art or {})
    icon_path = menu_icon(icon_key)
    if icon_path:
        art.setdefault("icon", icon_path)
        art.setdefault("thumb", icon_path)
    if art:
        item.setArt(art)
    if info:
        item.setInfo("video", info)
    if playable:
        # Mark the item as a directly playable video so pressing Enter triggers
        # playback immediately instead of requiring right-click -> Play.
        item.setProperty("IsPlayable", "true")
    xbmcplugin.addDirectoryItem(HANDLE, route, item, folder)


# Mapping of menu labels (and localised names) to the flat rounded-tile icon.
_ICON_DIR = os.path.join(ADDON.getAddonInfo("path"), "resources", "icons")
_ICON_MAP = {
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
    "profiel": "home",
    "mijn kijklijst": "home",
    "kijklijst": "home",
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

    Returns fresh (auth, profile_id). Raises ApiError when no saved credentials
    exist or login fails (e.g. password changed), so the caller can fall back to
    interactive sign-in.
    """
    email, password = credentials_data()
    if not email or not password:
        raise ApiError("Geen opgeslagen inloggegevens voor automatisch opnieuw inloggen")
    client = api()
    auth = client.login(email, password)
    store_auth(auth)
    store_credentials(email, password)
    profile_id = _resolve_profile(client, auth)
    save("profile_id", profile_id or "")
    return client, auth, profile_id


def ensure_login():
    auth = auth_data()
    if all(auth.get(key) for key in ("uid", "signature", "timestamp")):
        return auth
    # Session absent or unreadable -> try silent auto-relogin from stored creds.
    try:
        _client, fresh, _pid = refresh_session()
        return fresh
    except (ApiError, CipherError):
        pass
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
    client.jwt(auth, profile_id)  # Validate and activate the profile session.
    return profile_id


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


def root():
    auth = auth_data()
    if not auth:
        add("Aanmelden", url(action="login"), False, icon_key="aanmelden")
    else:
        client = api()
        ensure_profile(client, auth)
        try:
            navigation = client.navigation("desktop")
        except ApiError as exc:
            xbmc.log("[Videoland] Navigation fallback: {}".format(exc), xbmc.LOGWARNING)
            navigation = []
        added = add_navigation(navigation)
        if not added:
            add_default_navigation()
        add("Profiel opnieuw kiezen", url(action="profiles"), False, icon_key="profiel")
        add("Afmelden", url(action="logout"), False, icon_key="afmelden")
    add("Cache wissen", url(action="clear_cache"), False, icon_key="cache")
    xbmcplugin.endOfDirectory(HANDLE)


def add_navigation(navigation):
    """Add the useful desktop navigation entries returned by Videoland."""
    added = set()
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
            if kind not in ("alias", "folder") or not entity_id:
                continue
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
    ):
        add(label, url(action="layout", kind="folder", entity_id=entity_id, seo=seo), True, icon_key=label)
    add("Zoeken", url(action="search"), True, icon_key="zoeken")


def show_layout(kind, entity_id, seo="", season=None, section=None):
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/"
    location_suffixes = {"program": "p", "video": "c", "folder": "f"}
    if kind in location_suffixes and seo:
        location += "{}-{}_{}".format(seo, location_suffixes[kind], entity_id.replace("clip_", ""))
    data = client.layout(kind, entity_id, location)
    # Only the Home page keeps Videoland's grouped rail layout. Collection and
    # genre pages (Films/Series/Programma's, folders) also return titled rails in
    # their payload, but users expect those as plain flat lists, so grouping
    # sections there would hide the content behind a few category folders.
    sectioned = kind == "alias" and entity_id == "home"
    show_items(data, season=season, section=section, sectioned=sectioned, client=client)


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


def program_location(seo, entity_id):
    """Build the web location string used to render a program detail page."""
    location = "https://v2.videoland.com/"
    if seo:
        location += "{}-p_{}".format(seo, entity_id)
    return location


def _play_target(client, item, target, target_kind):
    """Return the target to play (video id/seo/parent), or None.

    ``video`` items (episodes/clips) play directly. ``program`` items can be a
    single film whose program page resolves to exactly one playable clip; we peek
    at the cached program layout to detect that and play it straight away instead
    of presenting the film as a navigable series folder. Series keep their
    folder/season UI.
    """
    if target_kind == "video":
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
    data = client.layout("program", target_id, program_location(target.get("seo", ""), target_id))
    rows = _build_rows(data)
    video_rows = [r for r in rows if r[2] == "video"]
    if len(rows) == 1 and video_rows and not _all_seasons(rows):
        clip_target = video_rows[0][1]
        if clip_target and clip_target.get("id"):
            return clip_target
    return None


def _build_rows(data, per_section=False):
    """Collect and de-duplicate the real content items from a layout.

    De-duplication is scoped per block (its title) when ``per_section`` is set,
    or across the whole page otherwise. The Home page groups output into titled
    rails that legitimately repeat popular programs (e.g. a program can appear in
    both "Onlangs toegevoegd" and "Top 10 van vandaag"); a page-global de-dup
    there would wrongly empty those rails, so Home builds with per-section de-dup.
    Flat collection pages (Films/Series/Programma's) use global de-dup to avoid
    listing the same title twice.
    """
    seen = set()
    rows = []
    for item, block in walk_item_content(data):
        target = action_target(item)
        if not target:
            continue
        target_id = str(target.get("id") or "")
        target_kind = target.get("type")
        if not target_id or target_kind not in (
            "program", "video", "alias", "folder", "service", "season", "details"
        ):
            continue
        # Drop recommendation/trailer/hero/ad rails; keep only real content.
        if is_related_block(block):
            continue
        if per_section:
            bucket = str((block or {}).get("block_title") or "")
            key = (bucket, target_kind, target_id)
        else:
            key = (target_kind, target_id)
        if key in seen:
            continue
        seen.add(key)
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


def _render_rows(rows, client=None):
    """"Add every collected row as a directory/playable entry."""
    # Resolve film-vs-series for whole program-list pages in parallel so a big
    # list (e.g. Films, ~90 movies) does not serialize one slow page fetch per
    # item. Program pages are cached, so repeat loads are cheap.
    resolve = {}
    resolve_rows = []
    if client is not None:
        for item, target, target_kind, _block in rows:
            if _needs_program_peek(item, target, target_kind):
                target_id = str(target.get("id") or "")
                if target_id in resolve:
                    continue
                resolve[target_id] = None
                resolve_rows.append((target_id, item, target, target_kind))

    if resolve_rows:
        def _peek(args):
            target_id, item, target, target_kind = args
            try:
                return target_id, _play_target(client, item, target, target_kind)
            except Exception:
                return target_id, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for target_id, play_target in pool.map(_peek, resolve_rows):
                resolve[target_id] = play_target

    for item, target, target_kind, block in rows:
        target_id = str(target.get("id") or "")
        image = item.get("image") or {}
        # Folder/category items (e.g. genre rails like "Competitie") and episodes
        # carry their display name in the artwork caption; title/name are often
        # null. Prefer the caption over extraTitle because Bedrock prefixes
        # extraTitle with "N. " (e.g. "1. Het feest") while the caption holds the
        # clean episode/category name.
        label = (
            item.get("title")
            or item.get("name")
            or (image.get("caption") if isinstance(image.get("caption"), str) else "")
            or item.get("extraTitle")
            or target_id
        )
        if not isinstance(label, str):
            label = str(label)
        art = {}
        if image.get("id"):
            art["thumb"] = "https://images-fio.videoland.bedrock.tech/v2/images/{}/raw".format(image["id"])
        info = {"title": label, "plot": item.get("description") or ""}
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
        if play_target:
            parent = play_target.get("parent") or {}
            add(label, url(
                action="play", video_id=play_target.get("id", target_id),
                seo=play_target.get("seo", ""),
                parent_id=parent.get("id", ""), parent_seo=parent.get("seo", "")
            ), False, art, info, playable=True)
        else:
            add(label, url(
                action="layout", kind=target_kind, entity_id=target_id, seo=target.get("seo", "")
            ), True, art, info)


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
        ), True)


def show_items(data, season=None, section=None, client=None, sectioned=False):
    rows = _build_rows(data)
    seasons = _all_seasons(rows)
    program = _program_identity(data)

    if section is not None:
        # Inside a chosen homepage rail: list only that section's items. Built and
        # de-duplicated per section so overlapping rails keep their full items.
        section_rows = [r for (t, rs) in _section_groups(_build_rows(data, per_section=True))
                        if t == section for r in rs]
        _render_rows(section_rows, client)
    elif sectioned:
        # Home layout: present the titled rails as folders, mirroring the grouped
        # appearance of the real homepage instead of one flat list. Only enabled
        # for the Home page; collection pages keep their plain flat lists.
        sections = _section_groups(_build_rows(data, per_section=True))
        if len(sections) > 1:
            show_sections(sections, program)
        else:
            _render_rows(rows, client)
    elif season is not None:
        # Inside a chosen season folder: show only that season's episodes.
        rows = [r for r in rows if block_season(r[3]) == season]
        _render_rows(rows, client)
    elif len(seasons) > 1:
        # Multi-season series: present only the "Seizoen N" folders. Episodes
        # live inside each season folder and are not listed on the show page.
        for s in seasons:
            add("Seizoen {}".format(s), url(
                action="layout",
                kind=(program or {}).get("kind", "program"),
                entity_id=(program or {}).get("entity_id", ""),
                seo=(program or {}).get("seo", ""),
                season=s,
            ), True)
    else:
        # Single season (or no season info): list the episodes directly.
        _render_rows(rows, client)
    xbmcplugin.endOfDirectory(HANDLE)


def search(query=""):
    query = (query or xbmcgui.Dialog().input("Zoeken in Videoland")).strip()
    if not query:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    if len(query) < 3:
        raise ApiError("Gebruik minimaal 3 tekens om te zoeken")
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/zoeken?" + urlencode({"query": query})
    data = client.layout("frontspace", "search", location, {"query": query})
    show_items(data, client=client)


def play(video_id, seo="", parent_id="", parent_seo=""):
    client = api()
    auth = ensure_login()
    ensure_profile(client, auth)
    location = "https://v2.videoland.com/"
    if parent_id and parent_seo and seo:
        location += "{}-p_{}/{}-c_{}".format(parent_seo, parent_id, seo, video_id.replace("clip_", ""))
    layout = client.layout("video", video_id, location)
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
    item = xbmcgui.ListItem(path=asset["path"])
    item.setMimeType("application/dash+xml")
    item.setContentLookup(False)
    item.setProperty("inputstream", "inputstream.adaptive")
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
        client.LICENSE_URL + "?specConform=true|" + license_headers + "|R{SSM}|R",
    )
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


def dispatch(params):
    action = params.get("action")
    if not action:
        return root()
    if action == "login":
        ensure_login()
        xbmc.executebuiltin("Container.Refresh")
    elif action == "clear_cache":
        removed = VideolandApi.clear_cache(cache_dir())
        xbmc.executebuiltin("Container.Refresh")
        xbmcgui.Dialog().notification("Videoland", "Cache gewist ({})".format(removed), time=3000)
    elif action == "logout":
        store_auth({})
        store_credentials(None, None)
        save("profile_id", "")
        xbmc.executebuiltin("Container.Refresh")
    elif action == "profiles":
        save("profile_id", "")
        client = api()
        ensure_profile(client, ensure_login())
        xbmcgui.Dialog().notification("Videoland", "Profiel gekozen")
    elif action == "layout":
        season = params.get("season")
        show_layout(
            params.get("kind", "alias"),
            params.get("entity_id", "home"),
            params.get("seo", ""),
            season if season in (None, "", "None") else int(season),
            params.get("section"),
        )
    elif action == "search":
        search(params.get("query", ""))
    elif action == "play":
        play(params["video_id"], params.get("seo", ""), params.get("parent_id", ""), params.get("parent_seo", ""))


def run():
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
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
