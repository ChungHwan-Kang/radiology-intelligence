import hashlib
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from publication_release_journal import (
    start_release_journal, record_external_readback, persist_private_journal, REQUIRED_RECORDS
)


class PublicationReleaseJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"private"/"release.json"
        self.body="<html><h1>synthetic code test</h1></html>"
        self.bodysha=hashlib.sha256(self.body.encode()).hexdigest()
        self.plan={"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":"RI-999",
                   "slug":"ri-999-synthetic.html","approved_sha256":"a"*64,
                   "required_targets":["posts/ri-999-synthetic.html","index.html",
                                       "categories.html","feed.xml","sitemap.xml"]}
        self.lease={"status":"READY_FOR_CONDITIONAL_WRITE_PRECHECK",
                    "article_id":"RI-999","approved_sha256":"a"*64,
                    "remote_sha_expectations":dict.fromkeys(self.plan["required_targets"],"b"*40),
                    "public_write_performed":False}
        self.html={"status":"PUBLIC_HTML_RENDERED_NOT_PUBLISHED","article_id":"RI-999",
                   "slug":"ri-999-synthetic.html","approved_private_sha256":"a"*64,
                   "public_html_sha256":self.bodysha,"html":self.body}

    def test_start_journal_never_claims_external_success(self):
        j=start_release_journal(self.plan,self.lease,self.html)
        self.assertEqual(j["status"],"RELEASE_NOT_STARTED")
        self.assertEqual(len(j["checks"]),len(REQUIRED_RECORDS))
        self.assertTrue(all(x=="NOT_OBSERVED" for x in j["checks"].values()))
        self.assertFalse(j["completion_claim_permitted"])
        self.assertFalse(j["public_write_performed_by_this_module"])

    def test_rejects_private_preview(self):
        self.html["html"]='<meta name="robots" content="noindex">'
        self.html["public_html_sha256"]=hashlib.sha256(self.html["html"].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,"PUBLIC_HTML_CONTAINS_PRIVATE_MARKERS"):
            start_release_journal(self.plan,self.lease,self.html)

    def test_rejects_mismatched_lease(self):
        self.lease["approved_sha256"]="c"*64
        with self.assertRaisesRegex(ValueError,"APPROVAL_LEASE_MISMATCH"):
            start_release_journal(self.plan,self.lease,self.html)

    def test_external_readback_is_reported_not_verified(self):
        j=start_release_journal(self.plan,self.lease,self.html)
        updated=record_external_readback(j,"github_post","f"*64,"f"*64,
                                         "private GitHub blob SHA/readback transcript")
        self.assertEqual(updated["checks"]["github_post"],"MATCH_REPORTED_BY_CALLER")
        self.assertEqual(updated["status"],"PARTIAL_READBACK_REPORTED")
        self.assertTrue(updated["external_execution_unverified"])
        self.assertFalse(updated["completion_claim_permitted"])
        self.assertEqual(j["checks"]["github_post"],"NOT_OBSERVED")
        self.assertEqual(record_external_readback(updated,"github_post","f"*64,"f"*64,
            "private GitHub blob SHA/readback transcript"),updated)

    def test_reject_mismatch_and_conflicting_retry(self):
        j=start_release_journal(self.plan,self.lease,self.html)
        with self.assertRaisesRegex(ValueError,"REMOTE_READBACK_MISMATCH"):
            record_external_readback(j,"github_post","a"*64,"b"*64,"test")
        x=record_external_readback(j,"github_post","a"*64,"a"*64,"test")
        with self.assertRaisesRegex(ValueError,"CONFLICTING_RETRY_RECEIPT"):
            record_external_readback(x,"github_post","a"*64,"a"*64,"different receipt")

    def test_refuses_existing_private_journal_overwrite(self):
        j=start_release_journal(self.plan,self.lease,self.html)
        persist_private_journal(self.path,j)
        with self.assertRaisesRegex(ValueError,"EXISTING_RELEASE_JOURNAL_PROTECTED"):
            persist_private_journal(self.path,j)
        self.assertTrue(self.path.is_file())

    def test_git_worktree_rejected(self):
        (self.path.parent/".git").mkdir(parents=True)
        j=start_release_journal(self.plan,self.lease,self.html)
        with self.assertRaisesRegex(ValueError,"PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY"):
            persist_private_journal(self.path,j)


if __name__=="__main__":
    unittest.main()
