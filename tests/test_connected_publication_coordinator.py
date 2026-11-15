#!/usr/bin/env python3
"""Offline contract tests. All providers are fakes; NO production writes."""
import copy
import hashlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import connected_publication_coordinator as c


class Provider:
    def __init__(self):
        self.data = {}
        self.creates = []
        self.fail_once = None
        self.bad_readback = None

    def assert_ready(self, components):
        return {"status": "ALL_TARGETS_READ_WRITE_READY",
                "components": list(components),
                "actual_write_scopes_verified": True,
                "caller_single_writer_lease_attested": True}

    def read(self, component, article_id):
        row = self.data.get(component)
        if row is None:
            return None
        if component == self.bad_readback:
            return {"record": {"article_id": article_id, "wrong": True},
                    "evidence_ref": "mock://" + component}
        return {"record": copy.deepcopy(row),
                "evidence_ref": "mock://" + component}

    def create(self, component, record, expected_absent):
        assert expected_absent is True
        self.creates.append(component)
        if component in self.data:
            raise ValueError("PROVIDER_ALREADY_PRESENT")
        self.data[component] = copy.deepcopy(record)
        if component == self.fail_once:
            self.fail_once = None
            raise OSError("NETWORK_TIMEOUT_AFTER_WRITE")
        return {"mock": True}


def fixture():
    html = "<html><body>approved synthetic fixture</body></html>"
    digest = hashlib.sha256(html.encode()).hexdigest()
    plan = {
        "status": "READY_FOR_AUTHORIZED_DISPATCH",
        "article_id": "RI-999",
        "doi": "10.1000/synthetic-only",
        "approved_sha256": "a" * 64,
        "slug": "ri-999-synthetic.html",
        "url": "https://example.org/posts/ri-999-synthetic.html",
        "required_targets": [
            "posts/ri-999-synthetic.html", "index.html", "categories.html",
            "feed.xml", "sitemap.xml"],
    }
    return {
        "status": "CONNECTED_GITHUB_READONLY_PREFLIGHT_READY",
        "plan": plan,
        "lease": {"status": "READY_FOR_CONDITIONAL_WRITE_PRECHECK"},
        "bundle": {
            "status": "APPROVED_SITE_PAYLOAD_READY_NOT_PUBLISHED",
            "plan": copy.deepcopy(plan),
            "rendered": {},
            "contents": {path: html for path in plan["required_targets"]},
        }
    }


class ConnectedCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.prepared = fixture()
        self.provider = Provider()
        self.authorization = c.execution_authorization_value(self.prepared["plan"])
        self.gh_success = {"state": "GITHUB_WRITES_READBACK_PASS"}
        self.live_success = {"status": "LIVE_PUBLICATION_QA_PASS"}
        self.p1 = patch.object(c, "execute_prepared_github_release", return_value=self.gh_success)
        self.p2 = patch.object(c, "verify_prepared_live_release", return_value=self.live_success)
        self.gh = self.p1.start()
        self.live = self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    def invoke(self, **kwargs):
        return c.run_approved_connected_release(
            self.prepared, object(), self.authorization, self.provider,
            **kwargs)

    def test_no_id_private_psmart_cannot_release(self):
        outcome = c.private_candidate_preflight({"source": "P-SMART"})
        self.assertFalse(outcome["release_eligible"])
        self.assertFalse(outcome["public_write_performed"])

    def test_fake_approval_identifier_is_rejected_for_private_gate(self):
        with self.assertRaisesRegex(ValueError, "NOT_A_NO_ID_PRIVATE"):
            c.private_candidate_preflight({"article_id": "RI-999"})

    def test_no_approval_blocks_before_any_write(self):
        with self.assertRaisesRegex(ValueError, "ARTICLE_HASH_AUTHORIZATION"):
            c.run_approved_connected_release(
                self.prepared, object(), "NOT_AUTHORIZED", self.provider)
        self.gh.assert_not_called()
        self.assertFalse(self.provider.creates)

    def test_five_records_created_and_readback(self):
        report = self.invoke()
        self.assertEqual(report["status"], "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS")
        self.assertEqual(report["external_records_count"], 5)
        self.assertEqual(set(self.provider.creates), set(c.RECORD_COMPONENTS))
        self.assertFalse(report["publication_complete"])
        self.assertFalse(report["provider_authentication_independently_verified"])

    def test_repeat_does_not_duplicate_external_records(self):
        self.invoke()
        report = self.invoke(recover=True)
        self.assertEqual(len(self.provider.creates), 5)
        self.assertTrue(all(x["action"] == "ALREADY_PRESENT_VERIFIED"
                            for x in report["writeback"]))
        self.assertEqual(self.gh.call_args.kwargs["recover"], True)

    def test_timeout_after_commit_is_reconciled_on_reentry(self):
        self.provider.fail_once = "drive_published_copy"
        first = self.invoke()
        self.assertEqual(first["status"], "EXTERNAL_WRITEBACK_PARTIAL")
        self.assertEqual(first["blocker"], "drive_published_copy")
        self.assertEqual(len(first["writeback"]), 2)
        second = self.invoke(recover=True)
        self.assertEqual(second["status"], "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS")
        self.assertEqual(self.provider.creates.count("drive_published_copy"), 1)

    def test_conflicting_existing_record_fails_closed(self):
        self.provider.data["sheets_master"] = {
            "article_id": "RI-999", "approved_private_sha256": "bad"}
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_PREFLIGHT_BLOCKED")
        self.assertEqual(result["blocker"], "provider")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertFalse(self.provider.creates)

    def test_readback_mismatch_stops(self):
        self.provider.bad_readback = "sheets_master"
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_WRITEBACK_PARTIAL")
        self.assertEqual(result["blocker"], "sheets_master")

    def test_get_only_provider_cannot_authorize_github_write(self):
        self.provider.assert_ready = lambda components: {
            "status": "ALL_TARGETS_READ_WRITE_READY",
            "components": list(components),
            "actual_write_scopes_verified": False,
            "caller_single_writer_lease_attested": True}
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_PREFLIGHT_BLOCKED")
        self.gh.assert_not_called()

    def test_missing_single_writer_attestation_blocks_github(self):
        self.provider.assert_ready = lambda components: {
            "status": "ALL_TARGETS_READ_WRITE_READY",
            "components": list(components),
            "actual_write_scopes_verified": True,
            "caller_single_writer_lease_attested": False}
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_PREFLIGHT_BLOCKED")
        self.gh.assert_not_called()

    def test_provider_not_ready_blocks_before_github(self):
        self.provider.assert_ready = lambda _: {"status": "NOT_READY", "components": []}
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_PREFLIGHT_BLOCKED")
        self.assertFalse(result["public_write_attempted"])
        self.gh.assert_not_called()

    def test_provider_conflict_blocks_before_github(self):
        self.provider.data["sheets_master"] = {
            "article_id": "RI-999", "approved_private_sha256": "different"}
        result = self.invoke()
        self.assertEqual(result["status"], "EXTERNAL_PREFLIGHT_BLOCKED")
        self.gh.assert_not_called()
        self.assertFalse(self.provider.creates)

    def test_live_failure_stops_before_external_sync(self):
        self.live.return_value = {"status": "LIVE_HTTP_NETWORK_ERROR",
                                  "failed_path": "feed.xml"}
        result = self.invoke()
        self.assertEqual(result["status"], "LIVE_QA_BLOCKED")
        self.assertEqual(result["blocker"], "feed.xml")
        self.assertFalse(self.provider.creates)

    def test_github_partial_stops_before_live_and_sync(self):
        self.gh.return_value = {"state": "PARTIAL_WRITE_OUTCOME_UNKNOWN",
                                "blocker": "categories.html"}
        result = self.invoke()
        self.assertEqual(result["status"], "GITHUB_PARTIAL_OR_BLOCKED")
        self.live.assert_not_called()
        self.assertFalse(self.provider.creates)

    def test_github_exception_preserves_uncertain_outcome(self):
        self.gh.side_effect = OSError("network uncertain")
        report = self.invoke()
        self.assertEqual(report["status"], "GITHUB_OUTCOME_UNKNOWN")
        self.assertEqual(report["recovery_action"], "RECONCILE_GITHUB_BEFORE_RETRY")
        self.assertFalse(self.provider.creates)

    def test_live_exception_is_not_accepted(self):
        self.live.side_effect = OSError("network")
        result = self.invoke()
        self.assertEqual(result["status"], "LIVE_QA_UNKNOWN")
        self.assertFalse(self.provider.creates)

    def test_source_identity_lock(self):
        bad = fixture()
        bad["bundle"]["plan"]["approved_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "PREFLIGHT_PLAN_BUNDLE_MISMATCH"):
            c.run_approved_connected_release(
                bad, object(), self.authorization, self.provider)
        self.gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
