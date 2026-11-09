#!/usr/bin/env python3
"""Native Google Sheets HTTPS values adapter with read-twice consistency.

No XLSX exports, cached files or write access. Supply short-lived Google OAuth
token from a secret manager at runtime. This component cannot claim data was
read from Google when using an injected/mock transport: provenance says how
the caller invoked it, and remote authentication is the transport's duty.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

SHEET_ID="1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM"
RANGES={"Master_Index":"A1:Z1026","MRI_Research_Watch":"A1:S1000"}
SHEET_IDS={"Master_Index":2040869943,"MRI_Research_Watch":778410221}


def _fingerprint(values):
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,
        separators=(",",":"),sort_keys=False).encode("utf-8")).hexdigest()


class NativeSheetsReadError(ValueError):
    pass


class NativeSheetsReader:
    """Read exact canonical native Google Sheets ranges using injected GET."""
    def __init__(self, transport, *, spreadsheet_id=SHEET_ID):
        if spreadsheet_id!=SHEET_ID:
            raise NativeSheetsReadError("UNEXPECTED_CANONICAL_SHEET_ID")
        if not callable(transport):
            raise NativeSheetsReadError("SHEETS_GET_TRANSPORT_REQUIRED")
        self.transport=transport
        self.spreadsheet_id=spreadsheet_id

    def _get(self,url):
        status,data=self.transport(url)
        if status!=200 or not isinstance(data,dict):
            raise NativeSheetsReadError("SHEETS_PROVIDER_READ_FAILED")
        return data

    def read(self):
        base="https://sheets.googleapis.com/v4/spreadsheets/"+self.spreadsheet_id
        meta=self._get(base+"?fields=spreadsheetId,sheets(properties(sheetId,title))")
        if meta.get("spreadsheetId")!=self.spreadsheet_id:
            raise NativeSheetsReadError("SHEETS_METADATA_ID_MISMATCH")
        actual={}
        for sheet in meta.get("sheets",[]):
            props=sheet.get("properties",{})
            if props.get("title") in RANGES:
                actual[props["title"]]=props.get("sheetId")
        if actual!=SHEET_IDS:
            raise NativeSheetsReadError("SHEETS_TAB_ID_MISMATCH")

        def read_once():
            result={}
            for name,cell_range in RANGES.items():
                a1=name+"!"+cell_range
                url=(base+"/values/"+quote(a1,safe="")+
                     "?valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS")
                data=self._get(url)
                if data.get("majorDimension") not in (None,"ROWS"):
                    raise NativeSheetsReadError("SHEETS_MAJOR_DIMENSION_CHANGED")
                if data.get("range","").split("!",1)[0].strip("'")!=name:
                    raise NativeSheetsReadError("SHEETS_RANGE_TAB_MISMATCH")
                values=data.get("values")
                if not isinstance(values,list):
                    raise NativeSheetsReadError("SHEETS_VALUES_MISSING")
                result[name]=values
            return result
        first=read_once()
        second=read_once()
        if any(_fingerprint(first[name])!=_fingerprint(second[name]) for name in RANGES):
            raise NativeSheetsReadError("SHEETS_VALUES_CHANGED_DURING_READ")
        return {
            "status":"NATIVE_PROVIDER_READ_TWICE_CONSISTENT",
            "spreadsheet_id":self.spreadsheet_id,
            "read_ranges":dict(RANGES),
            "tab_ids":dict(actual),
            "values":second,
            "sha256":{name:_fingerprint(second[name]) for name in RANGES},
            "authorization_to_write":False,
            "provider_authentication":"TRANSPORT_RESPONSIBILITY",
            "read_is_not_release_time_lease":True
        }


def google_sheets_readonly_transport(oauth_access_token):
    """Build HTTPS-only read transport; token is not stored or logged."""
    if not isinstance(oauth_access_token,str) or not oauth_access_token.strip():
        raise NativeSheetsReadError("GOOGLE_OAUTH_TOKEN_REQUIRED")
    def get(url):
        if not url.startswith("https://sheets.googleapis.com/v4/spreadsheets/"):
            raise NativeSheetsReadError("NON_GOOGLE_SHEETS_URL")
        req=Request(url,headers={
            "Authorization":"Bearer "+oauth_access_token,
            "Accept":"application/json",
            "User-Agent":"RI-native-sheets-readonly"})
        with urlopen(req,timeout=20) as response:
            return response.status,json.loads(response.read().decode("utf-8"))
    return get
