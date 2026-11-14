"""Retry pending cloud progress while Kodi is running, including after restart."""
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib import library as library_mod
from resources.lib.api import VideolandApi
from resources.lib.crypto import decrypt_json
from resources.lib.progress import ProgressWriter
from resources.lib.sync_store import SyncStore


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
    return library_mod.update_due(store, hours, now)


def run():
    addon = xbmcaddon.Addon('plugin.video.videoland.nl')
    directory = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.videoland.nl')
    store = SyncStore(directory)
    monitor = xbmc.Monitor()
    xbmc.log('[Videoland] Cloud progress retry service started', xbmc.LOGINFO)
    source = addon.getSettingString('history_source')
    refresh_pending = False
    next_retry = 0
    started = time.monotonic()
    next_library_check = 0
    next_library_run = 0
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
        if monitor.waitForAbort(1):
            break
