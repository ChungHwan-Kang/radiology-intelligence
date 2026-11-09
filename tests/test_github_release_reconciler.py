import hashlib
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from github_release_reconciler import reconcile_github_release


def blob(content):
    b=content.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()


class ActualBlobStore:
    def __init__(self,files):
        self.files=dict(files)
        self.writes=0
        self.conflict_after_read=None
        self.read_count={}
    def read(self,path):
        self.read_count[path]=self.read_count.get(path,0)+1
        if self.conflict_after_read==path and self.read_count[path]==2:
            self.files[path]+=" externally modified"
        return blob(self.files[path]) if path in self.files else None
    def read_content(self,path):
        return self.files[path]
    def write(self,*args):
        self.writes+=1
        raise AssertionError("reconciler must never call write")


class ReleaseReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.paths=["posts/ri-999-only-synthetic.html","index.html",
                    "categories.html","feed.xml","sitemap.xml"]
        self.before={
            "index.html":"Old index",
            "categories.html":"Old categories",
            "feed.xml":"Old RSS",
            "sitemap.xml":"Old sitemap"
        }
        self.new={
            "posts/ri-999-only-synthetic.html":"<html>Approved synthetic only</html>",
            **{p:("Updated "+p+" ri-999-only-synthetic.html") for p in self.paths[1:]}
        }
        self.plan={"status":"READY_FOR_AUTHORIZED_DISPATCH",
                   "article_id":"RI-999","slug":"ri-999-only-synthetic.html",
                   "approved_sha256":"a"*64,"required_targets":self.paths}
        self.lease={"status":"READY_FOR_CONDITIONAL_WRITE_PRECHECK",
                    "article_id":"RI-999","approved_sha256":"a"*64,
                    "remote_sha_expectations":{p:blob(self.before[p]) if p in self.before else None for p in self.paths}}
        self.remote=ActualBlobStore(self.before)
    def reconcile(self):
        return reconcile_github_release(self.plan,self.lease,self.new,self.remote)
    def test_untouched_originals_dont_claim_publication(self):
        r=self.reconcile()
        self.assertEqual(r["status"],"NO_GITHUB_TARGETS_UPDATED")
        self.assertTrue(all(s=="UNCHANGED_FROM_PREPUBLICATION" for s in r["paths"].values()))
        self.assertFalse(r["publication_complete"])
        self.assertFalse(r["auto_retry_permitted"])
        self.assertEqual(self.remote.writes,0)
    def test_partial_success_detects_exact_files_and_prevents_retry(self):
        self.remote.files["posts/ri-999-only-synthetic.html"]=self.new["posts/ri-999-only-synthetic.html"]
        self.remote.files["index.html"]=self.new["index.html"]
        r=self.reconcile()
        self.assertEqual(r["status"],"PARTIAL_GITHUB_TARGETS_PRESENT")
        self.assertEqual(r["paths"]["index.html"],"EXPECTED_NEW_CONTENT_PRESENT")
        self.assertEqual(r["paths"]["feed.xml"],"UNCHANGED_FROM_PREPUBLICATION")
        self.assertFalse(r["auto_retry_permitted"])
        self.assertFalse(r["publication_complete"])
    def test_five_present_still_doesnt_claim_external_sync(self):
        self.remote.files=dict(self.new)
        r=self.reconcile()
        self.assertEqual(r["status"],"GITHUB_TARGETS_READBACK_MATCH")
        self.assertTrue(r["github_target_readbacks_match"])
        self.assertFalse(r["publication_complete"])
        self.assertFalse(r["live_http_verified"])
        self.assertFalse(r["sheets_drive_notion_sync_verified"])
    def test_unexpected_remote_change_requires_manual_review(self):
        self.remote.files["feed.xml"]="A completely different concurrent RSS file"
        r=self.reconcile()
        self.assertEqual(r["status"],"MANUAL_CONFLICT_REVIEW_REQUIRED")
        self.assertEqual(r["conflicts"],["feed.xml"])
        self.assertFalse(r["auto_retry_permitted"])
    def test_changed_during_read_fails_closed(self):
        self.remote.conflict_after_read="feed.xml"
        with self.assertRaisesRegex(ValueError,"REMOTE_CHANGED_DURING_RECONCILIATION:feed.xml"):
            self.reconcile()
        self.assertEqual(self.remote.writes,0)
    def test_payload_and_approval_lock_mismatch_refused_without_remote_read(self):
        self.lease["approved_sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"APPROVAL_LEASE_MISMATCH"):
            self.reconcile()
        self.assertFalse(self.remote.read_count)
        self.lease["approved_sha256"]="a"*64
        self.new["index.html"]="No link"
        with self.assertRaisesRegex(ValueError,"MISSING_RELEASE_LINK"):
            self.reconcile()
        self.assertFalse(self.remote.read_count)
    def test_readback_blob_mismatch_fails_closed(self):
        base=self.remote.read
        def corrupt(path):
            return "f"*40 if path=="index.html" else base(path)
        self.remote.read=corrupt
        with self.assertRaisesRegex(ValueError,"GITHUB_BLOB_SHA_CONTENT_MISMATCH:index.html"):
            self.reconcile()
        self.assertEqual(self.remote.writes,0)


if __name__=="__main__": unittest.main()
