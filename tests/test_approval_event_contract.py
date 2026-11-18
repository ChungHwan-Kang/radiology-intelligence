from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from approval_event_contract import ApprovalEventBlocked, approval_binding, validate_event
from connected_publication_coordinator import NEWS_RECORD_COMPONENTS, RECORD_COMPONENTS


class ApprovalContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(
            article_id="RI-999", doi="10.1000/fixture", review_sha256="a" * 64,
            source_contract={"source_kind": "master_news", "source_master_id": "RB-999",
                             "source_master_content_stage": "Private"},
            components=list(NEWS_RECORD_COMPONENTS),
        )
        self.event = dict(
            self.identity, version=1, event_id="b" * 32, action="APPROVE_PUBLICATION",
            binding_sha256=approval_binding(**self.identity), reviewer="fixture-reviewer",
            approval_ref="fixture-private-event", approved_at="2026-11-18T09:00:00+09:00",
            expires_at="2026-11-18T10:00:00+09:00",
        )
        self.now = datetime.fromisoformat("2026-11-18T09:30:00+09:00")

    def validate(self, event=None, **overrides):
        arguments = dict(trusted_actor="fixture-reviewer", trusted_approval_ref="fixture-private-event",
                         now=self.now, consumed_event_ids=set())
        arguments.update(overrides)
        return validate_event(event or self.event, self.identity, **arguments)

    def test_news_four_and_research_five_bindings(self):
        result = self.validate()
        self.assertFalse(result["publication_authorized_by_validator"])
        research = dict(self.identity, source_contract={
            "source_kind": "research_watch", "source_watch_doi": self.identity["doi"],
        }, components=list(RECORD_COMPONENTS))
        event = dict(self.event, **research, binding_sha256=approval_binding(**research))
        self.assertEqual(validate_event(
            event, research, trusted_actor=event["reviewer"], trusted_approval_ref=event["approval_ref"],
            now=self.now, consumed_event_ids=set())["event_id"], self.event["event_id"])

    def test_changed_identity_provenance_replay_and_expiry_block(self):
        for key, value in (("review_sha256", "c" * 64), ("article_id", "RI-998"),
                           ("doi", "10.1000/other"), ("action", "MERGE_PR"),
                           ("reviewer", "untrusted")):
            event = deepcopy(self.event)
            event[key] = value
            with self.subTest(key=key), self.assertRaises(ApprovalEventBlocked):
                self.validate(event)
        with self.assertRaisesRegex(ApprovalEventBlocked, "CONSUMED"):
            self.validate(consumed_event_ids={self.event["event_id"]})
        with self.assertRaisesRegex(ApprovalEventBlocked, "TIME_INVALID"):
            self.validate(now=datetime.fromisoformat(self.event["expires_at"]))
        with self.assertRaisesRegex(ApprovalEventBlocked, "PROVENANCE"):
            self.validate(trusted_actor="")

    def test_wrong_component_set_and_source_are_blocked(self):
        identity = dict(self.identity, components=list(RECORD_COMPONENTS))
        with self.assertRaisesRegex(ApprovalEventBlocked, "COMPONENT"):
            approval_binding(**identity)
        identity = deepcopy(self.identity)
        identity["source_contract"]["source_master_content_stage"] = "Published"
        with self.assertRaisesRegex(ApprovalEventBlocked, "SOURCE_CONTRACT"):
            approval_binding(**identity)
