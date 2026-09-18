"""Persistent progress outbox. Contains playback metadata, never login secrets."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager


class SyncStore:
    def __init__(self, directory):
        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, 'progress.sqlite')
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS pending (
                account TEXT, profile TEXT, video TEXT, revision TEXT, payload TEXT,
                attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0,
                PRIMARY KEY (account, profile, video))''')
            db.execute("""CREATE TABLE IF NOT EXISTS removals (
                account TEXT, profile TEXT, content TEXT, removed_at REAL,
                PRIMARY KEY (account, profile, content))""")
            db.execute('''CREATE TABLE IF NOT EXISTS status (
                account TEXT, profile TEXT, saved_at REAL, position INTEGER, video TEXT,
                error TEXT, PRIMARY KEY (account, profile))''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=45)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, account, profile, config, location, position, reason, started_at=None):
        key = (account, profile, config['session']['videoId'])
        revision = uuid.uuid4().hex
        payload = json.dumps(dict(config=config, location=location, position=position, reason=reason))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if started_at is not None:
                removed = db.execute('SELECT content,removed_at FROM removals WHERE account=? AND profile=?',
                                     (account, profile)).fetchall()
                if any(r['removed_at'] >= started_at and self.matches_content(config, r['content']) for r in removed):
                    return None
            db.execute('INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?, ?, 0, 0)',
                       key + (revision, payload))
        return key, revision

    def deliver(self, key, send, revision=None, enabled=lambda: True):
        # Serialize retries and live saves, including their network requests.
        # A stale retry cannot finish after a newer save and rewind cloud progress.
        failure = None
        result = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM pending WHERE account=? AND profile=? AND video=?', key).fetchone()
            if not row or (revision and row['revision'] != revision) or not enabled():
                return None
            try:
                result = send(json.loads(row['payload']))
            except Exception as exc:
                failure = exc
                attempts = row['attempts'] + 1
                db.execute('UPDATE pending SET attempts=?, retry_at=? WHERE account=? AND profile=? AND video=?',
                           (attempts, time.time() + min(900, 30 * 2 ** min(attempts - 1, 5))) + key)
                # Store a safe error category, not server responses or credentials.
                error = 'auth' if type(exc).__name__ == 'AuthError' else 'connection'
                db.execute('INSERT INTO status(account,profile,error) VALUES(?,?,?) '
                           'ON CONFLICT(account,profile) DO UPDATE SET error=excluded.error', key[:2] + (error,))
            else:
                db.execute('DELETE FROM pending WHERE account=? AND profile=? AND video=?', key)
                db.execute('INSERT OR REPLACE INTO status VALUES(?,?,?,?,?,NULL)',
                           key[:2] + (time.time(), result, key[2]))
        if failure:
            raise failure
        return result

    def due(self, account, now=None):
        with self.connect() as db:
            return [tuple(r) for r in db.execute(
                'SELECT account,profile,video FROM pending WHERE account=? AND retry_at<=? ORDER BY retry_at',
                (account, time.time() if now is None else now))]

    def status(self, account, profile):
        with self.connect() as db:
            row = db.execute('SELECT * FROM status WHERE account=? AND profile=?', (account, profile)).fetchone()
            result = dict(row) if row else {}
            result['pending'] = db.execute('SELECT COUNT(*) FROM pending WHERE account=? AND profile=?',
                                           (account, profile)).fetchone()[0]
            return result

    @staticmethod
    def matches_content(config, content_id):
        session = config.get('session') or {}
        return str(content_id) in {str(session.get(field, '')) for field in ('programId', 'videoId', 'clipId')}

    def remove_content(self, account, profile, content_id, remove):
        # Serialize the cloud removal with retries so an older save cannot undo it.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            remove()
            db.execute('INSERT OR REPLACE INTO removals VALUES(?,?,?,?)',
                       (account, profile, content_id, time.time()))
            for row in db.execute('SELECT video,payload FROM pending WHERE account=? AND profile=?',
                                  (account, profile)).fetchall():
                if self.matches_content(json.loads(row['payload'])['config'], content_id):
                    db.execute('DELETE FROM pending WHERE account=? AND profile=? AND video=?',
                               (account, profile, row['video']))
            if not db.execute('SELECT 1 FROM pending WHERE account=? AND profile=?', (account, profile)).fetchone():
                db.execute('UPDATE status SET error=NULL WHERE account=? AND profile=?', (account, profile))

    def clear(self):
        with self.connect() as db:
            db.execute('DELETE FROM pending')
            db.execute('DELETE FROM status')
            db.execute('DELETE FROM removals')


class DurableWriter:
    def __init__(self, writer, store, enabled=lambda: True):
        self.writer = writer
        self.store = store
        self.enabled = enabled
        self.config = writer.config
        self.duration = writer.duration
        self.started_at = time.time()

    def save(self, position, reason):
        if not self.enabled():
            return None
        entry = self.store.enqueue(self.writer.auth['uid'], self.writer.profile_id,
                                   self.config, self.writer.location, position, reason, self.started_at)
        if entry is None:
            return None
        key, revision = entry
        return self.store.deliver(key, lambda data: self.writer.save(data['position'], data['reason']),
                                  revision, self.enabled)
