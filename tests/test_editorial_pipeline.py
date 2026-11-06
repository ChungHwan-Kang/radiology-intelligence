import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from editorial_pipeline import execute
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
    def test_idempotent(self):
        self.assertEqual(execute(self.values,self.active,self.states,self.out,self.note),
                         execute(self.values,self.active,self.states,self.out,self.note))
    def test_missing_research_data_blocks(self):
        self.assertEqual(execute(self.values,self.active,self.states,self.out)["steps"][2]["status"],"BLOCKED")
    def test_wrong_doi_fails(self):
        self.note["doi"]="10.1000/wrong"
        self.assertEqual(execute(self.values,self.active,self.states,self.out,self.note)["state"],"FAIL")
if __name__=="__main__":unittest.main()
