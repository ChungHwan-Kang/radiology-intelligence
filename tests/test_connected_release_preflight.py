import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))

from connected_release_preflight import prepare_connected_github_release, prepare_connected_release_from_native_sheets, prepare_release_with_provider_reads, INDEX_PATHS
from private_editorial_gate import preview


class FrozenReadAdapter:
    def __init__(self, site):
        self.site=dict(site)
        self.calls=[]
        self.mutate_on_second_read=None
        self.read_counts={}
    def read_content(self,path):
        self.calls.append(("read_content",path))
        count=self.read_counts.get(path,0)+1
        self.read_counts[path]=count
        if self.mutate_on_second_read==path and count==2:
            self.site[path]+="\n<!-- conflicting update -->"
        return self.site[path]
    def read(self,path):
        self.calls.append(("read_sha",path))
        if path not in self.site:
            return None
        raw=self.site[path].encode("utf-8")
        return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    def write(self,*args):
        raise AssertionError("read-only preflight must never write")


class ConnectedPreflightTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.folder=self.root/"RI-999"
        self.folder.mkdir()
        self.article={
            "id":"RI-999","slug":"ri-999-only-synthetic.html",
            "title":"MRI code-only synthetic research",
            "subtitle":"Code fixture",
            "summary":"No clinical result. Code validation only.",
            "categories":["MRI 검사와 기술","연구와 근거"],
            "sections":[{"heading":"Source Fact","text":"Synthetic input."},
                        {"heading":"Practical Implication","text":"No clinical inference."}],
            "takeaway":"Code test only.",
            "references":["https://doi.org/10.1000/synthetic-code-test"],
            "source_verification":{
                "original_methods_results":True,"quantitative_claims":True,
                "supplement":"NOT_APPLICABLE",
                "source_url":"https://doi.org/10.1000/synthetic-code-test"},
            "claims":[{"claim":"Synthetic code statement","verified":True,
                       "primary_source_location":"Synthetic fixture"}]
        }
        source=json.dumps(self.article).encode()
        page=preview(self.article).encode()
        (self.folder/"article.json").write_bytes(source)
        (self.folder/"review.html").write_bytes(page)
        self.state={"state":"APPROVED_FOR_PUBLISH","article_id":"RI-999",
                    "source_sha256":hashlib.sha256(source).hexdigest(),
                    "sha256":hashlib.sha256(page).hexdigest(),
                    "approval_sha256":hashlib.sha256(page).hexdigest()}
        (self.folder/"status.json").write_text(json.dumps(self.state))
        repo=Path(__file__).resolve().parents[1]
        self.site={p:(repo/p).read_text(encoding="utf-8") for p in INDEX_PATHS}
        self.adapter=FrozenReadAdapter(self.site)
    def execute(self,*,dois=(),ids=()):
        return prepare_connected_github_release(
            self.root,"RI-999","2026-11-09T10:00:00+09:00",self.adapter,
            published_dois=dois,published_ids=ids)
    def test_native_sheet_duplicate_guard_connected_to_approved_preflight(self):
        m=["x"+str(i) for i in range(26)]
        for name,i in (("ID",0),("DOI",10),("Content Stage",14)): m[i]=name
        w=["x"+str(i) for i in range(19)]
        for name,i in (("DOI",4),("RI Article Candidate",14),("Priority",15),
                       ("Existing Master ID",16)): w[i]=name
        master=[m,["RI-030"]+[""]*25]
        watch=[w,[""]*4+["10.1000/synthetic-code-test"]+[""]*9+
               ["YES","HIGH","","Indexed","2026-11-09"]]
        r=prepare_connected_release_from_native_sheets(
            self.root,"RI-999","2026-11-09T10:00:00+09:00",self.adapter,
            master,watch,"1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM",
            {"Master_Index":"A1:Z1026","MRI_Research_Watch":"A1:S1000"})
        self.assertEqual(r["native_sheets_duplicate_guard"]["matching_watch_doi_rows"],1)
        self.assertEqual(r["status"],"CONNECTED_GITHUB_READONLY_PREFLIGHT_READY")
        self.assertFalse(r["ready_for_unattended_publication"])
        self.assertFalse(r["public_write_performed"])
        self.assertEqual(len(r["bundle"]["contents"]),5)
        master[1][10]="10.1000/synthetic-code-test"
        with self.assertRaisesRegex(ValueError,"ALREADY_IN_MASTER_DOI"):
            prepare_connected_release_from_native_sheets(
                self.root,"RI-999","2026-11-09T10:00:00+09:00",self.adapter,
                master,watch,"1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM",
                {"Master_Index":"A1:Z1026","MRI_Research_Watch":"A1:S1000"})

    def test_provider_read_twice_is_linked_to_approved_no_write_release(self):
        from native_sheets_reader import NativeSheetsReader, SHEET_ID, SHEET_IDS
        from urllib.parse import unquote, urlsplit
        m=["x"+str(i) for i in range(26)]
        for name,i in (("ID",0),("DOI",10),("Content Stage",14)): m[i]=name
        w=["x"+str(i) for i in range(19)]
        for name,i in (("DOI",4),("RI Article Candidate",14),("Priority",15),("Existing Master ID",16)): w[i]=name
        values={"Master_Index":[m,["RI-030"]+[""]*25],
                "MRI_Research_Watch":[w,[""]*4+["10.1000/synthetic-code-test"]+
                                      [""]*9+["YES","HIGH","","Indexed","2026-11-09"]]}
        calls=[]
        def provider(url):
            calls.append(url)
            if "/values/" not in url:
                return 200,{"spreadsheetId":SHEET_ID,"sheets":[{"properties":{
                    "title":name,"sheetId":sid}} for name,sid in SHEET_IDS.items()]}
            a1=unquote(urlsplit(url).path.split("/values/",1)[1])
            name,range_string=a1.split("!",1)
            return 200,{"range":a1,"majorDimension":"ROWS","values":values[name]}
        result=prepare_release_with_provider_reads(
            self.root,"RI-999","2026-11-09T10:00:00+09:00",
            self.adapter,NativeSheetsReader(provider))
        self.assertEqual(result["status"],"CONNECTED_GITHUB_READONLY_PREFLIGHT_READY")
        self.assertEqual(len(calls),10)
        self.assertEqual(len(result["bundle"]["contents"]),5)
        self.assertEqual(result["native_provider_read_receipt"]["status"],"NATIVE_PROVIDER_READ_TWICE_CONSISTENT")
        self.assertFalse(result["ready_for_unattended_publication"])
        self.assertFalse(result["public_write_performed"])
        self.assertTrue(all(c[0]!="write" for c in self.adapter.calls))

    def test_real_repo_baseline_produces_five_file_readonly_plan(self):
        result=self.execute()
        self.assertEqual(result["status"],"CONNECTED_GITHUB_READONLY_PREFLIGHT_READY")
        self.assertEqual(len(result["bundle"]["contents"]),5)
        self.assertEqual(result["lease"]["remote_sha_expectations"]["posts/ri-999-only-synthetic.html"],None)
        self.assertFalse(result["public_write_performed"])
        self.assertFalse(result["ready_for_unattended_publication"])
        self.assertTrue(all(c[0]!="write" for c in self.adapter.calls))
        self.assertEqual(set(self.adapter.read_counts),set(INDEX_PATHS))
    def test_approval_missing_blocks_before_any_remote_read(self):
        self.state["state"]="APPROVAL_PENDING"
        (self.folder/"status.json").write_text(json.dumps(self.state))
        with self.assertRaisesRegex(ValueError,"ARTICLE_SPECIFIC_APPROVAL_REQUIRED"):
            self.execute()
        self.assertFalse(self.adapter.calls)
    def test_doi_duplicate_blocks_before_any_remote_read(self):
        with self.assertRaisesRegex(ValueError,"ALREADY_PUBLISHED_OR_DUPLICATE"):
            self.execute(dois=["10.1000/synthetic-code-test"])
        self.assertFalse(self.adapter.calls)
    def test_changed_remote_content_blocks_and_does_not_write(self):
        self.adapter.mutate_on_second_read="feed.xml"
        with self.assertRaisesRegex(ValueError,"REMOTE_CONTENT_CHANGED_DURING_PREFLIGHT:feed.xml"):
            self.execute()
        self.assertTrue(all(c[0]!="write" for c in self.adapter.calls))
    def test_missing_duplicate_guard_input_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"AUTHORITATIVE_DUPLICATE_GUARD_INPUT_REQUIRED"):
            prepare_connected_github_release(self.root,"RI-999","2026-11-09T10:00:00+09:00",
                                             self.adapter,None,None)
        self.assertFalse(self.adapter.calls)
    def test_existing_remote_post_blocks_new_article(self):
        self.adapter.site["posts/ri-999-only-synthetic.html"]="existing"
        with self.assertRaisesRegex(ValueError,"ARTICLE_ALREADY_EXISTS_REMOTE"):
            self.execute()
        self.assertTrue(all(c[0]!="write" for c in self.adapter.calls))


if __name__=="__main__":
    unittest.main()
