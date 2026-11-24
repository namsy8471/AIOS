"""Durable broker activity. Each entry describes a request without its arguments."""
from contextlib import contextmanager
from functools import wraps
import fcntl
import hashlib
import inspect
import json
import sqlite3
import threading
import time
import uuid


def checksum(previous, fields):
    packet = json.dumps([previous, *fields], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(packet.encode()).hexdigest()


class Activity:
    def __init__(self, path, grant):
        # SQLite serializes SQL transactions. This separate lifetime lock gives
        # exactly one broker authority to close abandoned requests at startup.
        self.owner = path.open("a+b")
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.grant = grant
        self.db.execute("PRAGMA synchronous=EXTRA")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, at_ns INTEGER NOT NULL, grant_id TEXT NOT NULL,
                request TEXT NOT NULL, tool TEXT NOT NULL, outcome TEXT NOT NULL,
                revision TEXT, hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS by_request ON events(request, seq);
            CREATE TRIGGER IF NOT EXISTS prevent_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS prevent_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)
        with self.db:
            previous = ""
            for *fields, stored in self.db.execute(
                    "SELECT at_ns,grant_id,request,tool,outcome,revision,hash FROM events ORDER BY seq"):
                if checksum(previous, fields) != stored:
                    raise ValueError("Broken activity hash chain")
                previous = stored
            # One broker owns the guest serial endpoint. A previous instance may
            # have died between publishing the document and recording the reply.
            pending = self.db.execute("""
                SELECT a.grant_id,a.request,a.tool FROM events a
                WHERE a.outcome='started' AND NOT EXISTS
                  (SELECT 1 FROM events b WHERE b.request=a.request AND b.seq>a.seq)
            """).fetchall()
            for grant_id, request, tool in pending:
                self._insert(grant_id, request, tool, "outcome_unknown", None)

    def _insert(self, grant, request, tool, outcome, revision):
        last = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        fields = (time.time_ns(), grant, request, tool, outcome, revision)
        self.db.execute("INSERT INTO events(at_ns,grant_id,request,tool,outcome,revision,hash) "
                        "VALUES(?,?,?,?,?,?,?)", (*fields, checksum(last[0] if last else "", fields)))

    def record(self, request, tool, outcome, revision=None):
        with self.lock, self.db:
            self._insert(self.grant, request, tool, outcome, revision)

    @contextmanager
    def attempt(self, tool):
        request = uuid.uuid4().hex
        self.record(request, tool, "started")
        try:
            yield lambda result: self.record(request, tool, "succeeded", result.revision)
        except StagedDiscarded:
            self.record(request, tool, "discarded")
            raise
        except ValueError:
            self.record(request, tool, "rejected")
            raise
        except BaseException:
            self.record(request, tool, "outcome_unknown")
            raise

    def recent(self, limit):
        if not 1 <= limit <= 100:
            raise ValueError("Expected a limit between 1 and 100")
        with self.lock:
            rows = self.db.execute("SELECT seq,at_ns,request,tool,outcome,revision FROM events "
                                   "WHERE grant_id=? ORDER BY seq DESC LIMIT ?", (self.grant, limit)).fetchall()
        return [dict(zip(("seq", "at_ns", "request", "tool", "outcome", "revision"), row)) for row in rows]


class StagedDiscarded(ValueError):
    pass


def tracked(activity):
    def decorate(fn):
        if activity is None:
            return fn
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def invoke(*args, **kwargs):
                with activity.attempt(fn.__name__) as succeeded:
                    result = await fn(*args, **kwargs)
                    succeeded(result)
                    return result
        else:
            @wraps(fn)
            def invoke(*args, **kwargs):
                with activity.attempt(fn.__name__) as succeeded:
                    result = fn(*args, **kwargs)
                    succeeded(result)
                    return result
        return invoke
    return decorate
