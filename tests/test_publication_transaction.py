import hashlib,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from publication_transaction import plan_publish,prepare_github_sha_lease,render_approved_public_html
from private_editorial_gate import preview

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

    def make_full_approved_preview(self):
        self.article.update(
            title="Synthetic MRI article",subtitle="Synthetic test",
            summary="Synthetic study for code tests.",
            categories=["MRI"],
            sections=[{"heading":"Source Fact","text":"Test methods"},
                      {"heading":"Practical Implication","text":"No clinical claim"}],
            takeaway="Test only."
        )
        (self.folder/"article.json").write_text(json.dumps(self.article))
        self.html=preview(self.article).encode("utf-8")
        (self.folder/"review.html").write_bytes(self.html)
        self.sha=hashlib.sha256(self.html).hexdigest()
        self.state["source_sha256"]=hashlib.sha256((self.folder/"article.json").read_bytes()).hexdigest()
        self.state["sha256"]=self.sha
        self.approved()

    def test_public_html_from_approved_preview_removes_private_markers(self):
        self.make_full_approved_preview()
        result=render_approved_public_html(self.root,"RI-999","2026-11-09")
        self.assertEqual(result["status"],"PUBLIC_HTML_RENDERED_NOT_PUBLISHED")
        self.assertFalse(result["public_write_performed"])
        self.assertEqual(result["approved_private_sha256"],self.sha)
        self.assertNotIn("noindex",result["html"])
        self.assertNotIn("[비공개 검토]",result["html"])
        self.assertIn("발행일 2026-11-09",result["html"])
        self.assertIn("Synthetic study for code tests.",result["html"])
        self.assertEqual((self.folder/"review.html").read_bytes(),self.html)

    def test_public_html_rejects_unapproved_state(self):
        self.make_full_approved_preview()
        self.state["state"]="APPROVAL_PENDING"
        self.save()
        with self.assertRaisesRegex(ValueError,"ARTICLE_SPECIFIC_APPROVAL_REQUIRED"):
            render_approved_public_html(self.root,"RI-999","2026-11-09")

    def test_public_html_rejects_changed_approved_preview(self):
        self.make_full_approved_preview()
        (self.folder/"review.html").write_bytes(self.html+b"tampered")
        with self.assertRaisesRegex(ValueError,"APPROVED_HTML_CHANGED"):
            render_approved_public_html(self.root,"RI-999","2026-11-09")

    def test_public_html_rejects_invalid_date_and_incomplete_preview(self):
        self.make_full_approved_preview()
        with self.assertRaisesRegex(ValueError,"INVALID_PUBLICATION_DATE"):
            render_approved_public_html(self.root,"RI-999","11/09/2026")
        (self.folder/"review.html").write_bytes(b'<meta name="robots" content="noindex,nofollow">')
        self.state["sha256"]=hashlib.sha256((self.folder/"review.html").read_bytes()).hexdigest()
        self.state["approval_sha256"]=self.state["sha256"]
        self.save()
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_APPROVED_PREVIEW_STRUCTURE"):
            render_approved_public_html(self.root,"RI-999","2026-11-09")

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
