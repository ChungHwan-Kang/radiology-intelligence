import base64
import hashlib
import unittest
import sys
from pathlib import Path
from urllib.parse import urlsplit,unquote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from github_contents_adapter import GitHubContentsAdapter,GitHubContentsError,build_authenticated_transport


def blob_sha(data):
    raw=data.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


class FakeContentsAPI:
    def __init__(self):
        self.files={"index.html":"Original published index"}
        self.calls=[]
        self.raise_after_write=False
        self.force_conflict=False
    def __call__(self,method,url,payload):
        path=unquote(urlsplit(url).path.split("/contents/",1)[1])
        self.calls.append((method,path,payload))
        if method=="GET":
            if path not in self.files:
                return 404,{}
            data=self.files[path]
            return 200,{"type":"file","sha":blob_sha(data),"encoding":"base64",
                        "content":base64.b64encode(data.encode()).decode()}
        if method=="PUT":
            expected=payload.get("sha")
            current=blob_sha(self.files[path]) if path in self.files else None
            if self.force_conflict or current!=expected:
                return 409,{}
            text=base64.b64decode(payload["content"]).decode("utf-8")
            self.files[path]=text
            if self.raise_after_write:
                raise ConnectionError("response lost after commit")
            return (200 if expected else 201),{"content":{"sha":blob_sha(text)}}
        return 405,{}


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeContentsAPI()
        self.adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api)
    def test_git_blob_sha_matches_known_git_object(self):
        self.assertEqual(blob_sha("hello\\n"),"ce013625030ba8dba906f756967f9e9ca394464a")

    def test_real_contents_schema_reads_sha_and_utf8(self):
        self.assertEqual(self.adapter.read("index.html"),blob_sha("Original published index"))
        self.assertEqual(self.adapter.read_content("index.html"),"Original published index")
        self.assertEqual(self.adapter.read("posts/ri-999-absent.html"),None)
        self.assertTrue(all(c[0]=="GET" for c in self.api.calls))
        self.assertTrue(any(c[1]=="index.html" for c in self.api.calls))
    def test_writes_disabled_by_default_even_when_sha_supplied(self):
        with self.assertRaisesRegex(GitHubContentsError,"GITHUB_WRITES_DISABLED"):
            self.adapter.write("index.html","New",self.adapter.read("index.html"))
        self.assertFalse(any(c[0]=="PUT" for c in self.api.calls))
    def test_enabled_put_is_sha_guarded_and_payload_is_base64(self):
        adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api,live_write_enabled=True)
        prev=adapter.read("index.html")
        result=adapter.write("index.html","새 MRI 기사",prev)
        self.assertEqual(result,blob_sha("새 MRI 기사"))
        self.assertEqual(adapter.read_content("index.html"),"새 MRI 기사")
        put=[c for c in self.api.calls if c[0]=="PUT"][0]
        self.assertEqual(put[2]["branch"],"main")
        self.assertEqual(put[2]["sha"],prev)
        self.assertEqual(base64.b64decode(put[2]["content"]).decode(),"새 MRI 기사")
    def test_create_absent_file_with_no_sha(self):
        adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api,live_write_enabled=True)
        result=adapter.write("posts/ri-999-absent.html","<h1>Test</h1>",None)
        self.assertEqual(result,blob_sha("<h1>Test</h1>"))
        put=[c for c in self.api.calls if c[0]=="PUT"][0]
        self.assertNotIn("sha",put[2])
    def test_stale_sha_prevents_write(self):
        adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api,live_write_enabled=True)
        with self.assertRaisesRegex(GitHubContentsError,"REMOTE_CHANGED_BEFORE_WRITE"):
            adapter.write("index.html","Overwrite","a"*40)
        self.assertFalse(any(c[0]=="PUT" for c in self.api.calls))
    def test_provider_conflict_fails_closed(self):
        self.api.force_conflict=True
        adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api,live_write_enabled=True)
        with self.assertRaisesRegex(GitHubContentsError,"GITHUB_CONDITIONAL_WRITE_FAILED:409"):
            adapter.write("index.html","Overwrite",adapter.read("index.html"))
    def test_response_loss_does_not_internally_retry(self):
        self.api.raise_after_write=True
        adapter=GitHubContentsAdapter("ChungHwan-Kang/radiology-intelligence","main",self.api,live_write_enabled=True)
        with self.assertRaises(ConnectionError):
            adapter.write("index.html","Committed before lost response",adapter.read("index.html"))
        self.assertEqual(len([x for x in self.api.calls if x[0]=="PUT"]),1)
        self.assertEqual(self.api.files["index.html"],"Committed before lost response")
    def test_invalid_path_or_branch_rejected(self):
        for path in ("../index.html","index.html?ref=evil","./index.html"):
            with self.assertRaises(ValueError):
                self.adapter.read(path)
        with self.assertRaisesRegex(ValueError,"INVALID_BRANCH"):
            GitHubContentsAdapter("owner/repo","../bad",self.api)
    def test_missing_token_rejected_without_request(self):
        with self.assertRaisesRegex(ValueError,"GITHUB_TOKEN_REQUIRED"):
            build_authenticated_transport("")


if __name__=="__main__":
    unittest.main()
