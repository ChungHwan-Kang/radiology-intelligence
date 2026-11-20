"""Synthetic verification of GitHub-first publication and isolated provider retry.

No network, real credentials, user article or Published fixture is used.
"""
import tempfile
import unittest
from urllib.parse import urlsplit

from authorized_github_dispatch import execution_authorization_value
from connected_publication_coordinator import RECORD_COMPONENTS
from native_provider_writeback import NativeProviderAdapter, SHEET_ID
from site_first_release import release_site, sync_records, SiteFirstBlocked
from test_connected_release_end_to_end import ConnectedReleaseEndToEndTests
from test_native_provider_writeback import (
    FakeNativeHTTP, metadata, research_source, write_scope_attestation,
)


class SiteFirstReleaseTests(unittest.TestCase):
    def setUp(self):
        self.prepared, self.github, self.contents, self.article = (
            ConnectedReleaseEndToEndTests()._prepared()
        )
        plan = self.prepared["plan"]
        self.prepared["native_sheets_duplicate_guard"] = {
            "status": "CALLER_NATIVE_SHEETS_DUPLICATE_GUARD_PASS",
            "article_id": plan["article_id"],
            "doi": plan["doi"],
            "source_contract": research_source(),
            "record_components": list(RECORD_COMPONENTS),
        }
        self.prepared["native_provider_read_receipt"] = {"spreadsheet_id": SHEET_ID}
        self.auth = execution_authorization_value(plan)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fetch(self, url):
        path = urlsplit(url).path
        hits = [body for key, body in self.contents.items() if path.endswith(key)]
        return (200, hits[0]) if len(hits) == 1 else (404, "")

    def fresh(self):
        return dict(self.prepared["native_sheets_duplicate_guard"])

    def release(self, **kwargs):
        return release_site(self.prepared, self.github, self.auth, self.tmp.name,
                            fresh_duplicate_check=self.fresh, fetch=self.fetch, **kwargs)

    def provider(self, api=None, **kwargs):
        return NativeProviderAdapter(
            api or FakeNativeHTTP(), metadata(), self.article,
            write_enabled=kwargs.get("write_enabled", True),
            exclusive_writer_attested=kwargs.get("single_writer", True),
            write_scope_attestation=write_scope_attestation(),
            source_contract=research_source(),
            record_components=RECORD_COMPONENTS)

    def test_github_live_pass_without_provider_mutation(self):
        result = self.release()
        self.assertEqual(result["status"], "PUBLISHED_SYNC_PENDING")
        self.assertTrue(result["publication_complete"])
        self.assertFalse(result["sync_complete"])
        self.assertEqual(self.github.writes, self.prepared["plan"]["required_targets"])
        again = self.release()
        self.assertEqual(again["status"], "ALREADY_PUBLISHED_SYNC_PENDING")
        self.assertEqual(len(self.github.writes), 5)

    def test_gate_fails_closed_without_source_recheck(self):
        with self.assertRaisesRegex(SiteFirstBlocked, "FRESH_NATIVE"):
            release_site(self.prepared, self.github, self.auth, self.tmp.name,
                         fresh_duplicate_check=None, fetch=self.fetch)
        self.assertEqual(self.github.writes, [])

    def test_stale_source_or_wrong_approval_blocks_publication(self):
        with self.assertRaisesRegex(SiteFirstBlocked, "ARTICLE_SHA"):
            release_site(self.prepared, self.github, "fake", self.tmp.name,
                         fresh_duplicate_check=self.fresh, fetch=self.fetch)
        with self.assertRaisesRegex(SiteFirstBlocked, "RECHECK_FAILED"):
            release_site(self.prepared, self.github, self.auth, self.tmp.name,
                         fresh_duplicate_check=lambda: {"status": "UNVERIFIED"},
                         fetch=self.fetch)
        self.assertEqual(self.github.writes, [])

    def test_live_failure_requires_explicit_recovery(self):
        result = release_site(self.prepared, self.github, self.auth, self.tmp.name,
                              fresh_duplicate_check=self.fresh,
                              fetch=lambda _: (404, ""))
        self.assertEqual(result["status"], "LIVE_QA_PENDING")
        self.assertEqual(len(self.github.writes), 5)
        blocked = self.release()
        self.assertEqual(blocked["status"], "EXPLICIT_RECOVERY_REQUIRED")
        resumed = self.release(recover=True)
        self.assertEqual(resumed["status"], "PUBLISHED_SYNC_PENDING")
        self.assertEqual(len(self.github.writes), 5)

    def test_sync_requires_successful_site_result_and_real_provider_gate(self):
        api = FakeNativeHTTP()
        provider = self.provider(api)
        with self.assertRaisesRegex(SiteFirstBlocked, "VERIFIED_SITE"):
            sync_records(self.prepared, self.github, self.auth, provider,
                         self.tmp.name, fetch=self.fetch)
        self.assertEqual(api.writes, [])

    def test_sync_gate_rejects_provider_without_actual_external_lock(self):
        self.release()
        api = FakeNativeHTTP()
        provider = self.provider(api, single_writer=False)
        with self.assertRaisesRegex(ValueError, "EXTERNAL_SINGLE_WRITER_LEASE_REQUIRED"):
            sync_records(self.prepared, self.github, self.auth, provider,
                         self.tmp.name, fetch=self.fetch)
        self.assertEqual(api.writes, [])

    def test_provider_sync_retry_not_republish_github(self):
        self.release()
        api = FakeNativeHTTP()
        fail = [True]
        old = api.call
        def timeout_after_notion(provider, method, path, *args, **kwargs):
            out = old(provider, method, path, *args, **kwargs)
            if fail[0] and provider == "notion" and method == "PATCH":
                fail[0] = False
                raise TimeoutError("synthetic response loss")
            return out
        api.call = timeout_after_notion
        provider = self.provider(api)
        initial = sync_records(self.prepared, self.github, self.auth, provider,
                               self.tmp.name, fetch=self.fetch)
        self.assertEqual(initial["status"], "SYNC_PENDING_RETRY")
        self.assertEqual(len(self.github.writes), 5)
        once = len(api.writes)
        retry = sync_records(self.prepared, self.github, self.auth, provider,
                             self.tmp.name, fetch=self.fetch)
        self.assertEqual(retry["status"], "PUBLISHED_SYNC_DONE")
        self.assertEqual(len(api.writes), once)
        again = sync_records(self.prepared, self.github, self.auth, provider,
                             self.tmp.name, fetch=self.fetch)
        self.assertEqual(again["status"], "SYNC_ALREADY_DONE")
        self.assertEqual(len(api.writes), once)
        self.assertEqual(len(self.github.writes), 5)


if __name__ == "__main__":
    unittest.main()
