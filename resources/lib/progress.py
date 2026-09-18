"""Profile-bound Videoland heartbeat writes and Kodi playback tracking."""
import copy
import math
import queue
import threading
import time

from .api import ApiError, AuthError, walk_item_content


def heartbeat_config(layout, video_id):
    for item, _ in walk_item_content(layout):
        video = item.get('video') or {}
        if video.get('id') != video_id:
            continue
        config = (item.get('analytics') or {}).get('heartbeat-v2')
        if isinstance(config, dict) and (config.get('session') or {}).get('videoId') == video_id:
            return copy.deepcopy(config)
    return None


class ProgressWriter:
    """Only used by one worker; retain profile and sequence across writes."""
    def __init__(self, client, auth, profile_id, config, location):
        self.client = client
        self.auth = dict(auth)
        self.profile_id = profile_id
        self.config = config
        self.location = location
        self.session_id = None
        self.sequence = 0
        self.previous = None
        self.duration = float(config['session']['clipDuration'])

    def save(self, position, reason):
        if not math.isfinite(position):
            return
        position = int(round(min(self.duration, max(0, position))))
        if self.client.session_expired():
            self.client.jwt(self.auth, self.profile_id)
        if not self.session_id:
            try:
                self.session_id = self.client.progress_session(self.auth['uid'], self.config['session'])
            except AuthError:
                self.client.jwt(self.auth, self.profile_id)
                self.session_id = self.client.progress_session(self.auth['uid'], self.config['session'])
        relative = 0 if self.previous is None or reason == 'seek' else max(0, position - self.previous)
        if relative > self.config.get('polling', 240):
            relative = 0
        view = dict(self.config.get('view') or {}, file=self.location, tc=position,
                    tcRelative=relative, sequenceNumber=self.sequence, sessionId=self.session_id)
        try:
            result = self.client.progress_view(self.auth['uid'], view)
        except AuthError:
            self.client.jwt(self.auth, self.profile_id)
            result = self.client.progress_view(self.auth['uid'], view)
        csl = (result.get('view_information') or {}).get('csl') or {}
        if csl.get('allowed') is False:
            raise ApiError('Videoland rejected playback progress')
        self.sequence += 1
        self.previous = position
        return position


def monitor_class(xbmc):
    # Construct lazily so pure heartbeat code can be tested without Kodi modules.
    class PlaybackProgress(xbmc.Player):
        def __init__(self, writer, stream, enabled, notify, log):
            super().__init__()
            self.writer = writer
            self.stream = stream
            self.enabled = enabled
            self.notify = notify
            self.log = log
            self.events = queue.Queue()
            self.writes = queue.Queue()
            self.started = False
            self.position = None
            self.finished = False
            self.last_sync = 0
            self.last_notice = 0
            self.last_error_notice = 0
            self.worker = None

        def onAVStarted(self):
            self.events.put(('start', None))

        def onPlayBackSeek(self, time, seekOffset):
            self.events.put(('seek', time / 1000.0))

        def onPlayBackPaused(self):
            self.events.put(('pause', None))

        def onPlayBackStopped(self):
            self.events.put(('stop', None))

        def onPlayBackEnded(self):
            self.events.put(('end', None))

        def onPlayBackError(self):
            self.events.put(('stop', None))

        def matches(self):
            try:
                return self.isPlayingVideo() and self.getPlayingFile() == self.stream
            except RuntimeError:
                return False

        def sample(self):
            try:
                if self.matches():
                    value = self.getTime()
                    if math.isfinite(value) and value >= 0:
                        self.position = value
            except RuntimeError:
                pass

        def submit(self, reason):
            if self.position is not None and self.enabled():
                self.writes.put((self.position, reason))
                self.last_sync = time.monotonic()

        def write_loop(self):
            while True:
                entry = self.writes.get()
                if entry is None:
                    return
                position, reason = entry
                if not self.enabled():
                    continue
                try:
                    saved = self.writer.save(position, reason)
                    if saved is None:
                        continue
                    self.log('Cloud progress saved at {} seconds ({})'.format(saved, reason), False)
                    now = time.monotonic()
                    # Periodic saves stay quiet; throttle repeated seeks/pauses.
                    if reason in ('seek', 'pause', 'stop', 'end') and (reason in ('stop', 'end') or now - self.last_notice >= 10):
                        self.notify(True, saved)
                        self.last_notice = now
                except Exception as exc:
                    # Do not expose session/profile IDs or tokens in log messages.
                    self.log('Cloud progress failed ({})'.format(type(exc).__name__), True)
                    now = time.monotonic()
                    if now - self.last_error_notice >= 60:
                        self.notify(False, position)
                        self.last_error_notice = now

        def run(self):
            monitor = xbmc.Monitor()
            deadline = time.monotonic() + 60
            self.worker = threading.Thread(target=self.write_loop, name='VideolandProgress')
            self.worker.start()
            try:
                while not self.finished and not monitor.abortRequested():
                    while not self.events.empty():
                        reason, position = self.events.get()
                        if reason == 'start':
                            if self.matches():
                                self.started = True
                                self.sample()
                                self.submit('start')
                        elif not self.started and reason in ('stop', 'end'):
                            # Playback cancelled/failed before AV started: no bookmark to write.
                            self.finished = True
                        elif self.started:
                            if reason == 'seek':
                                self.position = position
                            elif reason == 'end':
                                self.position = self.writer.duration
                            elif reason == 'pause':
                                self.sample()
                            self.submit(reason)
                            if reason in ('stop', 'end'):
                                self.finished = True
                    if self.finished:
                        break
                    if self.started:
                        if not self.matches():
                            self.submit('stop')
                            break
                        self.sample()
                        if time.monotonic() - self.last_sync >= self.writer.config.get('polling', 240):
                            self.submit('periodic')
                    elif time.monotonic() >= deadline:
                        break
                    monitor.waitForAbort(0.5)
                if monitor.abortRequested() and self.started and not self.finished:
                    self.submit('stop')
            finally:
                self.writes.put(None)
                self.worker.join()

    return PlaybackProgress
