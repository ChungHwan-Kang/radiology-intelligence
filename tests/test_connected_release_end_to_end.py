#!/usr/bin/env python3
"""Synthetic executable integration; every remote system is in-memory."""
import hashlib
import tempfile
import unittest
from urllib.parse import urlsplit

from test_approved_publication_runtime import MemoryGitHub
from test_native_provider_writeback import (
    FakeNativeHTTP, metadata, write_scope_attestation,
)

import connected_publication_coordinator as coordinator
import durable_release_runner as durable
import native_provider_writeback as native
from authorized_github_dispatch import execution_authorization_value


class ConnectedReleaseEndToEndTests(unittest.TestCase):
    def _prepared(self):
        canonical = metadata()
        slug = canonical["slug"]
        paths = ["posts/" + slug, "index.html", "categories.html",
                 "feed.xml", "sitemap.xml"]
        article = "<html><body>approved synthetic fixture</body></html>"
        contents = {
            paths[0]: article,
            paths[1]: "published " + slug,
            paths[2]: "published " + slug,
            paths[3]: "<rss><channel><item><link>" + slug +
                      "</link></item></channel></rss>",
            paths[4]: ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                       "<url><loc>" + slug + "</loc></url></urlset>"),
        }
        plan = {"status": "READY_FOR_AUTHORIZED_DISPATCH",
                "article_id": "RI-999", "doi": canonical["doi"],
                "slug": slug, "url": canonical["published_url"],
                "approved_sha256": "a" * 64, "required_targets": paths}
        github = MemoryGitHub(paths)
        lease = {"status": "READY_FOR_CONDITIONAL_WRITE_PRECHECK",
                 "article_id": plan["article_id"],
                 "approved_sha256": plan["approved_sha256"],
                 "remote_sha_expectations": {p: github.read(p) for p in paths}}
        rendered = {"status": "PUBLIC_HTML_RENDERED_NOT_PUBLISHED",
                    "article_id": plan["article_id"],
                    "approved_private_sha256": plan["approved_sha256"],
                    "html": article,
                    "public_html_sha256": hashlib.sha256(article.encode()).hexdigest()}
        prepared = {"status": "CONNECTED_GITHUB_READONLY_PREFLIGHT_READY",
                    "plan": plan, "lease": lease,
                    "source_contract":{"source_kind":"research_watch",
                                       "source_watch_doi":plan["doi"]},
                    "record_components":list(native.RECORD_COMPONENTS),
                    "bundle": {"status": "APPROVED_SITE_PAYLOAD_READY_NOT_PUBLISHED",
                               "plan": plan, "rendered": rendered,
                               "contents": contents}}
        return prepared, github, contents, article

    def test_all_gates_five_github_targets_live_qa_and_native_readbacks(self):
        prepared, github, contents, article = self._prepared()
        api = FakeNativeHTTP()
        provider = native.NativeProviderAdapter(
            api, metadata(), article, write_enabled=True,
            exclusive_writer_attested=True,
            write_scope_attestation=write_scope_attestation(),
            source_contract={"source_kind":"research_watch",
                             "source_watch_doi":prepared["plan"]["doi"]},
            record_components=native.RECORD_COMPONENTS)

        def fetch(url):
            public_path = urlsplit(url).path.lstrip("/")
            matching = [body for path, body in contents.items()
                        if public_path.endswith(path)]
            if len(matching) != 1:
                raise KeyError(public_path)
            return 200, matching[0]

        with tempfile.TemporaryDirectory() as journal:
            result = durable.run_durably(
                prepared, github,
                execution_authorization_value(prepared["plan"]), provider,
                journal, fetch=fetch)
            self.assertEqual(result["status"],
                             "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS", result)
            self.assertTrue(result["durable_result_saved"])
            self.assertEqual(github.writes, prepared["plan"]["required_targets"])
            self.assertEqual(len(api.writes), 5)
            self.assertFalse(provider.local_lock_held)

            recovered = durable.run_durably(
                prepared, github,
                execution_authorization_value(prepared["plan"]), provider,
                journal, fetch=fetch, recover=True)
            self.assertEqual(recovered["status"],
                             "ALREADY_COMPLETED_MANUAL_VERIFY")
            self.assertEqual(len(api.writes), 5)

    def test_psmart_remains_private_without_id_or_public_write(self):
        result = coordinator.private_candidate_preflight({
            "source": "P-SMART",
            "doi": "10.1186/s13244-026-02459-2",
            "source_qa_status": "PRIVATE_VERIFIED_CANDIDATE",
        })
        self.assertFalse(result["release_eligible"])
        self.assertFalse(result["public_write_performed"])


if __name__ == "__main__":
    unittest.main()
