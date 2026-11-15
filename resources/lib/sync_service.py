"""Retry pending cloud progress while Kodi is running, including after restart."""
import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib import library as library_mod
from resources.lib import library_art
from resources.lib import logo_cache as logo_cache_mod
from resources.lib import metadata as metadata_mod
from resources.lib.api import VideolandApi
from resources.lib.crypto import decrypt_json
from resources.lib.progress import ProgressWriter
from resources.lib.sync_store import SyncStore
from resources.lib import watch_sync
from resources.lib import playback_extras


def retry_pending(addon, directory, store):
    if addon.getSettingString('history_source') == 'local' or not addon.getSettingBool('sync_progress'):
        return
    auth = decrypt_json(directory, addon.getSettingString('auth_json'))
    if not auth or not auth.get('uid'):
        return
    enabled = lambda: (addon.getSettingString('history_source') != 'local'
                       and addon.getSettingBool('sync_progress')
                       and bool(addon.getSettingString('auth_json')))
    last_notice = 0
    for key in store.due(auth['uid']):
        if not enabled():
            break
        def send(data):
            client = VideolandApi(addon.getSettingString('device_id') or None, timeout=8)
            client.jwt(auth, key[1])
            writer = ProgressWriter(client, auth, key[1], data['config'], data['location'])
            # A replay is a new session, so don't count the gap as time watched.
            return writer.save(data['position'], 'seek')
        try:
            saved = store.deliver(key, send, enabled=enabled)
            if saved is not None:
                xbmc.log('[Videoland] Queued cloud progress saved at {} seconds'.format(saved), xbmc.LOGINFO)
                if addon.getSettingBool('sync_notifications') and time.monotonic() - last_notice > 60:
                    xbmcgui.Dialog().notification('Videoland', addon.getLocalizedString(31077), time=2500, sound=False)
                    last_notice = time.monotonic()
        except Exception as exc:
            xbmc.log('[Videoland] Cloud retry deferred ({})'.format(type(exc).__name__), xbmc.LOGWARNING)


LIBRARY_STARTUP_DELAY = 120
LIBRARY_CHECK_INTERVAL = 60
LIBRARY_RETRY_INTERVAL = 3600


def library_update_due(addon, now=None):
    """True when automatic updates are on and the last run is old enough."""
    try:
        if not addon.getSettingBool('library_auto_update'):
            return False
        hours = max(1, int(addon.getSettingInt('library_update_hours') or 12))
    except Exception:
        return False
    if not addon.getSettingString('auth_json'):
        return False
    store = library_mod.LibraryStore(library_mod.store_path())
    if store.is_empty() and addon.getSettingBool('library_watchlist_sync'):
        last = store.data.get('last_update') or 0
        current = time.time() if now is None else now
        return current - last >= hours * 3600
    return library_mod.update_due(store, hours, now)


ADDON_ID = 'plugin.video.videoland.nl'


def _rpc(method, params):
    import json
    answer = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    return answer.get('result') or {}


def _read_text(path):
    handle = xbmcvfs.File(path)
    try:
        return handle.read()
    finally:
        handle.close()


class LibraryMonitor(xbmc.Monitor):
    """Notices library scans and watched/unwatched changes in Kodi's library."""

    def __init__(self):
        super().__init__()
        self.scan_finished = False
        self.repeats = watch_sync.Repeats()

    def onScanFinished(self, library):
        if library == 'video':
            self.scan_finished = True

    def onNotification(self, sender, method, data):
        if method != 'VideoLibrary.OnUpdate':
            return
        addon = xbmcaddon.Addon(ADDON_ID)
        if addon.getSettingString('history_source') == 'local' or not addon.getSettingBool('watched_to_service'):
            return
        change = watch_sync.library_update(data)
        if not change:
            return
        media_type, dbid, watched = change
        try:
            path = watch_sync.library_file(media_type, dbid, _rpc)
            params = watch_sync.plugin_params(watch_sync.strm_target(path, _read_text), ADDON_ID)
            if params.get('action') != 'play' or not params.get('video_id'):
                return
            if not self.repeats.fresh(str(params['video_id']), watched):
                return
            query = {'action': 'mark_watched', 'video_id': params['video_id'],
                     'watched': '1' if watched else '0', 'background': '1'}
            for key in ('seo', 'parent_id', 'parent_seo'):
                if params.get(key):
                    query[key] = params[key]
            from urllib.parse import urlencode
            xbmc.executebuiltin('RunPlugin(plugin://{}/?{})'.format(ADDON_ID, urlencode(query)))
        except Exception as exc:
            xbmc.log('[Videoland] Library watched check failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)


class PlaybackFollower(xbmc.Player):
    """Applies the audio/subtitle preference and the binge auto-play."""

    def __init__(self, addon):
        super().__init__()
        self.addon = addon
        self.current = {}
        self.position = 0.0
        self.total = 0.0
        self.repeats = watch_sync.Repeats()

    def onAVStarted(self):
        import json
        window = xbmcgui.Window(10000)
        raw = window.getProperty('videoland.now_playing')
        try:
            self.current = json.loads(raw) if raw else {}
        except ValueError:
            self.current = {}
        window.clearProperty('videoland.stop_after')
        window.clearProperty('videoland.next_armed')
        self.position = 0.0
        self.total = 0.0
        audio = self.addon.getSettingString('preferred_audio') or 'off'
        sub = self.addon.getSettingString('preferred_subtitle') or 'off'
        if audio not in ('', 'off') or sub not in ('', 'off'):
            try:
                result = playback_extras.apply_language(_rpc, audio, sub)
                xbmc.log('[Videoland] language {}'.format(result), xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log('[Videoland] language select failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        if self.addon.getSettingBool('auto_subtitle_search'):
            self._maybe_find_subtitles()

    def _maybe_find_subtitles(self):
        try:
            if xbmc.Monitor().waitForAbort(3):
                return
            if not self.isPlayingVideo() or playback_extras.subtitles_present(_rpc):
                return
            xbmc.executebuiltin('ActivateWindow(subtitlesearch)')
        except Exception:
            pass

    def sample(self):
        if not self.current.get('video_id'):
            return
        try:
            if self.isPlayingVideo():
                value = self.getTime()
                if value and value >= 0:
                    self.position = float(value)
                    self.total = float(self.getTotalTime() or 0)
        except RuntimeError:
            pass

    def _threshold_watched(self):
        if (self.addon.getSettingString('history_source') == 'local'
                or not self.addon.getSettingBool('watched_to_service')):
            return
        try:
            share = max(0.5, min(0.99, int(self.addon.getSettingInt('watched_threshold') or 90) / 100.0))
        except Exception:
            share = 0.9
        current = self.current
        if not current.get('video_id') or not watch_sync.watched_enough(self.position, self.total, share):
            return
        if not self.repeats.fresh(str(current['video_id']), True):
            return
        from urllib.parse import urlencode
        query = {'action': 'mark_watched', 'video_id': current['video_id'], 'watched': '1', 'background': '1'}
        for key in ('seo', 'parent_id', 'parent_seo'):
            if current.get(key):
                query[key] = current[key]
        xbmc.executebuiltin('RunPlugin(plugin://{}/?{})'.format(ADDON_ID, urlencode(query)))

    def onPlayBackStopped(self):
        self._threshold_watched()
        self._binge(natural=False)

    def onPlayBackEnded(self):
        self._threshold_watched()
        self._binge(natural=True)

    def _binge(self, natural=True):
        current, self.current = self.current, {}
        # inputstream.adaptive (DRM) often reports the end of a video as
        # "stopped" rather than "ended", so also treat a stop within the final
        # seconds as a natural end; otherwise auto-play-next never fires.
        near_end = bool(self.total and self.total > 0 and self.position >= self.total - 20)
        if not current.get('video_id') or (not natural and not near_end):
            return
        if (self.addon.getSettingString('next_episode') or 'upnext') != 'auto':
            return
        if xbmcgui.Window(10000).getProperty('videoland.stop_after') == '1':
            return
        query = {'action': 'play_next', 'video_id': current['video_id'],
                 'parent_id': current.get('parent_id', ''), 'parent_seo': current.get('parent_seo', ''),
                 'background': '1'}
        from urllib.parse import urlencode
        xbmc.executebuiltin('RunPlugin(plugin://{}/?{})'.format(ADDON_ID, urlencode(query)))


def repair_art_after_scan(addon):
    store = library_mod.LibraryStore(library_mod.store_path())
    if store.is_empty():
        return 0
    lib = library_mod.Library(None, addon.getSettingString, store=store)
    return library_art.repair_kodi_art(lib, marker='plugin.video.videoland.nl/library')


def repair_dateadded_once(addon):
    """One-off: give existing library episodes a dateadded based on their air
    date, so "recently added" widgets order by when an episode aired. Updates
    Kodi's database directly, so already-scanned episodes are fixed too."""
    if addon.getSettingBool('dateadded_repaired_v2'):
        return
    marker = 'plugin.video.videoland.nl/library'
    try:
        result = _rpc('VideoLibrary.GetEpisodes',
                      {'properties': ['file', 'firstaired', 'dateadded']}) or {}
    except Exception:
        return
    changed = 0
    for ep in result.get('episodes') or []:
        path = str(ep.get('file') or '')
        aired = str(ep.get('firstaired') or '')[:10]
        if marker not in path or len(aired) != 10:
            continue
        desired = aired + ' 12:00:00'
        if str(ep.get('dateadded') or '') == desired:
            continue
        try:
            _rpc('VideoLibrary.SetEpisodeDetails',
                 {'episodeid': ep.get('episodeid'), 'dateadded': desired})
            changed += 1
        except Exception:
            pass
    try:
        addon.setSetting('dateadded_repaired_v2', 'true')
    except Exception:
        pass
    xbmc.log('[Videoland] dateadded repaired for {} episodes'.format(changed), xbmc.LOGINFO)
    try:
        xbmcgui.Dialog().notification('Videoland', addon.getLocalizedString(31222).format(changed),
                                      xbmcgui.NOTIFICATION_INFO, 8000)
        xbmc.executebuiltin('Container.Refresh')
    except Exception:
        pass


def run():
    addon = xbmcaddon.Addon('plugin.video.videoland.nl')
    directory = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.videoland.nl')
    store = SyncStore(directory)
    monitor = LibraryMonitor()
    follower = PlaybackFollower(addon)
    xbmc.log('[Videoland] Cloud progress retry service started', xbmc.LOGINFO)
    source = addon.getSettingString('history_source')
    refresh_pending = False
    next_retry = 0
    started = time.monotonic()
    next_library_check = 0
    next_library_run = 0
    next_scan_check = 0
    next_notify = 0
    next_resume_sync = 0
    while not monitor.abortRequested():
        current = addon.getSettingString('history_source')
        if current != source:
            source = current
            refresh_pending = True
        if (refresh_pending and not xbmc.Player().isPlaying()
                and not xbmc.getCondVisibility('Window.IsActive(addonsettings)')):
            if xbmc.getInfoLabel('Container.FolderPath').startswith('plugin://plugin.video.videoland.nl'):
                xbmc.executebuiltin('Container.Refresh')
            refresh_pending = False
        try:
            if time.monotonic() >= next_retry:
                next_retry = time.monotonic() + 30
                retry_pending(addon, directory, store)
        except Exception as exc:
            xbmc.log('[Videoland] Progress retry unavailable ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        now = time.monotonic()
        if now >= next_scan_check:
            # A scan asked for while Kodi was busy runs as soon as it is free.
            next_scan_check = now + 10
            try:
                library_art.run_pending_scan(library_mod.scan_flag_path())
            except Exception:
                pass
            # Look up logos for titles seen in browse lists, a few at a time.
            if not xbmc.Player().isPlaying() and os.path.isfile(os.path.join(directory, 'logo_queue.json')):
                try:
                    enricher = metadata_mod.Enricher(os.path.join(directory, 'metadata_cache.json'),
                                                     tmdb_key=addon.getSettingString('tmdb_api_key'),
                                                     user_agent='plugin.video.videoland.nl')
                    logo_cache_mod.LogoCache(directory).process(enricher, limit=15,
                                                               should_stop=monitor.abortRequested)
                    enricher.save()
                except Exception as exc:
                    xbmc.log('[Videoland] Logo lookup failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        if monitor.scan_finished:
            monitor.scan_finished = False
            try:
                fixed = repair_art_after_scan(addon)
                if fixed:
                    xbmc.log('[Videoland] Library artwork set for {} titles'.format(fixed), xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log('[Videoland] Library artwork repair failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        if now - started >= LIBRARY_STARTUP_DELAY and not addon.getSettingBool('dateadded_repaired_v2'):
            try:
                repair_dateadded_once(addon)
            except Exception as exc:
                xbmc.log('[Videoland] dateadded repair failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        if now - started >= LIBRARY_STARTUP_DELAY and now >= next_library_check:
            next_library_check = now + LIBRARY_CHECK_INTERVAL
            try:
                if (now >= next_library_run and not xbmc.Player().isPlaying()
                        and library_update_due(addon)):
                    # Retry at most hourly if a run does not record itself.
                    next_library_run = now + LIBRARY_RETRY_INTERVAL
                    xbmc.log('[Videoland] Starting library update', xbmc.LOGINFO)
                    xbmc.executebuiltin('RunPlugin(plugin://plugin.video.videoland.nl/?action=library_update&background=1)')
            except Exception as exc:
                xbmc.log('[Videoland] Library update check failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        follower.sample()
        if (now - started >= LIBRARY_STARTUP_DELAY and now >= next_notify
                and not xbmc.Player().isPlaying() and addon.getSettingBool('notify_new_episodes')):
            next_notify = now + 3 * 3600
            try:
                xbmc.executebuiltin('RunPlugin(plugin://{}/?action=notify_new&background=1)'.format(ADDON_ID))
            except Exception:
                pass
        # Pull watch positions from Videoland into the library (what you watched
        # on another device), shortly after startup and then once an hour.
        if (now - started >= LIBRARY_STARTUP_DELAY and now >= next_resume_sync
                and not xbmc.Player().isPlaying() and addon.getSettingBool('sync_resume_from_service')):
            next_resume_sync = now + 3600
            try:
                xbmc.executebuiltin('RunPlugin(plugin://{}/?action=sync_resume&background=1)'.format(ADDON_ID))
            except Exception:
                pass
        if monitor.waitForAbort(1):
            break
