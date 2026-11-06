import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from research_preview import prepare
class Tests(unittest.TestCase):
    def test_private(self):
        with tempfile.TemporaryDirectory() as d:
            a={"doi":"10.1000/example","title":"T","source_url":"https://example.org","source_facts":"F","interpretation":"I","practical_implication":"P","limitations":"L"}
            r=prepare(a,Path(d))
            self.assertFalse(r["approval_possible"])
            self.assertFalse(r["public_write_permitted"])
            a["article_id"]="RI-032"
            with self.assertRaises(ValueError):prepare(a,Path(d))
if __name__=="__main__":unittest.main()
