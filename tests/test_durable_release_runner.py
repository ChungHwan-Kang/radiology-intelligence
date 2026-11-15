#!/usr/bin/env python3
"""Tests for durable release receipts. All data and publication are synthetic."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,os.path.join(os.path.dirname(__file__),"..","scripts"))
import durable_release_runner as d
import connected_publication_coordinator as c


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def journal(self):
        return d.PrivateReleaseJournal(self.root,"RI-999","a"*64)

    def test_first_chain_and_readback(self):
        with self.journal() as j:
            j.append("RESULT",{"status":"EXTERNAL_WRITEBACK_PARTIAL"})
            self.assertEqual([x["fields"]["event"] for x in j.entries()],
                             ["INITIALIZED","RESULT"])
        self.assertFalse(j.lock.exists())

    def test_reopen_valid_journal(self):
        with self.journal() as j:
            j.append("RESULT",{"status":"EXTERNAL_WRITEBACK_PARTIAL"})
        with self.journal() as j2:
            self.assertTrue(j2.preexisting)
            self.assertEqual(len(j2.entries()),2)

    def test_existing_lock_prevents_concurrent_entry(self):
        with self.journal():
            with self.assertRaisesRegex(d.JournalBlocked,"EXCLUSIVE_RELEASE_LOCK"):
                with self.journal():pass

    def test_tampering_detected(self):
        with self.journal() as j:
            j.append("RESULT",{"status":"EXTERNAL_WRITEBACK_PARTIAL"})
        p=self.journal().path
        p.write_text(p.read_text().replace("EXTERNAL_WRITEBACK_PARTIAL","SUCCESS"),
                     encoding="utf-8")
        with self.assertRaisesRegex(d.JournalBlocked,"JOURNAL_TAMPER"):
            with self.journal():pass

    def test_git_directory_rejected(self):
        (self.root/".git").mkdir()
        with self.assertRaisesRegex(d.JournalBlocked,"INSIDE_GIT"):
            self.journal()

    def test_no_approval_blocks_before_journal(self):
        from test_connected_publication_coordinator import fixture, Provider
        prepared=fixture()
        with self.assertRaisesRegex(d.JournalBlocked,"ARTICLE_SPECIFIC_HASH_AUTHORIZATION"):
            d.run_durably(prepared,object(),"NOT_APPROVED",
                           Provider(),self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_release_failure_is_durable_and_requires_recovery(self):
        from test_connected_publication_coordinator import fixture, Provider
        prepared=fixture()
        auth=c.execution_authorization_value(prepared["plan"])
        provider=Provider()
        with patch.object(d,"run_approved_connected_release",return_value={
            "status":"EXTERNAL_WRITEBACK_PARTIAL","blocker":"notion"}) as mocked:
            first=d.run_durably(prepared,object(),auth,provider,self.root)
            self.assertEqual(first["status"],"EXTERNAL_WRITEBACK_PARTIAL")
            self.assertTrue(first["durable_result_saved"])
            self.assertFalse(provider.local_lock_held)
            second=d.run_durably(prepared,object(),auth,provider,self.root)
            self.assertEqual(second["status"],"EXPLICIT_RECOVERY_REQUIRED")
            self.assertEqual(mocked.call_count,1)
            third=d.run_durably(prepared,object(),auth,provider,self.root,recover=True)
            self.assertEqual(third["status"],"EXTERNAL_WRITEBACK_PARTIAL")
            self.assertEqual(mocked.call_count,2)
            self.assertTrue(mocked.call_args.kwargs["recover"])
            self.assertFalse(provider.local_lock_held)

    def test_finished_release_cannot_repeat_without_manual_check(self):
        from test_connected_publication_coordinator import fixture, Provider
        prepared=fixture()
        auth=c.execution_authorization_value(prepared["plan"])
        provider=Provider()
        with patch.object(d,"run_approved_connected_release",return_value={
            "status":"ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS"}) as mocked:
            d.run_durably(prepared,object(),auth,provider,self.root)
            again=d.run_durably(prepared,object(),auth,provider,self.root,recover=True)
            self.assertEqual(again["status"],"ALREADY_COMPLETED_MANUAL_VERIFY")
            self.assertEqual(mocked.call_count,1)

    def test_write_disabled_is_still_disabled(self):
        from test_connected_publication_coordinator import fixture, Provider
        prepared=fixture()
        auth=c.execution_authorization_value(prepared["plan"])
        provider=Provider()
        provider.write_enabled=False
        provider.exclusive=False
        with patch.object(d,"run_approved_connected_release",return_value={
            "status":"EXTERNAL_PREFLIGHT_BLOCKED"}) as mocked:
            out=d.run_durably(prepared,object(),auth,provider,self.root)
            self.assertEqual(out["status"],"EXTERNAL_PREFLIGHT_BLOCKED")
            self.assertFalse(provider.local_lock_held)
            self.assertFalse(provider.write_enabled)


if __name__=="__main__":
    unittest.main()
