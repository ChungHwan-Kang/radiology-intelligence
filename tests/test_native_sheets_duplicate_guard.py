import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from native_sheets_duplicate_guard import build_native_duplicate_guard

CANONICAL="1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM"
RANGES={"Master_Index":"A1:Z1026","MRI_Research_Watch":"A1:S1000"}


class NativeSheetsGuardTests(unittest.TestCase):
    def setUp(self):
        m=["x"+str(i) for i in range(26)]
        for name,i in (("ID",0),("DOI",10),("Content Stage",14)): m[i]=name
        w=["x"+str(i) for i in range(19)]
        for name,i in (("DOI",4),("RI Article Candidate",14),("Priority",15),
                       ("Existing Master ID",16)): w[i]=name
        self.master=[m,["RI-030"]+[""]*9+["10.1000/already-published"]+[""]*15]
        self.watch=[w,[""]*4+["10.1000/new-item"]+[""]*9+["YES","HIGH","","Indexed","2026-11-09"]]
    def verdict(self,doi="10.1000/new-item",article_id="RI-031"):
        return build_native_duplicate_guard(self.master,self.watch,article_id,doi,
                                            spreadsheet_id=CANONICAL,read_ranges=RANGES)
    def test_clean_native_values_pass_and_do_not_authorize_publication(self):
        r=self.verdict()
        self.assertEqual(r["status"],"CALLER_NATIVE_SHEETS_DUPLICATE_GUARD_PASS")
        self.assertEqual(r["matching_watch_doi_rows"],1)
        self.assertFalse(r["public_write_permitted"])
        self.assertFalse(r["source_verified_independently"])
    def test_duplicate_doi_blocks(self):
        with self.assertRaisesRegex(ValueError,"ALREADY_IN_MASTER_DOI"):
            self.verdict("https://doi.org/10.1000/already-published")
    def test_duplicate_id_blocks(self):
        with self.assertRaisesRegex(ValueError,"ALREADY_IN_MASTER_ID"):
            self.verdict(article_id="RI-030")
    def test_linked_watch_doi_blocks(self):
        self.watch[1][16]="RI-030"
        with self.assertRaisesRegex(ValueError,"DOI_ALREADY_LINKED_IN_WATCH_ROW"):
            self.verdict()
    def test_corrupt_export_marker_74_blocks(self):
        self.watch[1][16]="74"
        with self.assertRaisesRegex(ValueError,"INVALID_WATCH_MASTER_LINK_ROW"):
            self.verdict()
    def test_watch_priority_corruption_blocks(self):
        self.watch[1][15]="74"
        with self.assertRaisesRegex(ValueError,"INVALID_WATCH_PRIORITY_ROW"):
            self.verdict()
    def test_header_schema_mismatch_blocks(self):
        self.watch[0][16]="Wrong Header"
        with self.assertRaisesRegex(ValueError,"WATCH_REQUIRED_COLUMN_MISMATCH"):
            self.verdict()
    def test_dynamic_row_count_is_supported(self):
        for n in range(5):
            self.watch.append([""]*4+[f"10.1000/other-{n}"])
        self.assertEqual(self.verdict()["watch_data_rows"],6)
    def test_wrong_source_id_or_range_blocks(self):
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_CANONICAL_SHEET_ID"):
            build_native_duplicate_guard(self.master,self.watch,"RI-031","10.1000/new-item",
                                         spreadsheet_id="wrong",read_ranges=RANGES)
        with self.assertRaisesRegex(ValueError,"CANONICAL_NATIVE_RANGE_MISMATCH"):
            build_native_duplicate_guard(self.master,self.watch,"RI-031","10.1000/new-item",
                                         spreadsheet_id=CANONICAL,
                                         read_ranges={"Master_Index":"A1:Z2",
                                                      "MRI_Research_Watch":"A1:S1000"})


if __name__=="__main__":
    unittest.main()
