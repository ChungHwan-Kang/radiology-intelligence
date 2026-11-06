import hashlib,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from publication_transaction import plan_publish

class PublicationTransactionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.folder=self.root/"RI-999"
        self.folder.mkdir()
        self.article={"id":"RI-999","slug":"ri-999-synthetic.html","references":["10.1000/synthetic-code-test"],"source_verification":{"original_methods_results":True}}
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.html=b'<meta name="robots" content="noindex,nofollow">'
        (self.folder/"review.html").write_bytes(self.html)
        self.sha=hashlib.sha256(self.html).hexdigest()
        self.state={"article_id":"RI-999","state":"APPROVAL_PENDING","sha256":self.sha,"source_sha256":hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()}
        self.save()
    def save(self):
        (self.folder/"status.json").write_text(json.dumps(self.state))
    def approved(self):
        self.state.update(state="APPROVED_FOR_PUBLISH",approval_sha256=self.sha)
        self.save()
    def test_missing_approval(self):
        with self.assertRaisesRegex(ValueError,"ARTICLE_SPECIFIC_APPROVAL_REQUIRED"):
            plan_publish(self.root,"RI-999")
    def test_approved_dry_run(self):
        self.approved()
        plan=plan_publish(self.root,"RI-999")
        self.assertFalse(plan["public_write_performed"])
        self.assertEqual(len(plan["required_targets"]),5)
    def test_tampered_article(self):
        self.approved()
        (self.folder/"review.html").write_bytes(b"change")
        with self.assertRaisesRegex(ValueError,"APPROVED_HTML_CHANGED"):
            plan_publish(self.root,"RI-999")
    def test_duplicate_doi(self):
        self.approved()
        with self.assertRaisesRegex(ValueError,"ALREADY_PUBLISHED_OR_DUPLICATE"):
            plan_publish(self.root,"RI-999",published_dois=["10.1000/synthetic-code-test"])
    def test_duplicate_id(self):
        self.approved()
        with self.assertRaisesRegex(ValueError,"ALREADY_PUBLISHED_OR_DUPLICATE"):
            plan_publish(self.root,"RI-999",published_ids=["RI-999"])
    def test_unverified_source(self):
        self.approved()
        self.article["source_verification"]["original_methods_results"]=False
        (self.folder/"article.json").write_text(json.dumps(self.article))
        with self.assertRaisesRegex(ValueError,"APPROVED_SOURCE_CHANGED"):
            plan_publish(self.root,"RI-999")
    def test_path_traversal(self):
        with self.assertRaisesRegex(ValueError,"INVALID_ARTICLE_ID"):
            plan_publish(self.root,"../RI-999")

if __name__=="__main__":unittest.main()
