"""Foreground approval inbox with durable replay protection.

The host supplies independently verified human provenance, external writer
ownership and the existing publisher. This module never starts a service.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from approval_event_contract import ApprovalEventBlocked, approval_binding, validate_event


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def event_hash(event):
    return hashlib.sha256(canonical(event).encode()).hexdigest()


class Inbox:
    def __init__(self, path):
        path = Path(path).absolute()
        if any(p.is_symlink() or p.is_junction() or (p / ".git").exists()
               for p in (path, *path.parents)):
            raise ApprovalEventBlocked("PRIVATE_INBOX_PATH_REQUIRED")
        if path.resolve() != path:
            raise ApprovalEventBlocked("PRIVATE_INBOX_PATH_REQUIRED")
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                    article_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL,
                    envelope TEXT NOT NULL, recovery_allowed INTEGER NOT NULL,
                    state TEXT NOT NULL, continuation TEXT NOT NULL DEFAULT 'NONE'
                );
                CREATE TABLE IF NOT EXISTS ownership(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    event_id TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def accept(self, event, identity, *, human_origin, recovery_allowed, now):
        """human_origin is returned by the trusted local approval surface."""
        if (not isinstance(human_origin, dict) or human_origin.get("kind") != "WINDOWS_DIRECT"
                or human_origin.get("binding") != approval_binding(**identity)
                or type(recovery_allowed) is not bool):
            raise ApprovalEventBlocked("DIRECT_USER_APPROVAL_REQUIRED")
        checked = validate_event(
            event, identity, trusted_actor=human_origin.get("actor"),
            trusted_approval_ref=human_origin.get("reference"), now=now,
            consumed_event_ids=set(),
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
            digest = event_hash(event)
            if old:
                if old[0] != digest:
                    raise ApprovalEventBlocked("EVENT_CONTENT_CHANGED")
                return "ALREADY_RECORDED"
            try:
                db.execute(
                    "INSERT INTO events(event_id,binding,article_id,digest,envelope,recovery_allowed,state)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (event["event_id"], checked["binding_sha256"], event["article_id"],
                     digest, canonical(event), int(recovery_allowed), "PENDING"),
                )
            except sqlite3.IntegrityError:
                raise ApprovalEventBlocked("ARTICLE_ALREADY_CLAIMED") from None
        return "RECORDED"

    def claim(self, event_id, *, identity, now, revoked, recovery=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT envelope,binding,recovery_allowed,state FROM events WHERE event_id=?", (event_id,),
            ).fetchone()
            if not row or row[1] != approval_binding(**identity) or revoked:
                raise ApprovalEventBlocked("EVENT_MISSING_CHANGED_OR_REVOKED")
            event, binding, recovery_allowed, state = row
            event = json.loads(event)
            if state == "DONE":
                return None
            if state == "PENDING":
                if recovery or not datetime.fromisoformat(event["approved_at"]) <= now < datetime.fromisoformat(event["expires_at"]):
                    raise ApprovalEventBlocked("UNSTARTED_APPROVAL_EXPIRED")
            elif not recovery or not recovery_allowed or state != "PARTIAL":
                raise ApprovalEventBlocked("EXPLICIT_SAME_IDENTITY_RECOVERY_REQUIRED")
            if db.execute("SELECT 1 FROM ownership").fetchone():
                raise ApprovalEventBlocked("WORKER_ALREADY_ACTIVE_OR_CRASHED")
            db.execute("INSERT INTO ownership VALUES(1,?)", (event_id,))
            db.execute("UPDATE events SET state='RUNNING' WHERE event_id=?", (event_id,))
            return event

    def finish(self, event_id, complete):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT event_id FROM ownership").fetchone() != (event_id,):
                raise ApprovalEventBlocked("WORKER_OWNERSHIP_REQUIRED")
            db.execute("UPDATE events SET state=?,continuation=? WHERE event_id=?",
                       ("DONE" if complete else "PARTIAL", "PENDING" if complete else "NONE", event_id))
            db.execute("DELETE FROM ownership")

    def continue_candidate(self, event_id, notify):
        with self.connect() as db:
            row = db.execute("SELECT state,continuation FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row != ("DONE", "PENDING"):
            return False
        # notify must conditionally upsert by completion ID. A lost response may
        # cause a retry; only its acknowledged write marks the outbox complete.
        if notify(event_id) is not True:
            return False
        with self.connect() as db:
            db.execute("UPDATE events SET continuation='ACK' WHERE event_id=? AND state='DONE'", (event_id,))
        return True


def run_once(inbox, event_id, identity, *, now, writer_guard, publish, revoked, recovery=False):
    """writer_guard must validate cross-client ownership before every mutation."""
    with writer_guard(event_id, identity):
        event = inbox.claim(event_id, identity=identity, now=now, recovery=recovery, revoked=revoked)
        if event is None:
            return "ALREADY_COMPLETED"
        try:
            report = publish(event, recover=recovery)
        except Exception:
            inbox.finish(event_id, False)
            raise ApprovalEventBlocked("PUBLICATION_PARTIAL_RECONCILE_REQUIRED") from None
        complete = (isinstance(report, dict)
                    and report.get("status") == "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS"
                    and report.get("durable_result_saved") is True)
        inbox.finish(event_id, complete)
        return "DONE" if complete else "PARTIAL"


def foreground_cycle(poll, process, *, stop, interval=30):
    """Caller starts this loop explicitly and owns authenticated queue reads."""
    if not 1 <= interval <= 60:
        raise ValueError("POLL_INTERVAL_INVALID")
    while not stop():
        for event in poll():
            process(event)
        if not stop():
            time.sleep(interval)
