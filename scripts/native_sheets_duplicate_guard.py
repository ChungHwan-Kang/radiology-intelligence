#!/usr/bin/env python3
"""Fail-closed duplicate and source-integrity guard for native Google Sheets values.

Input must be Google Sheets values arrays (not an XLSX export). This module
performs NO network reads or writes; the caller must fetch current native
values and provide sheet identity/range read provenance independently.
"""
from __future__ import annotations
import re

MASTER_HEADERS={"ID":0,"DOI":10,"Content Stage":14}
WATCH_HEADERS={"DOI":4,"RI Article Candidate":14,"Priority":15,
               "Existing Master ID":16}
PRIORITIES={"HIGH","MEDIUM","LOW"}


def norm_doi(value):
    text=str(value or "").strip().lower()
    text=re.sub(r"^https?://(?:dx\.)?doi\.org/","",text)
    text=re.sub(r"^doi:\s*","",text)
    return text.rstrip(" .,;").strip()


def _check_table(values,cols,requirements,name):
    if not isinstance(values,list) or len(values)<2 or not isinstance(values[0],list):
        raise ValueError(name+"_LIVE_ROWS_REQUIRED")
    header=values[0]
    if len(header)!=cols:
        raise ValueError(name+"_HEADER_WIDTH_INVALID")
    for key,index in requirements.items():
        if header[index]!=key or header.count(key)!=1:
            raise ValueError(name+"_REQUIRED_COLUMN_MISMATCH:"+key)
    for i,row in enumerate(values[1:],2):
        if not isinstance(row,list) or len(row)>cols:
            raise ValueError(name+"_INVALID_ROW:"+str(i))


def build_native_duplicate_guard(master_values,watch_values,article_id,doi,
                                 *,spreadsheet_id,read_ranges):
    """Validate structural fidelity and return one explicit duplicate verdict.

    Never infer that the caller actually read live Sheets merely from the
    spreadsheet ID; the returned result labels provider claims as caller supplied.
    """
    if spreadsheet_id!="1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM":
        raise ValueError("UNEXPECTED_CANONICAL_SHEET_ID")
    if not isinstance(read_ranges,dict) or set(read_ranges)!={"Master_Index","MRI_Research_Watch"}:
        raise ValueError("NATIVE_SHEETS_READ_PROVENANCE_REQUIRED")
    if read_ranges["Master_Index"]!="A1:Z1026" or read_ranges["MRI_Research_Watch"]!="A1:S1000":
        raise ValueError("CANONICAL_NATIVE_RANGE_MISMATCH")
    if not isinstance(article_id,str) or not re.fullmatch(r"RI-[0-9]{3}",article_id):
        raise ValueError("INVALID_ARTICLE_ID")
    candidate=norm_doi(doi)
    if not re.fullmatch(r"10\.\d{4,9}/\S+",candidate):
        raise ValueError("ARTICLE_DOI_INVALID")
    _check_table(master_values,26,MASTER_HEADERS,"MASTER")
    _check_table(watch_values,19,WATCH_HEADERS,"WATCH")
    ids=set()
    dois=set()
    for i,row in enumerate(master_values[1:],2):
        rid=str(row[0]).strip() if row else ""
        if rid:
            if rid in ids: raise ValueError("DUPLICATE_MASTER_ID_ROW:"+str(i))
            ids.add(rid)
        raw_doi=row[10] if len(row)>10 else ""
        d=norm_doi(raw_doi)
        if d:
            if not re.fullmatch(r"10\.\d{4,9}/\S+",d):
                raise ValueError("INVALID_MASTER_DOI_ROW:"+str(i))
            dois.add(d)
    watch_matches=0
    for i,row in enumerate(watch_values[1:],2):
        priority=str(row[15]).strip().upper() if len(row)>15 else ""
        linked=str(row[16]).strip() if len(row)>16 else ""
        if priority and priority not in PRIORITIES:
            raise ValueError("INVALID_WATCH_PRIORITY_ROW:"+str(i))
        if linked and not re.fullmatch(r"RI-[0-9]{3}",linked):
            raise ValueError("INVALID_WATCH_MASTER_LINK_ROW:"+str(i))
        d=norm_doi(row[4] if len(row)>4 else "")
        if d==candidate:
            watch_matches+=1
            if linked:
                raise ValueError("DOI_ALREADY_LINKED_IN_WATCH_ROW:"+str(i))
        if linked==article_id:
            raise ValueError("ARTICLE_ID_ALREADY_LINKED_IN_WATCH_ROW:"+str(i))
    if article_id in ids:
        raise ValueError("ALREADY_IN_MASTER_ID")
    if candidate in dois:
        raise ValueError("ALREADY_IN_MASTER_DOI")
    return {
        "status":"CALLER_NATIVE_SHEETS_DUPLICATE_GUARD_PASS",
        "article_id":article_id,"doi":candidate,
        "master_data_rows":len(master_values)-1,
        "watch_data_rows":len(watch_values)-1,
        "matching_watch_doi_rows":watch_matches,
        "duplicate_master_ids":False,"duplicate_master_dois":False,
        "source_verified_independently":False,
        "provider_read_provenance":"CALLER_DECLARED_NOT_AUTHENTICATED_BY_GUARD",
        "public_write_permitted":False
    }
