"""Retry pending cloud progress while Kodi is running, including after restart."""
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

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


def run():
    addon = xbmcaddon.Addon('plugin.video.videoland.nl')
    directory = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.videoland.nl')
    store = SyncStore(directory)
    monitor = xbmc.Monitor()
    xbmc.log('[Videoland] Cloud progress retry service started', xbmc.LOGINFO)
    source = addon.getSettingString('history_source')
    refresh_pending = False
    next_retry = 0
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
        if monitor.waitForAbort(1):
            break
