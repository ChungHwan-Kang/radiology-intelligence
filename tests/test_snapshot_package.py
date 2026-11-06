import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from snapshot_package import package
from snapshot_integrity import validate

class SnapshotPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.master = [['ID','DOI','Content Stage'],['RI-030','10.1/a','Published']]
        self.watch = [['Title','DOI','RI Article Candidate','Priority','Existing Master ID'],['P-SMART','10.1/b','YES','HIGH','']]

    def test_roundtrip(self):
        p = self.root/'package.json'
        result = package(self.master, self.watch, p)
        self.assertEqual(result['tab_rows']['Master_Index'], 2)
        self.assertEqual(len(validate(json.loads(p.read_text()))['tabs']), 2)
        self.assertFalse(result['source_authentication_verified'])

    def test_repeat_does_not_overwrite(self):
        p = self.root/'package.json'
        package(self.master, self.watch, p)
        before = p.read_bytes()
        with self.assertRaises(ValueError): package(self.master, self.watch, p)
        self.assertEqual(before, p.read_bytes())

    def test_git_dir_refused(self):
        (self.root/'.git').mkdir()
        with self.assertRaises(ValueError): package(self.master, self.watch, self.root/'package.json')

    def test_missing_parent_refused(self):
        with self.assertRaises(ValueError): package(self.master, self.watch, self.root/'missing'/'package.json', require_existing=True)

    def test_array_required(self):
        with self.assertRaises(ValueError): package({}, self.watch, self.root/'package.json')

    def test_missing_header_refused(self):
        with self.assertRaises(ValueError): package([], self.watch, self.root/'package.json')

    def test_bad_header_refused(self):
        with self.assertRaises(ValueError): package([[5,6]], self.watch, self.root/'package.json')

    def test_tamper_detected(self):
        p = self.root/'package.json'
        package(self.master, self.watch, p)
        obj=json.loads(p.read_text());obj['Master_Index'][1][2]='Changed'
        with self.assertRaises(ValueError): validate(obj)

if __name__ == '__main__': unittest.main()
