#!/usr/bin/env python3
"""Synthetic provider API contract tests; never access user accounts."""
import hashlib
import json
import sys
import os
import unittest
from urllib.parse import unquote
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import native_provider_writeback as p


def metadata():
    return {"article_id":"RI-999","doi":"10.1000/synthetic",
            "title":"Synthetic approval-only test", "source":"Synthetic Journal",
            "source_url":"https://example.org/synthetic",
            "summary":"Mock summary","why_it_matters":"Mock explanation",
            "published_date":"2026-11-15","published_url":"https://example.org/ri-999.html",
            "slug":"ri-999-fixture.html"}


def record(component, html="<html>synthetic</html>"):
    return {"article_id":"RI-999","doi":"10.1000/synthetic",
            "slug":"ri-999-fixture.html",
            "published_url":"https://example.org/ri-999.html",
            "approved_private_sha256":"a"*64,
            "published_html_sha256":hashlib.sha256(html.encode()).hexdigest(),
            "component":component}


class FakeNativeHTTP:
    """Models response shapes for real native endpoints; no network."""
    def __init__(self):
        master=[""]*26
        for k,i in p.REQUIRED_MASTER.items():master[i]=k
        self.master=[master]
        watch=[""]*19
        for k,i in p.REQUIRED_WATCH.items():watch[i]=k
        candidate=[""]*19
        candidate[4]="10.1000/synthetic"
        self.watch=[watch,candidate]
        self.notes={}
        self.drive=None
        self.html=None
        self.docs=""
        self.doc_revision=1
        self.notion=[]
        self.writes=[]
        self.fail_once=None
        self.permission="ok"

    def call(self, provider, method, path, data=None, **kwargs):
        if method!="GET":
            self.writes.append((provider,method,path))
            if self.permission=="deny":raise p.ProviderBlocked("PERMISSION_DENIED")
        if provider=="google" and path.startswith("/sheets/v4/spreadsheets/"):
            if method=="GET":
                if "values/" in path:
                    if "Master_Index" in unquote(path):
                        return {"values":self.master}
                    return {"values":self.watch}
                if "includeGridData" in path:
                    tab="Master_Index" if "Master_Index" in unquote(path) else "MRI_Research_Watch"
                    row=int(unquote(path).split("ranges=")[1].split("%")[0].split("A")[-1].split("Q")[-1].split("&")[0]) if False else None
                    # URL parameters decode into 'Master_Index!A2'
                    import re
                    match=re.search(r"(?:A|Q)(\d+)",unquote(path))
                    row=int(match.group(1)) if match else 0
                    note=self.notes.get((tab,row),"")
                    return {"sheets":[{"data":[{"rowData":[{"values":[{"note":note}]}]}]}]}
                return {"spreadsheetId":p.SHEET_ID,
                        "sheets":[{"properties":{"title":"Master_Index","sheetId":p.MASTER_TAB}},
                                  {"properties":{"title":"MRI_Research_Watch","sheetId":p.WATCH_TAB}}]}
            if ":batchUpdate" in path:
                op=data["requests"][0]
                if "appendCells" in op:
                    cells=op["appendCells"]["rows"][0]["values"]
                    self.master.append([v["userEnteredValue"]["stringValue"] for v in cells])
                    self.notes[("Master_Index",len(self.master))]=cells[0]["note"]
                else:
                    q=op["updateCells"]
                    row=q["start"]["rowIndex"]+1
                    self.watch[row-1][16]=q["rows"][0]["values"][0]["userEnteredValue"]["stringValue"]
                    self.notes[("MRI_Research_Watch",row)]=q["rows"][0]["values"][0]["note"]
                return {"replies":[{}]}
        if provider=="google" and path.startswith("/drive/v3/"):
            if path.startswith("/drive/v3/files/"+p.DRIVE_FOLDER):
                return {"id":p.DRIVE_FOLDER,"mimeType":"application/vnd.google-apps.folder"}
            if path.startswith("/drive/v3/files?"):
                return {"files":[self.drive] if self.drive is not None else []}
            if "alt=media" in path:
                return self.html
        if provider=="google" and path.startswith("/upload/drive/v3/"):
            raw=data
            head=raw.split(b"\r\n\r\n",1)[1]
            props=json.loads(head.split(b"\r\n--ri-release-boundary",1)[0])
            html=raw.split(b"Content-Type: text/html; charset=UTF-8\r\n\r\n",1)[1].split(b"\r\n--ri-release-boundary--",1)[0]
            self.drive={"id":"f1","name":props["name"],"description":props["description"],
                        "mimeType":props["mimeType"],"appProperties":props["appProperties"],"parents":props["parents"]}
            self.html=html
            return {"id":"f1"}
        if provider=="google" and path.startswith("/docs/v1/"):
            if method=="GET":
                return {"documentId":p.HANDOFF_DOC,"revisionId":"v"+str(self.doc_revision),
                        "tabs":[{"documentTab":{"body":{"content":[{"paragraph":{"elements":[{"textRun":{"content":self.docs}}]}}]}}}]}
            if method=="POST":
                if data["writeControl"]["requiredRevisionId"]!="v"+str(self.doc_revision):
                    raise p.ProviderBlocked("REVISION_CONFLICT")
                self.docs+=data["requests"][0]["insertText"]["text"]
                self.doc_revision+=1
                return {"documentId":p.HANDOFF_DOC,"revisionId":"v"+str(self.doc_revision)}
        if provider=="notion":
            if method=="GET" and path.startswith("/v1/pages/"):
                return {"id":p.NOTION_PAGE}
            if method=="GET" and path.startswith("/v1/blocks/"):
                return {"results":self.notion,"has_more":False}
            if method=="PATCH":
                self.notion+=data["children"]
                return {"results":self.notion}
        raise AssertionError("UNEXPECTED_PROVIDER_API_CALL "+str((provider,method,path)))


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeNativeHTTP()
        self.html="<html>synthetic</html>"
        self.adapter=p.NativeProviderAdapter(self.api,metadata(),self.html,
                  write_enabled=True,exclusive_writer_attested=True)

    def test_five_native_records_roundtrip(self):
        state=self.adapter.assert_ready(p.RECORD_COMPONENTS)
        self.assertEqual(state["status"],"ALL_TARGETS_READ_WRITE_READY")
        self.assertFalse(state["actual_write_scopes_verified"])
        for component in p.RECORD_COMPONENTS:
            expected=record(component)
            self.assertIsNone(self.adapter.read(component,"RI-999"))
            self.adapter.create(component,expected,expected_absent=True)
            saved=self.adapter.read(component,"RI-999")
            self.assertEqual(saved["record"],expected)
            self.assertTrue(saved["evidence_ref"])

    def test_readonly_default_blocks_mutations(self):
        locked=p.NativeProviderAdapter(self.api,metadata(),self.html)
        with self.assertRaisesRegex(p.ProviderBlocked,"LIVE_WRITE_DISABLED"):
            locked.assert_ready(p.RECORD_COMPONENTS)
        with self.assertRaisesRegex(p.ProviderBlocked,"NONCONDITIONAL"):
            locked.create("sheets_master",record("sheets_master"))
        self.assertFalse(self.api.writes)

    def test_exclusive_writer_required(self):
        locked=p.NativeProviderAdapter(self.api,metadata(),self.html,write_enabled=True)
        with self.assertRaisesRegex(p.ProviderBlocked,"SINGLE_WRITER"):
            locked.assert_ready(p.RECORD_COMPONENTS)

    def test_watch_no_matching_doi_fails_without_write(self):
        self.api.watch=self.api.watch[:1]
        with self.assertRaisesRegex(p.ProviderBlocked,"WATCH_DOI_ROW_NOT_UNIQUE"):
            self.adapter.read("sheets_watch","RI-999")
        self.assertFalse(self.api.writes)

    def test_master_other_doi_owner_blocks(self):
        other=[""]*26
        other[0]="RI-123";other[10]="10.1000/synthetic"
        self.api.master.append(other)
        with self.assertRaisesRegex(p.ProviderBlocked,"MASTER_DOI_ALREADY_OWNED"):
            self.adapter.read("sheets_master","RI-999")

    def test_watch_existing_other_article_blocks(self):
        self.api.watch[1][16]="RI-321"
        with self.assertRaisesRegex(p.ProviderBlocked,"WATCH_LINKED_TO_ANOTHER_ARTICLE"):
            self.adapter.read("sheets_watch","RI-999")

    def test_existing_record_does_not_get_overwritten(self):
        self.adapter.create("sheets_master",record("sheets_master"))
        before=len(self.api.writes)
        with self.assertRaisesRegex(p.ProviderBlocked,"ALREADY_PRESENT"):
            self.adapter.create("sheets_master",record("sheets_master"))
        self.assertEqual(len(self.api.writes),before)

    def test_no_secret_or_token_creation(self):
        with self.assertRaisesRegex(p.ProviderBlocked,"EXISTING_GOOGLE_TOKEN_REQUIRED"):
            p.NativeHTTP("","notion")
        with self.assertRaisesRegex(p.ProviderBlocked,"EXISTING_NOTION_TOKEN_REQUIRED"):
            p.NativeHTTP("google","")

    def test_token_transport_native_hosts(self):
        seen=[]
        def transport(method,url,headers,body):
            seen.append((url,headers.get("Authorization"),headers.get("Notion-Version")))
            return 200,{"ok":True}
        http=p.NativeHTTP("existingGoogle","existingNotion",transport)
        http.call("google","GET","/sheets/v4/spreadsheets/abc")
        http.call("google","GET","/docs/v1/documents/abc")
        http.call("google","GET","/drive/v3/files/abc")
        http.call("notion","GET","/v1/pages/abc")
        self.assertEqual([x[0].split("/")[2] for x in seen],
                         ["sheets.googleapis.com","docs.googleapis.com",
                          "www.googleapis.com","api.notion.com"])
        self.assertEqual(seen[-1][2],"2022-06-28")

    def test_published_html_hash_lock(self):
        wrong=record("sheets_master")
        wrong["published_html_sha256"]="0"*64
        with self.assertRaisesRegex(p.ProviderBlocked,"APPROVED_HTML_CONTENT_MISMATCH"):
            self.adapter.create("sheets_master",wrong)

    def test_no_extra_component(self):
        with self.assertRaisesRegex(p.ProviderBlocked,"INCOMPLETE_RECORD_COMPONENTS"):
            self.adapter.assert_ready(["sheets_master"])

    def test_permissions_failure_not_suppressed(self):
        self.api.permission="deny"
        with self.assertRaisesRegex(p.ProviderBlocked,"PERMISSION_DENIED"):
            self.adapter.create("sheets_master",record("sheets_master"))

    def test_notion_receipt_is_idempotent(self):
        self.adapter.create("notion",record("notion"))
        self.assertEqual(len(self.api.notion),1)
        with self.assertRaisesRegex(p.ProviderBlocked,"ALREADY_PRESENT"):
            self.adapter.create("notion",record("notion"))
        self.assertEqual(len(self.api.notion),1)


if __name__=="__main__":
    unittest.main()
