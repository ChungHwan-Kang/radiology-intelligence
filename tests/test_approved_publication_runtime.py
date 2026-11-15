import hashlib
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))

from approved_publication_runtime import (
    execute_prepared_github_release,verify_prepared_live_release,
)
from authorized_github_dispatch import execution_authorization_value


def blob(content):
    raw=content.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


class MemoryGitHub:
    def __init__(self,paths):
        self.files={path:"" for path in paths[1:]}
        self.writes=[]
    def read(self,path): return blob(self.files[path]) if path in self.files else None
    def read_content(self,path): return self.files[path]
    def write(self,path,content,expected):
        if self.read(path)!=expected: raise RuntimeError("conflict")
        self.files[path]=content
        self.writes.append(path)
        return blob(content)


class ApprovedPublicationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.slug="ri-999-synthetic.html"
        self.paths=["posts/"+self.slug,"index.html","categories.html","feed.xml","sitemap.xml"]
        self.article="<html>approved article</html>"
        self.contents={
            self.paths[0]:self.article,
            "index.html":"published "+self.slug,
            "categories.html":"published "+self.slug,
            "feed.xml":"<rss><channel><item><link>"+self.slug+"</link></item></channel></rss>",
            "sitemap.xml":'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+self.slug+"</loc></url></urlset>",
        }
        self.plan={"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":"RI-999",
                   "slug":self.slug,"approved_sha256":"a"*64,"required_targets":self.paths}
        self.git=MemoryGitHub(self.paths)
        self.lease={"status":"READY_FOR_CONDITIONAL_WRITE_PRECHECK","article_id":"RI-999",
                    "approved_sha256":"a"*64,
                    "remote_sha_expectations":{path:self.git.read(path) for path in self.paths}}
        self.rendered={"status":"PUBLIC_HTML_RENDERED_NOT_PUBLISHED","article_id":"RI-999",
                       "approved_private_sha256":"a"*64,"html":self.article,
                       "public_html_sha256":hashlib.sha256(self.article.encode()).hexdigest()}
        self.bundle={"status":"APPROVED_SITE_PAYLOAD_READY_NOT_PUBLISHED",
                     "plan":self.plan,"rendered":self.rendered,"contents":self.contents}
        self.prepared={"status":"CONNECTED_GITHUB_READONLY_PREFLIGHT_READY",
                       "plan":self.plan,"lease":self.lease,"bundle":self.bundle}
        self.authorization=execution_authorization_value(self.plan)
    def test_prepared_release_connects_approval_lease_and_five_writes(self):
        result=execute_prepared_github_release(
            self.prepared,self.git,self.authorization)
        self.assertEqual(result["state"],"GITHUB_WRITES_READBACK_PASS")
        self.assertEqual(self.git.writes,self.paths)
    def test_live_qa_requires_github_readback_pass(self):
        with self.assertRaisesRegex(ValueError,"GITHUB_TARGET_READBACK_PASS_REQUIRED"):
            verify_prepared_live_release(self.prepared,{"state":"PARTIAL_WRITE_OUTCOME_UNKNOWN"})
    def test_live_qa_uses_exact_prepared_payload(self):
        for path,body in self.contents.items(): self.git.files[path]=body
        def fetch(url):
            return 200,self.contents[url.removeprefix("https://example.test/")]
        result=verify_prepared_live_release(
            self.prepared,{"state":"GITHUB_WRITES_READBACK_PASS"},fetch,
            base_url="https://example.test/")
        self.assertEqual(result["status"],"LIVE_PUBLICATION_QA_PASS")


if __name__=="__main__": unittest.main()
