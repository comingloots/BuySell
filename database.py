import sqlite3
from pathlib import Path
from contextlib import contextmanager


class Database:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def conn(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def init(self):
        with self.conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS verified_users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                verified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY,
                state TEXT
            );
            CREATE TABLE IF NOT EXISTS join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO settings(key,value) VALUES
              ('welcome_message','Hello {first_name}! Please submit your join request.'),
              ('verified_message','✅ You are verified, {first_name}. Your join request is now visible to the channel admins.'),
              ('welcome_photo',''), ('verified_photo',''), ('welcome_buttons',''), ('verified_buttons','');
            """)

    def get_settings(self):
        with self.conn() as c:
            rows = c.execute("SELECT key,value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def set_setting(self, key, value):
        with self.conn() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def is_verified(self, user_id):
        with self.conn() as c:
            return c.execute("SELECT 1 FROM verified_users WHERE user_id=?", (user_id,)).fetchone() is not None

    def add_verified(self, user_id, name="", username=""):
        with self.conn() as c:
            c.execute("""INSERT INTO verified_users(user_id,name,username)
                         VALUES(?,?,?)
                         ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username""",
                      (user_id, name, username))

    def remove_verified(self, user_id):
        with self.conn() as c:
            c.execute("DELETE FROM verified_users WHERE user_id=?", (user_id,))

    def list_verified(self, limit=50):
        with self.conn() as c:
            return c.execute("SELECT * FROM verified_users ORDER BY verified_at DESC LIMIT ?", (limit,)).fetchall()

    def add_admin(self, user_id):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (user_id,))

    def remove_admin(self, user_id):
        with self.conn() as c:
            c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))

    def is_admin(self, user_id):
        with self.conn() as c:
            return c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None

    def list_admins(self):
        with self.conn() as c:
            return c.execute("SELECT * FROM admins ORDER BY added_at DESC").fetchall()

    def add_channel(self, chat_id, title=""):
        with self.conn() as c:
            c.execute("""INSERT INTO channels(chat_id,title) VALUES(?,?)
                         ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""", (chat_id, title))

    def delete_channel(self, row_id):
        with self.conn() as c:
            c.execute("DELETE FROM channels WHERE id=?", (row_id,))

    def list_channels(self):
        with self.conn() as c:
            return c.execute("SELECT * FROM channels ORDER BY id DESC").fetchall()

    def set_state(self, user_id, state):
        with self.conn() as c:
            c.execute("""INSERT INTO user_state(user_id,state) VALUES(?,?)
                         ON CONFLICT(user_id) DO UPDATE SET state=excluded.state""", (user_id, state))

    def get_state(self, user_id):
        with self.conn() as c:
            row = c.execute("SELECT state FROM user_state WHERE user_id=?", (user_id,)).fetchone()
            return row["state"] if row else None

    def clear_state(self, user_id):
        with self.conn() as c:
            c.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))

    def record_join_request(self, user_id, chat_id, name):
        with self.conn() as c:
            c.execute("INSERT INTO join_requests(user_id,chat_id,name) VALUES(?,?,?)",
                      (user_id, chat_id, name))

    def stats(self):
        with self.conn() as c:
            def count(table):
                return c.execute(f"SELECT COUNT(*) n FROM {table}").fetchone()["n"]
            return {
                "verified": count("verified_users"),
                "channels": count("channels"),
                "admins": count("admins"),
                "requests": count("join_requests")
            }
