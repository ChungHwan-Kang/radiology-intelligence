#!/usr/bin/env python3
"""No-ID private research preview. Not an independent source-verification engine."""
import argparse,hashlib,json,html,re,sys
from pathlib import Path

def prepare(record,private_dir):
    if record.get("article_id") or record.get("ri_id"):
        raise ValueError("ALTERNATE_RESEARCH_MUST_NOT_GET_RI_ID")
    doi=str(record.get("doi","")).strip().lower()
    if not re.fullmatch(r"10\.\d{4,9}/[a-z0-9._;()/:+-]+",doi):
        raise ValueError("INVALID_DOI")
    for key in ("title","source_url","source_facts","interpretation","practical_implication","limitations"):
        if not record.get(key):raise ValueError("MISSING_"+key.upper())
    root=private_dir.resolve()
    if any((x/".git").exists() for x in (root,*root.parents)):
        raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
    out=root/("research-"+re.sub(r"[^a-z0-9]+","-",doi))
    out.mkdir(parents=True,exist_ok=True)
    e=html.escape
    text='<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
    text+='<title>비공개 검토 · '+e(record["title"])+'</title></head><body><main>'
    text+='<p>PRIVATE_RESEARCH_ONLY — RI 번호 미부여, 승인 요청 대상 아님</p><h1>'+e(record["title"])+'</h1>'
    for heading,key in (("원 연구 사실","source_facts"),("해석","interpretation"),("실무적 시사점","practical_implication"),("연구의 한계","limitations")):
        text+='<section><h2>'+heading+'</h2><p>'+e(record[key])+'</p></section>'
    text+='<p>DOI: '+e(doi)+'</p><p>출처: '+e(record["source_url"])+'</p></main></body></html>'
    page=out/"research_preview.html";page.write_text(text,encoding="utf-8")
    state={"state":"PRIVATE_RESEARCH_ONLY","doi":doi,"article_id":None,
      "supplement_status":record.get("supplement_status","UNVERIFIED"),
      "research_claims_came_from_supplied_note":True,
      "sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
      "approval_possible":False,"public_write_permitted":False}
    (out/"status.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    return state

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",type=Path,required=True);p.add_argument("--private-dir",type=Path,required=True)
    args=p.parse_args()
    try:
        print(json.dumps(prepare(json.loads(args.input.read_text(encoding="utf-8")),args.private_dir),ensure_ascii=False));return 0
    except (ValueError,OSError,json.JSONDecodeError) as err:
        print("ERROR: "+str(err),file=sys.stderr);return 3
if __name__=="__main__":sys.exit(main())
