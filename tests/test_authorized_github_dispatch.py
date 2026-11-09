import hashlib
import unittest
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from authorized_github_dispatch import dispatch_github_approved,DispatchBlocked


class FakeGitHub:
    def __init__(self,paths):
        self.shas={path:("a"*40 if i else None) for i,path in enumerate(paths)}
        self.files={path:"" for path in paths}
        self.calls=[]
    def read(self,path):
        self.calls.append(("read",path))
        return self.shas[path]
    def write(self,path,content,expected_sha):
        self.calls.append(("write",path))
        if self.shas[path]!=expected_sha:
            raise RuntimeError("conflict")
        self.files[path]=content
        self.shas[path]="b"*40
        return self.shas[path]
    def read_content(self,path):
        self.calls.append(("readback",path))
        return self.files[path]


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.paths=["posts/ri-999-synthetic.html","index.html","categories.html","feed.xml","sitemap.xml"]
        self.post="<html>Approved synthetic test</html>"
        self.plan={"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":"RI-999",
                   "slug":"ri-999-synthetic.html","approved_sha256":"f"*64,
                   "required_targets":self.paths}
        self.git=FakeGitHub(self.paths)
        self.lease={"status":"READY_FOR_CONDITIONAL_WRITE_PRECHECK","article_id":"RI-999",
                    "approved_sha256":"f"*64,
                    "remote_sha_expectations":dict(self.git.shas)}
        self.render={"status":"PUBLIC_HTML_RENDERED_NOT_PUBLISHED","article_id":"RI-999",
                     "approved_private_sha256":"f"*64,"html":self.post,
                     "public_html_sha256":hashlib.sha256(self.post.encode()).hexdigest()}
        self.payload={path:(self.post if i==0 else "<test>ri-999-synthetic.html</test>")
                      for i,path in enumerate(self.paths)}
        self.token="EXECUTE_ARTICLE_SPECIFIC_APPROVED_DISPATCH"
    def run_dispatch(self):
        return dispatch_github_approved(self.plan,self.lease,self.render,self.payload,self.git,self.token)
    def test_no_execution_without_token(self):
        with self.assertRaisesRegex(DispatchBlocked,"EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED"):
            dispatch_github_approved(self.plan,self.lease,self.render,self.payload,self.git,None)
        self.assertFalse(self.git.calls)
    def test_no_execution_when_preview_is_not_public(self):
        self.payload[self.paths[0]]='<meta name="robots" content="noindex">'
        with self.assertRaises(DispatchBlocked):
            self.run_dispatch()
        self.assertFalse(self.git.calls)
    def test_no_execution_when_article_identity_mismatched(self):
        self.lease["article_id"]="RI-998"
        with self.assertRaisesRegex(DispatchBlocked,"ARTICLE_ID_LOCK_MISMATCH"):
            self.run_dispatch()
        self.assertFalse(self.git.calls)
    def test_remote_change_blocks_all_writes(self):
        self.git.shas["feed.xml"]="e"*40
        r=self.run_dispatch()
        self.assertEqual(r["state"],"BLOCKED_REMOTE_CHANGED")
        self.assertFalse(any(c[0]=="write" for c in self.git.calls))
    def test_missing_site_reference_blocks_all_writes(self):
        self.payload["sitemap.xml"]="<sitemap/>"
        with self.assertRaisesRegex(DispatchBlocked,"MISSING_ARTICLE_LINK"):
            self.run_dispatch()
        self.assertFalse(self.git.calls)
    def test_reads_every_target_before_writing(self):
        r=self.run_dispatch()
        self.assertEqual(r["state"],"GITHUB_WRITES_READBACK_PASS")
        self.assertEqual(len(r["writes"]),5)
        self.assertEqual([x[0] for x in self.git.calls[:5]],["read"]*5)
        self.assertFalse(r["publication_complete"])
        self.assertEqual(r["external_system_sync"],"PENDING_SHEETS_DRIVE_NOTION")
    def test_ambiguous_api_exception_is_partial_and_requires_reconciliation(self):
        original=self.git.write
        def ambiguous_write(path,content,sha):
            if path=="index.html":
                # Emulates a GitHub write being committed before lost response.
                original(path,content,sha)
                raise ConnectionError("response lost")
            return original(path,content,sha)
        self.git.write=ambiguous_write
        result=self.run_dispatch()
        self.assertEqual(result["state"],"PARTIAL_WRITE_OUTCOME_UNKNOWN")
        self.assertEqual(result["blocker"],"index.html")
        self.assertEqual(result["recovery_action"],"REFETCH_REMOTE_AND_RECONCILE_BEFORE_RETRY")
        self.assertEqual(len(result["writes"]),1)
        self.assertFalse(result["publication_complete"])
        self.assertNotIn(("write","categories.html"),self.git.calls)

    def test_readback_mismatch_is_partial_not_published(self):
        original=self.git.read_content
        def bad(path):
            return "tampered" if path=="index.html" else original(path)
        self.git.read_content=bad
        r=self.run_dispatch()
        self.assertEqual(r["state"],"PARTIAL_READBACK_MISMATCH")
        self.assertEqual(r["blocker"],"index.html")
        self.assertEqual(len(r["writes"]),1)
        self.assertFalse(r["publication_complete"])


if __name__=="__main__":
    unittest.main()
