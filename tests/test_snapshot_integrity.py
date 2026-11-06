import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from snapshot_integrity import digest, validate
from editorial_pipeline import execute


def payload():
    data = {
        "Master_Index": [["ID", "DOI", "Content Stage"], ["RI-030", "10.1002/jmri.70592", "Published"]],
        "MRI_Research_Watch": [["Title", "DOI", "RI Article Candidate", "Priority", "Existing Master ID"],
                               ["P-SMART", "10.1186/s13244-026-02459-2", "YES", "HIGH", ""]],
        "_snapshot_complete": True,
    }
    data["_snapshot_envelope"] = {"tabs": {
        key: {"range": rng, "rows": len(data[key]), "sha256": digest(data[key])}
        for key, rng in (("Master_Index", "A1:Z1000"), ("MRI_Research_Watch", "A1:S1000"))
    }}
    return data


class SnapshotIntegrityTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(len(validate(payload())["tabs"]), 2)

    def test_missing_envelope(self):
        p=payload(); del p["_snapshot_envelope"]
        with self.assertRaises(ValueError): validate(p)

    def test_missing_tab(self):
        p=payload(); del p["MRI_Research_Watch"]
        with self.assertRaises(ValueError): validate(p)

    def test_wrong_range(self):
        p=payload(); p["_snapshot_envelope"]["tabs"]["Master_Index"]["range"]="A1:Z30"
        with self.assertRaises(ValueError): validate(p)

    def test_removed_row(self):
        p=payload(); p["Master_Index"].pop()
        with self.assertRaises(ValueError): validate(p)

    def test_modified_value(self):
        p=payload(); p["Master_Index"][1][2]="Public-ready"
        with self.assertRaises(ValueError): validate(p)

    def test_missing_completeness(self):
        p=payload(); p["_snapshot_complete"]=False
        with self.assertRaises(ValueError): validate(p)

    def test_changed_header(self):
        p=payload(); p["MRI_Research_Watch"][0][0]="Wrong"
        with self.assertRaises(ValueError): validate(p)

    def test_bad_count_type(self):
        p=payload(); p["_snapshot_envelope"]["tabs"]["Master_Index"]["rows"]=True
        with self.assertRaises(ValueError): validate(p)

    def test_production_rejects_bad_hash_before_csv(self):
        p=payload(); p["Master_Index"][1][2]="Edited"
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"private"
            result=execute(p,{"article_id":"RI-031","state":"SOURCE_BLOCKED","doi":"10.1002/jmri.70589"},
                {},root,require_complete=True)
            self.assertEqual(result["state"],"BLOCKED")
            self.assertFalse((root/"sheets_snapshot").exists())
            self.assertFalse((root/"queue_decision.json").exists())
            self.assertFalse(result["public_write_performed"])

if __name__ == "__main__":
    unittest.main()
