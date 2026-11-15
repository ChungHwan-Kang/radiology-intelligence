import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))

from live_publication_verifier import verify_live_publication


class LivePublicationVerifierTests(unittest.TestCase):
    def setUp(self):
        self.slug="ri-999-synthetic.html"
        self.paths=["posts/"+self.slug,"index.html","categories.html","feed.xml","sitemap.xml"]
        self.plan={"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":"RI-999",
                   "slug":self.slug,"required_targets":self.paths}
        url="https://example.test/posts/"+self.slug
        self.contents={
            self.paths[0]:"<html>published</html>",
            "index.html":"<a href=\"posts/"+self.slug+"\">article</a>",
            "categories.html":"<a href=\"posts/"+self.slug+"\">article</a>",
            "feed.xml":"<rss><channel><item><link>"+url+"</link></item></channel></rss>",
            "sitemap.xml":'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+url+"</loc></url></urlset>",
        }
    def fetch(self,url):
        path=url.removeprefix("https://example.test/")
        return 200,self.contents[path]
    def test_all_five_public_targets_pass(self):
        result=verify_live_publication(self.plan,self.contents,self.fetch,"https://example.test/")
        self.assertEqual(result["status"],"LIVE_PUBLICATION_QA_PASS")
        self.assertEqual(len(result["checks"]),5)
        self.assertTrue(result["live_http_verified"])
        self.assertFalse(result["publication_complete"])
    def test_network_error_is_distinct(self):
        def broken(url): raise ConnectionError("offline")
        result=verify_live_publication(self.plan,self.contents,broken,"https://example.test/")
        self.assertEqual(result["status"],"LIVE_HTTP_NETWORK_ERROR")
        self.assertEqual(result["error_type"],"ConnectionError")
    def test_http_status_error_is_distinct(self):
        result=verify_live_publication(
            self.plan,self.contents,lambda url:(503,"unavailable"),"https://example.test/")
        self.assertEqual(result["status"],"LIVE_HTTP_STATUS_ERROR")
        self.assertEqual(result["http_status"],503)
    def test_content_mismatch_is_distinct(self):
        def changed(url):
            status,body=self.fetch(url)
            return status,(body+" changed" if url.endswith("index.html") else body)
        result=verify_live_publication(self.plan,self.contents,changed,"https://example.test/")
        self.assertEqual(result["status"],"LIVE_CONTENT_VALIDATION_FAILED")
        self.assertEqual(result["failed_path"],"index.html")


if __name__=="__main__": unittest.main()
