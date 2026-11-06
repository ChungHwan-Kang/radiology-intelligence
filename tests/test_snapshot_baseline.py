import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from snapshot_integrity import RANGES, digest
from snapshot_baseline import verify_against_baseline

def case():
    data = {"Master_Index": [["ID", "DOI", "Content Stage"], ["RI-030", "10.1002/jmri.70592", "Published"]],
            "MRI_Research_Watch": [["Title", "DOI", "RI Article Candidate", "Priority", "Existing Master ID"],
                                   ["Study", "10.1000/example", "YES", "HIGH", ""]], "_snapshot_complete": True}
    data["_snapshot_envelope"] = {"tabs": {name: {"range": rng, "rows": len(data[name]), "sha256": digest(data[name])}
                                           for name, rng in RANGES.items()}}
    baseline = {"spreadsheet_id": "known-connected-sheet", "tabs": {
        name: {"observed_rows": len(data[name]), "provider_range": name + "!" + rng,
               "headers": list(data[name][0])} for name, rng in RANGES.items()}}
    return data, baseline

class BaselineTests(unittest.TestCase):
    def test_valid_baseline(self):
        v,b=case()
        self.assertEqual(verify_against_baseline(v,b)["state"], "BASELINE_CHECK_PASS")
    def test_truncated_but_self_consistent_envelope_blocked(self):
        v,b=case()
        v["Master_Index"].pop()
        v["_snapshot_envelope"]["tabs"]["Master_Index"]["rows"]=len(v["Master_Index"])
        v["_snapshot_envelope"]["tabs"]["Master_Index"]["sha256"]=digest(v["Master_Index"])
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_BELOW_OBSERVED_BASELINE"):
            verify_against_baseline(v,b)
    def test_changed_header_with_recomputed_hash_blocked(self):
        v,b=case()
        v["Master_Index"][0][0]="Wrong"
        v["_snapshot_envelope"]["tabs"]["Master_Index"]["sha256"]=digest(v["Master_Index"])
        with self.assertRaisesRegex(ValueError,"BASELINE_HEADER_CHANGED"):
            verify_against_baseline(v,b)
    def test_malformed_baseline_blocked(self):
        v,b=case()
        del b["spreadsheet_id"]
        with self.assertRaisesRegex(ValueError,"MISSING_BASELINE_SPREADSHEET_ID"):
            verify_against_baseline(v,b)
    def test_missing_tab_baseline_blocked(self):
        v,b=case()
        del b["tabs"]["MRI_Research_Watch"]
        with self.assertRaisesRegex(ValueError,"MISSING_BASELINE_TAB"):
            verify_against_baseline(v,b)
    def test_bad_provider_range_blocked(self):
        v,b=case()
        b["tabs"]["Master_Index"]["provider_range"]="Incorrect!A1:Z1000"
        with self.assertRaisesRegex(ValueError,"INVALID_BASELINE_RANGE"):
            verify_against_baseline(v,b)
    def test_same_tab_but_shorter_provider_range_blocked(self):
        v,b=case()
        b["tabs"]["Master_Index"]["provider_range"]="Master_Index!A1:Z1000"
        with self.assertRaisesRegex(ValueError,"BASELINE_SNAPSHOT_RANGE_MISMATCH"):
            verify_against_baseline(v,b)
    def test_boolean_count_blocked(self):
        v,b=case()
        b["tabs"]["Master_Index"]["observed_rows"]=True
        with self.assertRaisesRegex(ValueError,"INVALID_BASELINE_COUNT"):
            verify_against_baseline(v,b)
    def test_growth_is_allowed(self):
        v,b=case()
        v["Master_Index"].append(["RI-031", "10.1000/new", "Research"])
        v["_snapshot_envelope"]["tabs"]["Master_Index"]["rows"]=len(v["Master_Index"])
        v["_snapshot_envelope"]["tabs"]["Master_Index"]["sha256"]=digest(v["Master_Index"])
        self.assertEqual(verify_against_baseline(v,b)["tabs"]["Master_Index"]["actual_rows"], 3)
if __name__ == "__main__": unittest.main()
