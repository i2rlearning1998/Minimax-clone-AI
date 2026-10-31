import sqlite3
from contextlib import contextmanager


class History:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS generations (
                id TEXT PRIMARY KEY, audio_url TEXT NOT NULL, duration_sec REAL NOT NULL,
                language TEXT NOT NULL, voice_id TEXT NOT NULL, text TEXT NOT NULL,
                speed REAL NOT NULL, created_at TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, item):
        with self.connection() as db:
            db.execute('INSERT INTO generations VALUES (:id, :audio_url, :duration_sec, :language, :voice_id, :text, :speed, :created_at)', item)

    def get(self, identifier):
        with self.connection() as db:
            row = db.execute('SELECT * FROM generations WHERE id=?', (identifier,)).fetchone()
            return dict(row) if row else None

    def list(self, limit, offset):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM generations ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', (limit, offset))]

    def delete(self, identifier):
        with self.connection() as db:
            return db.execute('DELETE FROM generations WHERE id=?', (identifier,)).rowcount > 0
