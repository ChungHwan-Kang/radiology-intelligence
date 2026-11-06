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
    def test_duplicate_nonkey_header_preserves_both_values(self):
        self.data["Master_Index"]=[
            ["ID","DOI","Content Stage","Published Date","Published Date"],
            ["RI-030","10.1002/jmri.70592","Published","2026-11-03","2026-11-04"]]
        result=bridge(self.data,self.dest)
        cols=read_csv(self.dest/"Master_Index.csv")[0]
        self.assertEqual(cols["Published Date"],"2026-11-03")
        self.assertEqual(cols["Published Date [COL_E]"],"2026-11-04")
        self.assertEqual(result["header_disambiguations"]["Master_Index"],
            [{"column":"E","original":"Published Date","csv_header":"Published Date [COL_E]"}])
        self.assertEqual(self.data["Master_Index"][0].count("Published Date"),2)

    def test_duplicate_required_header_fails_closed(self):
        self.data["Master_Index"]=[
            ["ID","DOI","Content Stage","DOI"],
            ["RI-030","10.1002/jmri.70592","Published","10.1000/different"]]
        with self.assertRaisesRegex(ValueError,"AMBIGUOUS_REQUIRED_HEADER"):
            bridge(self.data,self.dest)

    def test_corrupted_existing_master_reference_rejected(self):
        self.data["MRI_Research_Watch"][1][4]="74"
        with self.assertRaisesRegex(ValueError,"INVALID_MASTER_REFERENCE_ROW_2"):
            bridge(self.data,self.dest)

    def test_corrupted_priority_rejected(self):
        self.data["MRI_Research_Watch"][1][3]="74"
        with self.assertRaisesRegex(ValueError,"INVALID_PRIORITY_ROW_2"):
            bridge(self.data,self.dest)

    def test_valid_existing_ri_reference_accepted(self):
        self.data["MRI_Research_Watch"][1][4]="RI-030"
        self.assertEqual(bridge(self.data,self.dest)["tabs"]["MRI_Research_Watch"],2)

    def test_missing_tabs(self):
        with self.assertRaisesRegex(ValueError,"MISSING_REQUIRED_TWO_TABS"):bridge({"Master_Index":[]},self.dest)
    def test_missing_header(self):
        self.data["Master_Index"]=[["ID","DOI"],["RI-030","10.1002/jmri.70592"]]
        with self.assertRaisesRegex(ValueError,"MISSING_HEADERS"):bridge(self.data,self.dest)
    def test_git_storage_rejected(self):
        (self.dest/".git").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,"PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY"):bridge(self.data,self.dest)
if __name__=="__main__":unittest.main()
