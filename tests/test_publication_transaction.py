import hashlib,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from publication_transaction import plan_publish,prepare_github_sha_lease

class PublicationTransactionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.folder=self.root/"RI-999"
        self.folder.mkdir()
        self.article={"id":"RI-999","slug":"ri-999-synthetic.html",
            "references":["10.1000/synthetic-code-test"],
            "source_verification":{
                "original_methods_results":True,"quantitative_claims":True,
                "supplement":"NOT_APPLICABLE","source_url":"https://doi.org/10.1000/synthetic-code-test"},
            "claims":[{"claim":"Synthetic test only","primary_source_location":"Methods/Test",
                       "verified":True}]}
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
    def test_optimistic_sha_lease_for_fresh_approved_plan(self):
        self.approved()
        plan=plan_publish(self.root,"RI-999")
        remote={p:("a"*40) for p in plan["required_targets"]}
        remote["posts/"+self.article["slug"]]=None
        lease=prepare_github_sha_lease(plan,remote)
        self.assertTrue(lease["remote_shas_must_be_revalidated_immediately_before_each_write"])
        self.assertTrue(lease["approved_noindex_preview_must_not_be_published"])
        self.assertFalse(lease["public_write_performed"])

    def test_sha_lease_rejects_existing_article(self):
        self.approved()
        plan=plan_publish(self.root,"RI-999")
        remote={p:("a"*40) for p in plan["required_targets"]}
        with self.assertRaisesRegex(ValueError,"ARTICLE_ALREADY_EXISTS_REMOTE"):
            prepare_github_sha_lease(plan,remote)

    def test_sha_lease_rejects_missing_remote_files(self):
        self.approved()
        plan=plan_publish(self.root,"RI-999")
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_REMOTE_SHA_SNAPSHOT"):
            prepare_github_sha_lease(plan,{})

    def test_sha_lease_rejects_invalid_existing_sha(self):
        self.approved()
        plan=plan_publish(self.root,"RI-999")
        remote={p:("a"*40) for p in plan["required_targets"]}
        remote["posts/"+self.article["slug"]]=None
        remote["index.html"]="not-a-sha"
        with self.assertRaisesRegex(ValueError,"INVALID_REMOTE_SHA"):
            prepare_github_sha_lease(plan,remote)

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
    def test_approved_but_quantitative_unverified_blocked(self):
        self.article["source_verification"]["quantitative_claims"]=False
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.state["source_sha256"]=hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()
        self.approved()
        with self.assertRaisesRegex(ValueError,"QUANTITATIVE_CLAIMS_NOT_VERIFIED"):
            plan_publish(self.root,"RI-999")

    def test_approved_but_supplement_pending_blocked(self):
        self.article["source_verification"]["supplement"]="PENDING"
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.state["source_sha256"]=hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()
        self.approved()
        with self.assertRaisesRegex(ValueError,"SUPPLEMENT_STATUS_UNRESOLVED"):
            plan_publish(self.root,"RI-999")

    def test_approved_but_claim_without_primary_locator_blocked(self):
        self.article["claims"][0]["primary_source_location"]=""
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.state["source_sha256"]=hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()
        self.approved()
        with self.assertRaisesRegex(ValueError,"CLAIM_PROVENANCE_INCOMPLETE"):
            plan_publish(self.root,"RI-999")

    def test_approved_but_primary_source_url_missing_blocked(self):
        self.article["source_verification"]["source_url"]=""
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.state["source_sha256"]=hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()
        self.approved()
        with self.assertRaisesRegex(ValueError,"PRIMARY_SOURCE_URL_MISSING"):
            plan_publish(self.root,"RI-999")

    def test_path_traversal(self):
        with self.assertRaisesRegex(ValueError,"INVALID_ARTICLE_ID"):
            plan_publish(self.root,"../RI-999")

if __name__=="__main__":unittest.main()
