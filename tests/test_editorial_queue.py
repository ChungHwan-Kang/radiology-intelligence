import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from editorial_queue import select,norm_doi

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
