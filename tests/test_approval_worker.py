from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from approval_event_contract import ApprovalEventBlocked
from approval_worker import Inbox, foreground_cycle, run_once
import test_approval_event_contract as contract_fixtures


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.fixture = contract_fixtures.ApprovalContractTests()
        self.fixture.setUp()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "inbox.sqlite"
        self.inbox = Inbox(self.path)
        self.event = self.fixture.event
        self.identity = self.fixture.identity
        self.now = self.fixture.now
        self.origin = dict(kind="WINDOWS_DIRECT", binding=self.event["binding_sha256"],
                           actor=self.event["reviewer"], reference=self.event["approval_ref"])
        self.inbox.accept(self.event, self.identity, human_origin=self.origin,
                          recovery_allowed=True, now=self.now)

    def invoke(self, publisher, **kwargs):
        kwargs.setdefault("revoked", False)
        return run_once(self.inbox, self.event["event_id"], self.identity, now=self.now,
                        writer_guard=lambda *_: nullcontext(), publish=publisher, **kwargs)

    def test_restart_replay_and_article_reuse(self):
        self.inbox = Inbox(self.path)
        self.assertEqual(self.inbox.accept(self.event, self.identity, human_origin=self.origin,
                                          recovery_allowed=True, now=self.now), "ALREADY_RECORDED")
        changed = dict(self.event, event_id="d" * 32)
        with self.assertRaisesRegex(ApprovalEventBlocked, "ARTICLE_ALREADY"):
            self.inbox.accept(changed, self.identity, human_origin=self.origin,
                              recovery_allowed=True, now=self.now)
        done = {"status": "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS", "durable_result_saved": True}
        self.assertEqual(self.invoke(lambda *_ , **kw: done), "DONE")
        self.assertEqual(self.invoke(lambda *_ , **kw: self.fail("replayed publisher")), "ALREADY_COMPLETED")

    def test_concurrent_claim_and_crash_do_not_expire_ownership(self):
        self.inbox.claim(self.event["event_id"], identity=self.identity, now=self.now, revoked=False)
        restarted = Inbox(self.path)
        with self.assertRaises(ApprovalEventBlocked):
            restarted.claim(self.event["event_id"], identity=self.identity,
                            now=self.now + timedelta(days=1), recovery=True, revoked=False)

    def test_failure_requires_same_identity_recovery_and_continuation_is_idempotent(self):
        self.assertEqual(self.invoke(lambda *_ , **kw: {"status": "LIVE_QA_BLOCKED"}), "PARTIAL")
        self.now += timedelta(days=1)
        with self.assertRaises(ApprovalEventBlocked):
            self.invoke(lambda *_ , **kw: {})
        done = {"status": "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS", "durable_result_saved": True}
        self.assertEqual(self.invoke(lambda *_ , **kw: done, recovery=True), "DONE")
        ident = self.event["event_id"]
        self.assertFalse(self.inbox.continue_candidate(ident, lambda _: False))
        self.assertTrue(self.inbox.continue_candidate(ident, lambda _: True))
        self.assertFalse(self.inbox.continue_candidate(ident, lambda _: self.fail("duplicate handoff")))

    def test_missing_human_origin_and_revocation_block(self):
        with self.assertRaises(ApprovalEventBlocked):
            self.inbox.accept(self.event, self.identity, human_origin={"kind": "DOC_LAST_EDITOR"},
                              recovery_allowed=True, now=self.now)
        with self.assertRaises(ApprovalEventBlocked):
            self.invoke(lambda *_ , **kw: self.fail("revoked publication"), revoked=True)

    def test_foreground_polls_only_when_running(self):
        processed = []
        foreground_cycle(lambda: ["fixture"], processed.append,
                         stop=lambda: bool(processed), interval=1)
        self.assertEqual(processed, ["fixture"])
