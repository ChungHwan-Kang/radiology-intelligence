#!/usr/bin/env python3
"""Native Google/Notion writeback adapter for the existing RI canonical resources.

Calls real provider APIs when a trusted existing runner injects bearer tokens.
There is no OAuth flow, token storage, scheduler or default write permission.
The instance is DISABLED for writes unless explicitly constructed with
write_enabled=True by the already-authorized *article-specific* runner.

Remote notes/receipts carry the exact release identity; Sheets' public-facing
columns retain their canonical meanings. Google/Notion API responses are
re-read before acceptance. An externally controlled single-writer lock is
still necessary: Google Sheets has no cross-provider atomic transaction.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

from connected_publication_coordinator import RECORD_COMPONENTS
from native_sheets_duplicate_guard import norm_doi

SHEET_ID = "1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM"
MASTER_TAB = 2040869943
WATCH_TAB = 778410221
DRIVE_FOLDER = "1JUcX0CFQQ_58yfR_V421ZPCWKGlUBmC7"
HANDOFF_DOC = "1_aM43wzoe_TjJDnKQ3Bjyp-6h1vz5bu-B6im4kyLQDQ"
NOTION_PAGE = "3ef7d7d3-2971-8174-ba40-e64573f6931f"
MARKER = "RI_APPROVED_RELEASE_RECEIPT:"
REQUIRED_MASTER = {"ID":0, "Title":2, "DOI":10, "Review Status":12,
                   "Content Stage":14, "Published URL":19, "Distribution QA":25}
REQUIRED_WATCH = {"DOI":4, "Existing Master ID":16}
EXPECTED_MASTER_WIDTH, EXPECTED_WATCH_WIDTH = 26, 19
WRITE_SCOPE_ATTESTATION = "RI_EXISTING_PROVIDER_WRITE_SCOPES_V1"


class ProviderBlocked(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False)


def _note(record):
    return MARKER + _json(record)


def _from_note(text):
    if not isinstance(text, str) or not text.startswith(MARKER):
        raise ProviderBlocked("MISSING_APPROVED_RELEASE_RECEIPT")
    value=json.loads(text[len(MARKER):])
    if not isinstance(value, dict):
        raise ProviderBlocked("INVALID_APPROVED_RELEASE_RECEIPT")
    return value


def _q(s):
    return quote(str(s), safe="")


def _cell(value):
    return {"userEnteredValue": {"stringValue": str(value)}}


def _text(obj):
    """Concatenate content from Google Docs API document elements."""
    found=[]
    def walk(x):
        if isinstance(x, dict):
            if "textRun" in x and isinstance(x["textRun"],dict):
                found.append(x["textRun"].get("content",""))
            for k,v in x.items():
                if k!="textRun":
                    walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(obj)
    return "".join(found)


class NativeHTTP:
    """No ambient credentials: only explicitly injected, existing tokens."""
    def __init__(self, google_token, notion_token, transport=None):
        if not isinstance(google_token,str) or not google_token.strip():
            raise ProviderBlocked("EXISTING_GOOGLE_TOKEN_REQUIRED")
        if not isinstance(notion_token,str) or not notion_token.strip():
            raise ProviderBlocked("EXISTING_NOTION_TOKEN_REQUIRED")
        self.google_token = google_token
        self.notion_token = notion_token
        self.transport = transport or self._request

    @staticmethod
    def _request(method, url, headers, body):
        request = Request(url, data=body, method=method, headers=headers)
        class NoCrossHostRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, newurl):
                # Prevent leaking Google/Notion bearer tokens through redirects.
                return None
        try:
            with build_opener(NoCrossHostRedirect).open(request, timeout=25) as response:
                payload=response.read()
                content_type=response.headers.get("Content-Type","")
                if "application/json" in content_type:
                    return response.status, json.loads(payload)
                return response.status, payload
        except HTTPError as exc:
            # Return status, not remote bodies that might contain sensitive data.
            return exc.code, {}

    def call(self, provider, method, path, data=None, *, raw=False, content_type=None):
        if provider not in ("google","notion"):
            raise ProviderBlocked("UNKNOWN_PROVIDER")
        base = ("https://www.googleapis.com" if provider=="google"
                else "https://api.notion.com")
        if not isinstance(path,str) or not path.startswith("/"):
            raise ProviderBlocked("INVALID_API_PATH")
        # Strict public Google/Notion APIs only; no arbitrary host or redirect
        # instructions from source materials.
        if provider=="google":
            if not path.startswith(("/sheets/v4/","/drive/v3/","/upload/drive/v3/",
                                    "/docs/v1/")):
                raise ProviderBlocked("GOOGLE_API_PATH_DENIED")
            token=self.google_token
        else:
            if not path.startswith("/v1/"):
                raise ProviderBlocked("NOTION_API_PATH_DENIED")
            token=self.notion_token
        if provider=="google" and path.startswith("/sheets/"):
            base="https://sheets.googleapis.com"
            path=path[len("/sheets"):]
        elif provider=="google" and path.startswith("/docs/"):
            base="https://docs.googleapis.com"
            path=path[len("/docs"):]
        headers={"Authorization":"Bearer "+token,
                 "Accept":"application/json",
                 "User-Agent":"RI-existing-connector-runtime"}
        if provider=="notion":
            headers["Notion-Version"]="2022-06-28"
        if content_type:
            headers["Content-Type"]=content_type
        elif data is not None and not raw:
            headers["Content-Type"]="application/json; charset=utf-8"
        body=(data if raw else _json(data).encode("utf-8") if data is not None else None)
        status, result=self.transport(method, base+path, headers, body)
        if status<200 or status>=300:
            raise ProviderBlocked(provider.upper()+"_HTTP_"+str(status))
        if not raw and not isinstance(result,dict):
            raise ProviderBlocked("INVALID_PROVIDER_RESPONSE")
        return result


class NativeProviderAdapter:
    """Map existing five coordinator components to provider-native resources.

    It never infers Google/Notion write permission from a successful GET. The
    caller must inject existing tokens, configure an external single-writer
    lease, and explicitly enable write. That is not article approval.
    """
    def __init__(self, http, article_metadata, approved_public_html, *,
                 write_enabled=False, exclusive_writer_attested=False,
                 write_scope_attestation=None):
        self.http=http
        self.metadata=article_metadata
        self.html=approved_public_html
        self.write_enabled=(write_enabled is True)
        # An external cross-client lease and this process's private journal
        # lock are different controls. The durable runner may set only the
        # latter; it must never manufacture the former.
        self.external_single_writer_attested=(exclusive_writer_attested is True)
        self.local_lock_held=False
        self.write_scope_attestation=write_scope_attestation
        if not isinstance(article_metadata,dict) or not isinstance(approved_public_html,str):
            raise ProviderBlocked("APPROVED_SOURCE_METADATA_AND_HTML_REQUIRED")
        for key in ("article_id","doi","title","source","source_url","summary",
                    "why_it_matters","published_date","published_url","slug"):
            if not isinstance(article_metadata.get(key),str) or not article_metadata[key].strip():
                raise ProviderBlocked("MISSING_CANONICAL_METADATA:"+key)
        if not re.fullmatch(r"RI-[0-9]{3}",article_metadata["article_id"]):
            raise ProviderBlocked("INVALID_ARTICLE_ID")
        self._last_master_read=None

    def _write_scope_verified(self):
        value=self.write_scope_attestation
        if value is None:
            return False
        expected_resources={
            "spreadsheet":SHEET_ID,
            "drive_folder":DRIVE_FOLDER,
            "handoff_document":HANDOFF_DOC,
            "notion_page":NOTION_PAGE,
        }
        if (not isinstance(value,dict)
            or value.get("status")!=WRITE_SCOPE_ATTESTATION
            or value.get("article_id")!=self.metadata["article_id"]
            or set(value.get("components",[]))!=set(RECORD_COMPONENTS)
            or value.get("resources")!=expected_resources
            or not isinstance(value.get("evidence_ref"),str)
            or not value["evidence_ref"].strip()):
            raise ProviderBlocked("WRITE_SCOPE_ATTESTATION_INVALID")
        return True

    def _ensure_record(self, component, record):
        if component not in RECORD_COMPONENTS:
            raise ProviderBlocked("UNKNOWN_RECORD_COMPONENT")
        if not isinstance(record,dict):
            raise ProviderBlocked("RELEASE_RECORD_REQUIRED")
        if record.get("article_id")!=self.metadata["article_id"]:
            raise ProviderBlocked("ARTICLE_METADATA_ID_MISMATCH")
        if record.get("doi","").lower()!=self.metadata["doi"].lower():
            raise ProviderBlocked("ARTICLE_METADATA_DOI_MISMATCH")
        if record.get("component")!=component:
            raise ProviderBlocked("RELEASE_COMPONENT_MISMATCH")
        if record.get("slug")!=self.metadata["slug"] or record.get("published_url")!=self.metadata["published_url"]:
            raise ProviderBlocked("RELEASE_TARGET_METADATA_MISMATCH")
        digest=record.get("approved_private_sha256")
        if not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}",digest):
            raise ProviderBlocked("INVALID_APPROVAL_DIGEST")
        if record.get("published_html_sha256")!=hashlib.sha256(self.html.encode("utf-8")).hexdigest():
            raise ProviderBlocked("APPROVED_HTML_CONTENT_MISMATCH")

    def _values(self, name, width):
        a1=(name+"!A1:"+("Z1026" if width==26 else "S1000"))
        obj=self.http.call("google","GET", "/sheets/v4/spreadsheets/"+SHEET_ID+
            "/values/"+_q(a1)+"?valueRenderOption=FORMATTED_VALUE")
        values=obj.get("values",[])
        if not values or not isinstance(values[0],list) or len(values[0])!=width:
            raise ProviderBlocked("CANONICAL_SHEET_WIDTH_CHANGED:"+name)
        expected=REQUIRED_MASTER if width==26 else REQUIRED_WATCH
        for key,index in expected.items():
            if values[0][index]!=key or values[0].count(key)!=1:
                raise ProviderBlocked("CANONICAL_HEADER_CHANGED:"+key)
        return values

    def _sheet_note(self, name, row):
        a1=name+"!"+("A" if name=="Master_Index" else "Q")+str(row)
        query=urlencode({"ranges":a1,"includeGridData":"true",
                         "fields":"sheets(data(rowData(values(note))))"})
        obj=self.http.call("google","GET","/sheets/v4/spreadsheets/"+
                           SHEET_ID+"?"+query)
        try:
            return obj["sheets"][0]["data"][0]["rowData"][0]["values"][0].get("note","")
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _matching_rows(values, index, needle):
        return [(i,row) for i,row in enumerate(values[1:],2)
                if len(row)>index and (
                    norm_doi(row[index])==norm_doi(needle) if index in (4,10)
                    else str(row[index]).strip().lower()==needle.lower())]

    def _master(self, article_id):
        values=self._values("Master_Index",26)
        ids=self._matching_rows(values,0,article_id)
        doi=self.metadata["doi"].lower()
        doi_rows=self._matching_rows(values,10,doi)
        if len(ids)>1 or len(doi_rows)>1:
            raise ProviderBlocked("DUPLICATE_MASTER_REMOTE")
        if doi_rows and (not ids or doi_rows[0][0]!=ids[0][0]):
            raise ProviderBlocked("MASTER_DOI_ALREADY_OWNED")
        if not ids:
            return None
        i,row=ids[0]
        if len(row)<=19 or norm_doi(row[10])!=norm_doi(doi) or row[14]!="Published" or row[19] != self.metadata["published_url"]:
            raise ProviderBlocked("MASTER_RECORD_CONFLICT")
        return {"record":_from_note(self._sheet_note("Master_Index",i)),
                "revision":"row:"+str(i),"evidence_ref":"https://docs.google.com/spreadsheets/d/"+SHEET_ID+"/edit#gid="+str(MASTER_TAB)+"&range=A"+str(i)}

    def _watch(self, article_id):
        values=self._values("MRI_Research_Watch",19)
        matches=self._matching_rows(values,4,self.metadata["doi"])
        if len(matches)!=1:
            raise ProviderBlocked("WATCH_DOI_ROW_NOT_UNIQUE")
        i,row=matches[0]
        current=row[16].strip() if len(row)>16 else ""
        if current and current != article_id:
            raise ProviderBlocked("WATCH_LINKED_TO_ANOTHER_ARTICLE")
        if not current:
            return None
        return {"record":_from_note(self._sheet_note("MRI_Research_Watch",i)),
                "revision":"row:"+str(i),"evidence_ref":"https://docs.google.com/spreadsheets/d/"+SHEET_ID+"/edit#gid="+str(WATCH_TAB)+"&range=Q"+str(i)}

    def _drive_name(self):
        return self.metadata["article_id"]+"_"+self.metadata["slug"] if self.metadata.get("slug") else self.metadata["article_id"]+"_approved_publication.html"

    def _drive_matches(self):
        name=self._drive_name()
        quoted=name.replace("\\","\\\\").replace("'","\\'")
        query=urlencode({"q":"'"+DRIVE_FOLDER+"' in parents and name = '"+quoted+"' and trashed = false",
                         "fields":"nextPageToken,files(id,name,mimeType,description,appProperties,parents)",
                         "page_size":"100"})
        items=self.http.call("google","GET","/drive/v3/files?"+query)
        if items.get("nextPageToken"):
            raise ProviderBlocked("DRIVE_RESULT_PAGINATION_UNRESOLVED")
        found=items.get("files",[])
        if len(found)>1:
            raise ProviderBlocked("DUPLICATE_DRIVE_COPY")
        return found[0] if found else None

    def _drive(self, article_id):
        item=self._drive_matches()
        if item is None:
            return None
        prop=item.get("appProperties",{})
        if prop.get("ri_article_id")!=article_id or prop.get("ri_html_sha256")!=hashlib.sha256(self.html.encode()).hexdigest():
            raise ProviderBlocked("DRIVE_FILE_IDENTITY_CONFLICT")
        raw=self.http.call("google","GET","/drive/v3/files/"+_q(item["id"])+"?alt=media",raw=True)
        if not isinstance(raw,(bytes,bytearray)) or hashlib.sha256(raw).hexdigest()!=prop["ri_html_sha256"]:
            raise ProviderBlocked("DRIVE_CONTENT_READBACK_MISMATCH")
        return {"record":_from_note(item.get("description","")),
                "revision":item["id"],"evidence_ref":"https://drive.google.com/file/d/"+item["id"]+"/view"}

    def _doc_text(self):
        obj=self.http.call("google","GET", "/docs/v1/documents/"+HANDOFF_DOC+"?includeTabsContent=true")
        return obj,_text(obj.get("tabs",obj.get("body",{})))

    def _doc(self, article_id):
        _,body=self._doc_text()
        matches=[line[len(MARKER):].strip() for line in body.splitlines() if line.startswith(MARKER)]
        records=[]
        for match in matches:
            row=_from_note(MARKER+match)
            if row.get("article_id")==article_id and row.get("component")=="current_handoff":
                records.append(row)
        if len(records)>1:
            raise ProviderBlocked("DUPLICATE_HANDOFF_RECEIPT")
        return ({"record":records[0],"revision":"document",
                 "evidence_ref":"https://docs.google.com/document/d/"+HANDOFF_DOC+"/edit"}
                if records else None)

    def _notion_blocks(self):
        cursor=None
        while True:
            suffix="?page_size=100"+("&start_cursor="+_q(cursor) if cursor else "")
            obj=self.http.call("notion","GET","/v1/blocks/"+NOTION_PAGE+"/children"+suffix)
            for block in obj.get("results",[]):
                yield block
            if not obj.get("has_more"): break
            cursor=obj.get("next_cursor")
            if not cursor:
                raise ProviderBlocked("NOTION_PAGINATION_UNRESOLVED")

    def _notion(self, article_id):
        rows=[]
        for block in self._notion_blocks():
            if block.get("type")!="paragraph": continue
            rich=block.get("paragraph",{}).get("rich_text",[])
            content="".join(part.get("plain_text",part.get("text",{}).get("content","")) for part in rich)
            if not content.startswith(MARKER): continue
            row=_from_note(content)
            if row.get("article_id")==article_id and row.get("component")=="notion":
                rows.append((row,block.get("id")))
        if len(rows)>1:
            raise ProviderBlocked("DUPLICATE_NOTION_RECEIPT")
        return ({"record":rows[0][0],"revision":rows[0][1],
                 "evidence_ref":"https://www.notion.so/"+NOTION_PAGE.replace("-","")}
                if rows else None)

    def read(self, component, article_id):
        if component not in RECORD_COMPONENTS or article_id!=self.metadata["article_id"]:
            raise ProviderBlocked("READ_IDENTITY_MISMATCH")
        return {
            "sheets_master":self._master, "sheets_watch":self._watch,
            "drive_published_copy":self._drive, "current_handoff":self._doc,
            "notion":self._notion,
        }[component](article_id)

    def assert_ready(self, components):
        if set(components)!=set(RECORD_COMPONENTS):
            raise ProviderBlocked("INCOMPLETE_RECORD_COMPONENTS")
        if not self.write_enabled:
            raise ProviderBlocked("LIVE_WRITE_DISABLED")
        if not self.external_single_writer_attested:
            raise ProviderBlocked("EXTERNAL_SINGLE_WRITER_LEASE_REQUIRED")
        # Provider GET checks identity, but cannot attest the tokens' write scopes.
        metadata=self.http.call("google","GET","/sheets/v4/spreadsheets/"+SHEET_ID+
                                "?fields=spreadsheetId,sheets(properties(sheetId,title))")
        tabs={x.get("properties",{}).get("title"):x.get("properties",{}).get("sheetId")
              for x in metadata.get("sheets",[])}
        if metadata.get("spreadsheetId")!=SHEET_ID or tabs.get("Master_Index")!=MASTER_TAB or tabs.get("MRI_Research_Watch")!=WATCH_TAB:
            raise ProviderBlocked("SHEETS_CANONICAL_ID_MISMATCH")
        self._values("Master_Index",26)
        self._values("MRI_Research_Watch",19)
        folder=self.http.call("google","GET","/drive/v3/files/"+DRIVE_FOLDER+"?fields=id,mimeType")
        if folder.get("id")!=DRIVE_FOLDER or folder.get("mimeType")!="application/vnd.google-apps.folder":
            raise ProviderBlocked("DRIVE_PUBLISHED_FOLDER_MISMATCH")
        handoff=self.http.call("google","GET","/docs/v1/documents/"+HANDOFF_DOC+"?fields=documentId,revisionId")
        if handoff.get("documentId")!=HANDOFF_DOC:
            raise ProviderBlocked("HANDOFF_DOCUMENT_ID_MISMATCH")
        notion=self.http.call("notion","GET","/v1/pages/"+NOTION_PAGE)
        if str(notion.get("id","")).replace("-","")!=NOTION_PAGE.replace("-",""):
            raise ProviderBlocked("NOTION_PAGE_MISMATCH")
        scopes=self._write_scope_verified()
        ready=scopes and self.local_lock_held
        # Successful GETs cannot demonstrate permission to modify any
        # provider. Only a separately obtained, exact-resource attestation may
        # promote this adapter, and the durable local lock must already exist.
        return {
            "status":("ALL_TARGETS_READ_WRITE_READY" if ready
                      else "READ_ONLY_PREFLIGHT_PASS_WRITE_SCOPE_UNVERIFIED"),
            "components":list(RECORD_COMPONENTS),
            "actual_write_scopes_verified":bool(scopes),
            "caller_single_writer_lease_attested":bool(
                self.external_single_writer_attested and self.local_lock_held),
            "write_scope_evidence_ref":(
                self.write_scope_attestation.get("evidence_ref") if scopes else None),
        }

    def create(self, component, record, expected_absent=True):
        if (not self.write_enabled or not self.external_single_writer_attested
            or not self.local_lock_held or not self._write_scope_verified()
            or expected_absent is not True):
            raise ProviderBlocked("NONCONDITIONAL_PROVIDER_WRITE_DENIED")
        self._ensure_record(component,record)
        if self.read(component,record["article_id"]) is not None:
            raise ProviderBlocked("PROVIDER_RECORD_ALREADY_PRESENT")
        methods={"sheets_master":self._write_master,"sheets_watch":self._write_watch,
                 "drive_published_copy":self._write_drive,
                 "current_handoff":self._write_doc,"notion":self._write_notion}
        return methods[component](record)

    def _write_master(self, record):
        values=self._values("Master_Index",26)
        if self._matching_rows(values,0,record["article_id"]) or self._matching_rows(values,10,record["doi"]):
            raise ProviderBlocked("MASTER_DUPLICATE_BEFORE_APPEND")
        m=self.metadata
        row=[""]*26
        for idx,val in {0:record["article_id"],1:m["published_date"],2:m["title"],
                        3:m["source"],4:m["source_url"],7:m.get("evidence_type","research"),
                        8:m["summary"],9:m["why_it_matters"],10:record["doi"],
                        11:"NO",12:"Published",14:"Published",15:record["published_url"],
                        17:"No",18:m["published_date"],19:record["published_url"],
                        20:m["published_date"],21:"Not started",25:"LIVE_RENDER_QA_PASS"}.items():
            row[idx]=str(val)
        rows=[_cell(x) for x in row]
        rows[0]["note"]=_note(record)
        request={"requests":[{"appendCells":{"sheetId":MASTER_TAB,
            "rows":[{"values":rows}],"fields":"userEnteredValue,note"}}]}
        return self.http.call("google","POST","/sheets/v4/spreadsheets/"+SHEET_ID+":batchUpdate",request)

    def _write_watch(self,record):
        values=self._values("MRI_Research_Watch",19)
        matches=self._matching_rows(values,4,record["doi"])
        if len(matches)!=1 or (len(matches[0][1])>16 and matches[0][1][16].strip()):
            raise ProviderBlocked("WATCH_ROW_NOT_SAFE_TO_LINK")
        row=matches[0][0]-1
        request={"requests":[{"updateCells":{
            "start":{"sheetId":WATCH_TAB,"rowIndex":row,"columnIndex":16},
            "rows":[{"values":[{**_cell(record["article_id"]),"note":_note(record)}]}],
            "fields":"userEnteredValue,note"}}]}
        return self.http.call("google","POST","/sheets/v4/spreadsheets/"+SHEET_ID+":batchUpdate",request)

    def _write_drive(self,record):
        boundary="ri-release-boundary"
        attrs={"name":self._drive_name(),"parents":[DRIVE_FOLDER],
               "mimeType":"text/html",
               "description":_note(record),
               "appProperties":{"ri_article_id":record["article_id"],
                                "ri_html_sha256":record["published_html_sha256"]}}
        payload=("--"+boundary+"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"+
                 _json(attrs)+"\r\n--"+boundary+
                 "\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n").encode("utf-8") + self.html.encode("utf-8") + ("\r\n--"+boundary+"--\r\n").encode()
        return self.http.call("google","POST",
            "/upload/drive/v3/files?uploadType=multipart&fields=id,appProperties",
            payload,raw=True,content_type="multipart/related; boundary="+boundary)

    def _write_doc(self,record):
        obj,body=self._doc_text()
        if _note(record) in body:
            raise ProviderBlocked("HANDOFF_DUPLICATE_BEFORE_APPEND")
        rev=obj.get("revisionId")
        if not rev:
            raise ProviderBlocked("DOC_REVISION_REQUIRED")
        request={"requests":[{"insertText":{
             "endOfSegmentLocation":{"tabId":"t.0"},
             "text":"\n"+_note(record)+"\n"}}],
             "writeControl":{"requiredRevisionId":rev}}
        return self.http.call("google","POST","/docs/v1/documents/"+HANDOFF_DOC+":batchUpdate",request)

    def _write_notion(self,record):
        text=_note(record)
        if len(text)>1900:
            raise ProviderBlocked("NOTION_RECEIPT_TOO_LONG")
        data={"children":[{"object":"block","type":"paragraph",
                "paragraph":{"rich_text":[{"type":"text","text":{"content":text}}]}}]}
        return self.http.call("notion","PATCH","/v1/blocks/"+NOTION_PAGE+"/children",data)
