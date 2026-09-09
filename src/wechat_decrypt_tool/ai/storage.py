from __future__ import annotations
from .diagnostics import observed, event as diagnostic_event
import logging

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from ..app_paths import get_output_dir


class AIStore:
    """短事务业务存储；与工作流检查点分开，避免模型请求持有数据库锁。"""

    def __init__(self, root: Path | None = None):
        self.root = root or get_output_dir() / "ai"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "ai.sqlite3"
        self.lock = threading.RLock()
        self.revoked_accounts = set()
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, account TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(kind,id));
                CREATE INDEX IF NOT EXISTS records_account ON records(kind,account,updated);
                CREATE INDEX IF NOT EXISTS records_status ON records(kind,json_extract(body,'$.status'),updated);
                CREATE INDEX IF NOT EXISTS records_task_usage ON records(kind,account,json_extract(body,'$.task_id'));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL,
                    kind TEXT NOT NULL, body TEXT NOT NULL, unique_key TEXT UNIQUE,
                    delivered INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
            """)

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            try:
                with db:
                    yield db
            except Exception as error:
                diagnostic_event('storage.transaction.failed', level=logging.ERROR, error=error, committed=False)
                raise
            finally:
                db.close()

    def put(self, kind, body, id=None, account=""):
        id = id or body.get("id") or uuid.uuid4().hex
        body = {**body, "id": id}
        with self.connection() as db:
            if (account or body.get("account", "")) in self.revoked_accounts:
                return body
            db.execute("INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body, account=excluded.account, updated=excluded.updated",
                       (kind, id, account or body.get("account", ""), json.dumps(body, ensure_ascii=False), time.time()))
        return body

    def get(self, kind, id):
        with self.connection() as db:
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind, account=None, limit=None, offset=0, compact=False):
        column = "json_remove(body,'$.results','$.overview','$.models','$.cursors')" if compact else "body"
        args = [kind] if account is None else [kind, account]
        sql = f"SELECT {column} FROM records WHERE kind=?" + (" AND account=?" if account is not None else "") + " ORDER BY updated DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args.extend([limit, offset])
        with self.connection() as db:
            rows = db.execute(sql, args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def tasks_in_status(self, statuses):
        placeholders = ",".join("?" for _ in statuses)
        with self.connection() as db:
            rows = db.execute(f"SELECT body FROM records WHERE kind='task' AND json_extract(body,'$.status') IN ({placeholders}) ORDER BY updated DESC", statuses).fetchall()
        return [json.loads(row[0]) for row in rows]

    @observed('storage.recover_interrupted_usage')
    def recover_interrupted_usage(self):
        """仅在服务启动、尚未接受请求时收尾上次进程遗留的调用。"""
        now = time.time()
        with self.connection() as db:
            # 无法获知进程退出的准确时间，不补造结束时间、耗时或 Token。
            db.execute("""UPDATE records SET
                body=json_set(body,'$.status','interrupted','$.error_type','ProcessInterrupted',
                              '$.recovered_at',?), updated=?
                WHERE kind='usage' AND json_extract(body,'$.status')='running'""", (now, now))
            recovered = db.execute('SELECT changes()').fetchone()[0]
        diagnostic_event('storage.usage.recovered', count=recovered, status='interrupted')

    def latest_event_id(self):
        with self.connection() as db:
            return db.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]

    def delete(self, kind, id):
        with self.connection() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, id))

    def event(self, account, kind, body, unique_key=None):
        with self.connection() as db:
            if account in self.revoked_accounts:
                return
            db.execute("INSERT OR IGNORE INTO events(account,kind,body,unique_key,created) VALUES(?,?,?,?,?)",
                       (account, kind, json.dumps(body, ensure_ascii=False), unique_key, time.time()))

    def events(self, after=0, account=None, pending=False):
        sql, args = "SELECT * FROM events WHERE id>?", [after]
        if account is not None:
            sql += " AND account=?"
            args.append(account)
        if pending:
            sql += " AND delivered=0 AND kind='notification'"
        with self.connection() as db:
            rows = db.execute(sql + " ORDER BY id LIMIT 100", args).fetchall()
        return [{**dict(row), "body": json.loads(row["body"])} for row in rows]

    @observed('storage.acknowledge')
    def acknowledge(self, id):
        with self.connection() as db:
            db.execute("UPDATE events SET delivered=1 WHERE id=?", (id,))

    @observed('storage.purge_account')
    def purge_account(self, account):
        with self.connection() as db:
            self.revoked_accounts.add(account)
            db.execute("DELETE FROM records WHERE account=?", (account,))
            db.execute("DELETE FROM events WHERE account=?", (account,))
