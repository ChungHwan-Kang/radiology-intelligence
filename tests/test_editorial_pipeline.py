import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from editorial_pipeline import execute
from snapshot_integrity import digest
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/"private"
        self.values={"Master_Index":[["ID","DOI","Content Stage"],["RI-030","10.1002/jmri.70592","Published"]],
            "MRI_Research_Watch":[["Title","DOI","RI Article Candidate","Priority","Existing Master ID"],
             ["CE MRA","10.1002/jmri.70589","YES","HIGH",""],
             ["P-SMART","10.1186/s13244-026-02459-2","YES","HIGH",""]]}
        self.active={"article_id":"RI-031","state":"SOURCE_BLOCKED","doi":"10.1002/jmri.70589"}
        self.states={"10.1186/s13244-026-02459-2":"SOURCE_VERIFIED"}
        self.note={"doi":"10.1186/s13244-026-02459-2","title":"P-SMART","source_url":"https://example.org",
                   "source_facts":"40 cases","interpretation":"Not causal",
                   "practical_implication":"Review","limitations":"Selection bias"}
    def test_blocked_article_research_alternate(self):
        r=execute(self.values,self.active,self.states,self.out,self.note)
        self.assertEqual(r["selected"]["decision"],"RESEARCH_ALTERNATE")
        self.assertFalse(r["public_write_performed"]);self.assertFalse(r["new_ri_id_assigned"])
        self.assertEqual(r["steps"][2]["status"],"PASS")
    def test_new_candidate_creates_private_assignment_without_ri_id(self):
        self.active={}
        result=execute(self.values,self.active,self.states,self.out)
        self.assertEqual(result["selected"]["decision"],"PREPARE_CANDIDATE")
        import json
        assignment=json.loads((self.out/"private_candidate_assignment.json").read_text(encoding="utf-8"))
        self.assertEqual(assignment["candidate_doi"],"10.1186/s13244-026-02459-2")
        self.assertIsNone(assignment["article_id"])
        self.assertFalse(assignment["public_write_permitted"])
        self.assertFalse(assignment["source_verification_independent"])
        self.assertFalse(result["new_ri_id_assigned"])
        self.assertFalse(result["public_write_performed"])
        self.assertTrue(any(x["stage"]=="PRIVATE_FINAL_HTML_QA" and x["status"]=="BLOCKED" for x in result["steps"]))

    def test_new_candidate_with_no_verified_source_creates_no_assignment(self):
        self.active={}
        self.states={}
        result=execute(self.values,self.active,self.states,self.out)
        self.assertEqual(result["selected"]["decision"],"NO_ELIGIBLE_SOURCE")
        self.assertFalse((self.out/"private_candidate_assignment.json").exists())

    def test_production_snapshot_block(self):
        result=execute(self.values,self.active,self.states,self.out,self.note,require_complete=True)
        self.assertEqual(result["state"],"BLOCKED")
    def test_production_snapshot_complete(self):
        self.values["_snapshot_complete"]=True
        self.values["_snapshot_envelope"]={"tabs":{
            name:{"range":rng,"rows":len(self.values[name]),"sha256":digest(self.values[name])}
            for name,rng in (("Master_Index","A1:Z1026"),("MRI_Research_Watch","A1:S1000"))}}
        result=execute(self.values,self.active,self.states,self.out,self.note,require_complete=True)
        self.assertEqual(result["selected"]["decision"],"RESEARCH_ALTERNATE")
    def test_production_existing_directory_with_old_result_is_rejected(self):
        self.out.mkdir(parents=True)
        (self.out / "queue_decision.json").write_text('{"old":"data"}')
        self.values["_snapshot_complete"] = True
        with self.assertRaisesRegex(ValueError, "PRIVATE_RUN_DIRECTORY_NOT_EMPTY"):
            execute(self.values,self.active,self.states,self.out,self.note,require_complete=True)
        self.assertEqual((self.out / "queue_decision.json").read_text(), '{"old":"data"}')

    def test_production_output_inside_git_is_rejected(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        (self.out.parent / ".git").mkdir()
        self.values["_snapshot_complete"] = True
        with self.assertRaisesRegex(ValueError, "PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY"):
            execute(self.values,self.active,self.states,self.out,self.note,require_complete=True)

    def test_production_empty_existing_directory_allowed_to_block(self):
        self.out.mkdir(parents=True)
        result=execute(self.values,self.active,self.states,self.out,self.note,require_complete=True)
        self.assertEqual(result["state"],"BLOCKED")

    def test_idempotent(self):
        self.assertEqual(execute(self.values,self.active,self.states,self.out,self.note),
                         execute(self.values,self.active,self.states,self.out,self.note))
    def test_missing_research_data_blocks(self):
        self.assertEqual(execute(self.values,self.active,self.states,self.out)["steps"][2]["status"],"BLOCKED")
    def test_wrong_doi_fails(self):
        self.note["doi"]="10.1000/wrong"
        self.assertEqual(execute(self.values,self.active,self.states,self.out,self.note)["state"],"FAIL")
if __name__=="__main__":unittest.main()
