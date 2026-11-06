#!/usr/bin/env python3
"""Offline RI two-tab queue. Never writes to publishing systems."""
from __future__ import annotations
import argparse,csv,json,re,sys
from pathlib import Path

def norm_doi(value):
    value=(value or "").strip().lower()
    value=re.sub(r"^https?://(?:dx\.)?doi\.org/","",value)
    value=re.sub(r"^doi:\s*","",value)
    return value.rstrip("/").split("?")[0]

def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def select(master,watch,active,source_states):
    protected_dois=set()
    protected_titles=set()
    for item in master:
        status=(item.get("Content Stage") or item.get("Status") or "").strip().lower()
        if status in {"published","approved","approval_pending","public-ready","hold","active","draft"}:
            doi=norm_doi(item.get("DOI",""))
            if doi: protected_dois.add(doi)
            title=(item.get("Title") or "").strip().casefold()
            if title: protected_titles.add(title)
    active_id=active.get("article_id","")
    active_state=active.get("state","")
    if active_id and active_state not in {"PUBLISHED","VERIFIED","REJECTED","CANCELLED"}:
        active_doi=norm_doi(active.get("doi",""))
        if active_doi: protected_dois.add(active_doi)
        if active_state!="SOURCE_BLOCKED":
            return {"decision":"RESUME_ACTIVE","article_id":active_id,"state":active_state,"no_new_ri_id":True,"public_write_permitted":False}
    else:
        active_id=""
    candidates=[]
    for row in watch:
        if (row.get("RI Article Candidate") or "").upper()!="YES": continue
        if (row.get("Existing Master ID") or "").strip(): continue
        doi=norm_doi(row.get("DOI",""))
        title=(row.get("Title") or "").strip()
        if not doi or not title or doi in protected_dois or title.casefold() in protected_titles: continue
        if source_states.get(doi)!="SOURCE_VERIFIED": continue
        candidates.append((0 if (row.get("Priority") or "").upper()=="HIGH" else 1,
                           -int(row.get("Watch Row") or 0),doi,title))
    if not candidates:
        return {"decision":"SOURCE_BLOCKED" if active_id else "NO_ELIGIBLE_SOURCE",
                "active_id":active_id,"public_write_permitted":False,"no_new_ri_id":True}
    candidates.sort()
    _,_,doi,title=candidates[0]
    return {"decision":"RESEARCH_ALTERNATE" if active_id else "PREPARE_CANDIDATE",
            "active_id":active_id,"candidate_doi":doi,"candidate_title":title,
            "no_new_ri_id":True,"public_write_permitted":False,
            "next_action":"PRIVATE_RESEARCH_ONLY_WHILE_ACTIVE_SOURCE_BLOCKED" if active_id else "PRIVATE_DRAFT_WITH_ID_CHECK"}

def main():
    p=argparse.ArgumentParser()
    for key in ("master","watch","active","sources","output"): p.add_argument("--"+key,required=True,type=Path)
    a=p.parse_args()
    out=a.output.resolve()
    if any((parent/".git").exists() for parent in (out,*out.parents)):
        raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
    active=json.loads(a.active.read_text(encoding="utf-8"))
    sources=json.loads(a.sources.read_text(encoding="utf-8"))
    decision=select(read_csv(a.master),read_csv(a.watch),active,sources)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(decision,ensure_ascii=False))
    return 0

if __name__=="__main__":
    sys.exit(main())
