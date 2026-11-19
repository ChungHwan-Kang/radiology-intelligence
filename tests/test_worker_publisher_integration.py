"""Worker-to-existing-publisher integration with synthetic providers only."""
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from approval_event_contract import approval_binding
from approval_worker import Inbox, run_once
from authorized_github_dispatch import execution_authorization_value
from durable_release_runner import run_durably
from native_provider_writeback import NativeProviderAdapter
import test_connected_release_end_to_end as release_fixtures
from test_native_provider_writeback import FakeNativeHTTP, metadata, write_scope_attestation


class WorkerPublisherIntegrationTests(unittest.TestCase):
    def test_partial_provider_commit_worker_restart_and_handoff(self):
        prepared, github, contents, html = release_fixtures.ConnectedReleaseEndToEndTests()._prepared()
        plan = prepared["plan"]
        identity = dict(article_id=plan["article_id"], doi=plan["doi"],
                        review_sha256=plan["approved_sha256"],
                        source_contract=prepared["source_contract"],
                        components=prepared["record_components"])
        now = datetime.fromisoformat("2026-11-19T12:00:00+09:00")
        event = dict(identity, version=1, event_id="d" * 32,
                     action="APPROVE_PUBLICATION", binding_sha256=approval_binding(**identity),
                     reviewer="synthetic-local-user", approval_ref="synthetic-user-confirmation",
                     approved_at=now.isoformat(), expires_at=(now + timedelta(minutes=5)).isoformat())
        api = FakeNativeHTTP()
        original_call = api.call
        failure = [True]

        def commit_then_timeout(provider, method, path, *args, **kwargs):
            result = original_call(provider, method, path, *args, **kwargs)
            if provider == "notion" and method == "PATCH" and failure[0]:
                failure[0] = False
                raise TimeoutError("synthetic post-commit loss")
            return result

        api.call = commit_then_timeout
        provider = NativeProviderAdapter(
            api, metadata(), html, write_enabled=True, exclusive_writer_attested=True,
            write_scope_attestation=write_scope_attestation(),
            source_contract=prepared["source_contract"], record_components=prepared["record_components"])

        def fetch(url):
            path = urlsplit(url).path.lstrip("/")
            matches = [body for target, body in contents.items() if path.endswith(target)]
            self.assertEqual(len(matches), 1)
            return 200, matches[0]

        calls = []
        with TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = Inbox(root / "inbox.sqlite")
            inbox.accept(event, identity, now=now, recovery_allowed=True, human_origin={
                "kind": "WINDOWS_DIRECT", "binding": event["binding_sha256"],
                "actor": event["reviewer"], "reference": event["approval_ref"],
            })

            def publish(accepted, *, recover):
                self.assertEqual(accepted, event)
                calls.append(recover)
                return run_durably(
                    prepared, github, execution_authorization_value(plan), provider,
                    root / "journal", fetch=fetch, recover=recover)

            def execute(recovery, when):
                return run_once(
                    inbox, event["event_id"], identity, now=when,
                    writer_guard=lambda *_: nullcontext(), publish=publish,
                    revoked=False, recovery=recovery)

            self.assertEqual(execute(False, now), "PARTIAL")
            self.assertEqual(len(github.writes), 5)
            self.assertEqual(len(api.writes), 5)
            inbox = Inbox(root / "inbox.sqlite")
            self.assertEqual(execute(True, now + timedelta(hours=1)), "DONE")
            self.assertEqual(len(github.writes), 5)
            self.assertEqual(len(api.writes), 5)
            self.assertEqual(execute(False, now + timedelta(hours=2)), "ALREADY_COMPLETED")
            self.assertEqual(calls, [False, True])
            self.assertFalse(inbox.continue_candidate(event["event_id"], lambda _: False))
            self.assertTrue(inbox.continue_candidate(event["event_id"], lambda _: True))
            self.assertEqual(calls, [False, True])

    def test_missing_external_guard_blocks_before_publisher(self):
        from approval_event_contract import ApprovalEventBlocked
        def blocked_guard(*_):
            raise ApprovalEventBlocked("EXTERNAL_WRITERS_NOT_EXCLUDED")
        with self.assertRaisesRegex(ApprovalEventBlocked, "EXTERNAL_WRITERS"):
            run_once(None, "synthetic", {}, now=None, writer_guard=blocked_guard,
                     publish=lambda *_: self.fail("Publisher called without guard"), revoked=False)
