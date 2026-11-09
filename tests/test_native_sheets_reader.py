import copy
import unittest
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from native_sheets_reader import NativeSheetsReader, NativeSheetsReadError, SHEET_ID, RANGES, SHEET_IDS, google_sheets_readonly_transport

class FakeNativeProvider:
    def __init__(self):
        m=["x"+str(i) for i in range(26)]
        for name,i in (("ID",0),("DOI",10),("Content Stage",14)): m[i]=name
        w=["x"+str(i) for i in range(19)]
        for name,i in (("DOI",4),("RI Article Candidate",14),("Priority",15),("Existing Master ID",16)): w[i]=name
        self.data={"Master_Index":[m,["RI-030"]+[""]*25],
                   "MRI_Research_Watch":[w,[""]*4+["10.1000/new"]+[""]*9+["YES","HIGH","","Indexed","2026-11-09"]]}
        self.calls=[]
        self.change_second_watch=False
        self.wrong_metadata=False
        self.wrong_range=False
    def __call__(self,url):
        self.calls.append(url)
        if "/values/" not in url:
            return 200,{"spreadsheetId":SHEET_ID,"sheets":[{"properties":{
                "title":name,"sheetId":id+int(self.wrong_metadata)}} for name,id in SHEET_IDS.items()]}
        a1=unquote(urlsplit(url).path.split("/values/",1)[1])
        name,rg=a1.split("!",1)
        if self.change_second_watch and name=="MRI_Research_Watch" and sum("/values/" in u and "MRI_Research_Watch" in u for u in self.calls)==2:
            self.data[name][1][15]="LOW"
        return 200,{"range":("Wrong" if self.wrong_range else name)+"!"+rg,"majorDimension":"ROWS","values":copy.deepcopy(self.data[name])}

class ProviderReadTests(unittest.TestCase):
    def setUp(self):
        self.provider=FakeNativeProvider()
        self.reader=NativeSheetsReader(self.provider)
    def test_reads_native_metadata_and_each_range_twice(self):
        r=self.reader.read()
        self.assertEqual(r["status"],"NATIVE_PROVIDER_READ_TWICE_CONSISTENT")
        self.assertEqual(r["tab_ids"],SHEET_IDS)
        self.assertEqual(r["read_ranges"],RANGES)
        self.assertEqual(len(r["sha256"]["Master_Index"]),64)
        self.assertEqual(len(self.provider.calls),5)
        self.assertFalse(r["authorization_to_write"])
        self.assertTrue(r["read_is_not_release_time_lease"])
        self.assertTrue(all("sheets.googleapis.com/v4/spreadsheets" in u for u in self.provider.calls))
    def test_changed_native_values_fail_closed(self):
        self.provider.change_second_watch=True
        with self.assertRaisesRegex(NativeSheetsReadError,"SHEETS_VALUES_CHANGED_DURING_READ"):
            self.reader.read()
    def test_tab_id_mismatch_fail_closed(self):
        self.provider.wrong_metadata=True
        with self.assertRaisesRegex(NativeSheetsReadError,"SHEETS_TAB_ID_MISMATCH"):
            self.reader.read()
    def test_source_range_mismatch_fail_closed(self):
        self.provider.wrong_range=True
        with self.assertRaisesRegex(NativeSheetsReadError,"SHEETS_RANGE_TAB_MISMATCH"):
            self.reader.read()
    def test_no_bogus_source_id_allowed(self):
        with self.assertRaisesRegex(NativeSheetsReadError,"UNEXPECTED_CANONICAL_SHEET_ID"):
            NativeSheetsReader(self.provider,spreadsheet_id="other")
    def test_no_token_fails_without_request(self):
        with self.assertRaisesRegex(NativeSheetsReadError,"GOOGLE_OAUTH_TOKEN_REQUIRED"):
            google_sheets_readonly_transport("")
if __name__=="__main__": unittest.main()
