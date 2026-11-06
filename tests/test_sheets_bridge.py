import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from sheets_bridge import bridge
from editorial_queue import select,read_csv
class SheetsBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.dest=Path(self.temp.name)/"private"
        self.data={"Master_Index":[["ID","DOI","Content Stage"],["RI-030","10.1002/jmri.70592","Published"]],
        "MRI_Research_Watch":[["Title","DOI","RI Article Candidate","Priority","Existing Master ID"],
        ["Published","10.1002/jmri.70592","YES","HIGH","RI-030"],["P-SMART","10.1186/s13244-026-02459-2","YES","HIGH",""]]}
    def test_values_to_csv_and_queue(self):
        m=bridge(self.data,self.dest);self.assertEqual(m["tabs"],{"Master_Index":1,"MRI_Research_Watch":2})
        self.assertFalse(m["source_write_performed"])
        r=select(read_csv(self.dest/"Master_Index.csv"),read_csv(self.dest/"MRI_Research_Watch.csv"),
           {"article_id":"RI-031","state":"SOURCE_BLOCKED","doi":"10.1002/jmri.70589"},
           {"10.1186/s13244-026-02459-2":"SOURCE_VERIFIED"})
        self.assertEqual(r["candidate_title"],"P-SMART");self.assertFalse(r["public_write_permitted"])
    def test_missing_tabs(self):
        with self.assertRaisesRegex(ValueError,"MISSING_REQUIRED_TWO_TABS"):bridge({"Master_Index":[]},self.dest)
    def test_missing_header(self):
        self.data["Master_Index"]=[["ID","DOI"],["RI-030","10.1002/jmri.70592"]]
        with self.assertRaisesRegex(ValueError,"MISSING_HEADERS"):bridge(self.data,self.dest)
    def test_git_storage_rejected(self):
        (self.dest/".git").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,"PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY"):bridge(self.data,self.dest)
if __name__=="__main__":unittest.main()
