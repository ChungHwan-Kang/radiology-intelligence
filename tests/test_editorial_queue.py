import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from editorial_queue import select,norm_doi,build_source_review_backlog

def row(doi,title,priority="HIGH",existing="",index=1):
    return {"DOI":doi,"Title":title,"RI Article Candidate":"YES","Priority":priority,
            "Existing Master ID":existing,"Watch Row":str(index)}
class QueueTests(unittest.TestCase):
    def setUp(self):
        self.active={"article_id":"RI-031","state":"SOURCE_BLOCKED","doi":"10.1002/jmri.70589"}
        self.watch=[row("https://doi.org/10.1186/s13244-026-02459-2","P-SMART",index=59),
                    row("10.1002/jmri.70589","CE MRA",index=51)]
        self.states={"10.1186/s13244-026-02459-2":"SOURCE_VERIFIED"}
    def test_normalize_doi(self):
        self.assertEqual(norm_doi("HTTPS://DOI.ORG/10.1234/X?abc=1"),"10.1234/x")
    def test_blocked_active_fallback_no_id(self):
        r=select([],self.watch,self.active,self.states)
        self.assertEqual(r["decision"],"RESEARCH_ALTERNATE")
        self.assertTrue(r["no_new_ri_id"]);self.assertFalse(r["public_write_permitted"])
    def test_resumable_active_precedes_alternate(self):
        self.active["state"]="DRAFT_READY"
        self.assertEqual(select([],self.watch,self.active,self.states)["decision"],"RESUME_ACTIVE")
    def test_published_doi_never_selected(self):
        master=[{"ID":"RI-030","Content Stage":"Published","DOI":"10.1186/s13244-026-02459-2","Title":"P-SMART"}]
        self.assertEqual(select(master,self.watch,self.active,self.states)["decision"],"SOURCE_BLOCKED")
    def test_missing_verified_source_never_selected(self):
        self.assertEqual(select([],self.watch,self.active,{})["decision"],"SOURCE_BLOCKED")
    def test_existing_master_reference_never_selected(self):
        self.watch[0]["Existing Master ID"]="RI-030"
        self.assertEqual(select([],self.watch,self.active,self.states)["decision"],"SOURCE_BLOCKED")
    def test_no_active_can_prepare_without_id(self):
        self.active={"state":"PUBLISHED","article_id":"RI-031"}
        r=select([],self.watch,self.active,self.states)
        self.assertEqual(r["decision"],"PREPARE_CANDIDATE");self.assertTrue(r["no_new_ri_id"])
    def test_production_rejects_unsubstantiated_legacy_flag(self):
        r=select([],self.watch,self.active,self.states,require_source_evidence=True)
        self.assertEqual(r["decision"],"SOURCE_BLOCKED")

    def test_production_accepts_complete_review_record(self):
        doi="10.1186/s13244-026-02459-2"
        self.states[doi]={
            "status":"SOURCE_VERIFIED",
            "original_methods_results":True,
            "quantitative_claims":True,
            "supplement":"UNAVAILABLE_DISCLOSED",
            "source_url":"https://doi.org/"+doi,
            "methods_locator":"Original article Methods section",
            "results_locator":"Original article Results/Table 2",
            "reviewed_by":"editor",
            "reviewed_at":"2026-11-06"
        }
        r=select([],self.watch,self.active,self.states,require_source_evidence=True)
        self.assertEqual(r["decision"],"RESEARCH_ALTERNATE")
        self.assertEqual(r["candidate_doi"],doi)

    def test_production_blocks_missing_primary_results_locator(self):
        doi="10.1186/s13244-026-02459-2"
        self.states[doi]={
            "status":"SOURCE_VERIFIED",
            "original_methods_results":True,
            "quantitative_claims":True,
            "supplement":"VERIFIED",
            "source_url":"https://doi.org/"+doi,
            "methods_locator":"Methods section",
            "reviewed_by":"editor",
            "reviewed_at":"2026-11-06"
        }
        self.assertEqual(select([],self.watch,self.active,self.states,require_source_evidence=True)["decision"],"SOURCE_BLOCKED")

    def test_unverified_source_review_backlog_prioritizes_high_and_never_allocates(self):
        worklist=build_source_review_backlog([],self.watch,self.active,{})
        self.assertEqual(worklist["candidate_count"],1)
        self.assertEqual(worklist["entries"][0]["doi"],"10.1186/s13244-026-02459-2")
        self.assertIsNone(worklist["entries"][0]["article_id"])
        self.assertFalse(worklist["source_verification_performed"])
        self.assertFalse(worklist["public_write_permitted"])

    def test_review_backlog_skips_verified_and_linked(self):
        doi="10.1186/s13244-026-02459-2"
        self.states[doi]={
            "status":"SOURCE_VERIFIED",
            "original_methods_results":True,
            "quantitative_claims":True,
            "supplement":"VERIFIED",
            "source_url":"https://doi.org/"+doi,
            "methods_locator":"Methods section",
            "results_locator":"Results/Table 2",
            "reviewed_by":"editor",
            "reviewed_at":"2026-11-06"
        }
        worklist=build_source_review_backlog([],self.watch,self.active,self.states)
        self.assertEqual(worklist["entries"],[])
        self.watch[0]["Existing Master ID"]="RI-030"
        self.assertEqual(build_source_review_backlog([],self.watch,self.active,{})["entries"],[])

    def test_in_progress_review_survives_blocked_run_without_verification(self):
        doi="10.1186/s13244-026-02459-2"
        self.states[doi]={
            "status":"SOURCE_REVIEW_IN_PROGRESS",
            "supplement":"PENDING",
            "methods_locator":"Original article Methods",
            "results_locator":"Original article Results"
        }
        worklist=build_source_review_backlog([],self.watch,self.active,self.states)
        self.assertEqual(worklist["candidate_count"],1)
        item=worklist["entries"][0]
        self.assertEqual(item["review_state"],"SOURCE_REVIEW_IN_PROGRESS")
        self.assertTrue(item["pending_supplement_review"])
        self.assertIsNone(item["article_id"])
        self.assertFalse(worklist["source_verification_performed"])

    def test_in_progress_review_precedes_newer_unreviewed_high_priority(self):
        doi="10.1186/s13244-026-02459-2"
        self.watch.append(row("10.1000/newer","New study","HIGH",index=100))
        self.states[doi]={
            "status":"SOURCE_REVIEW_IN_PROGRESS",
            "supplement":"PENDING",
            "source_url":"https://doi.org/"+doi,
            "pending_tasks":["Inspect original supplemental Table S1","Verify sensitivity analysis Table S2"]
        }
        result=build_source_review_backlog([],self.watch,self.active,self.states,limit=2)
        self.assertEqual(result["candidate_count"],2)
        self.assertEqual(result["entries"][0]["doi"],doi)
        self.assertEqual(result["entries"][0]["required_next_steps"],self.states[doi]["pending_tasks"])
        self.assertEqual(result["entries"][0]["review_note_source_url"],"https://doi.org/"+doi)
        self.assertFalse(result["source_verification_performed"])

    def test_unreviewed_candidate_has_no_pending_supplement_attestation(self):
        worklist=build_source_review_backlog([],self.watch,self.active,{})
        item=worklist["entries"][0]
        self.assertEqual(item["review_state"],"SOURCE_REVIEW_REQUIRED")
        self.assertFalse(item["pending_supplement_review"])

    def test_review_backlog_deduplicates_and_respects_limit(self):
        new=row("10.1000/other","Other","MEDIUM",index=77)
        self.watch.extend([new,dict(new)])
        worklist=build_source_review_backlog([],self.watch,self.active,{},limit=1)
        self.assertEqual(worklist["candidate_count"],2)
        self.assertEqual(len(worklist["entries"]),1)
        with self.assertRaisesRegex(ValueError,"INVALID_REVIEW_BACKLOG_LIMIT"):
            build_source_review_backlog([],self.watch,self.active,{},limit=0)

    def test_default_watch_row_import(self):
        import csv,tempfile
        from editorial_queue import read_csv
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"watch.csv"
            with path.open("w",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=["DOI","Title"])
                writer.writeheader()
                writer.writerow({"DOI":"10.1000/a","Title":"A"})
                writer.writerow({"DOI":"10.1000/b","Title":"B"})
            self.assertEqual([r["Watch Row"] for r in read_csv(path)],["2","3"])
    def test_prioritizes_high_over_medium(self):
        self.watch.insert(0,row("10.1000/med","MED","MEDIUM",index=61))
        self.states["10.1000/med"]="SOURCE_VERIFIED"
        self.assertEqual(select([],self.watch,self.active,self.states)["candidate_title"],"P-SMART")
if __name__=="__main__": unittest.main()
