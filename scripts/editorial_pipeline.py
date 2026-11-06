#!/usr/bin/env python3
"""Read-only deterministic handoff across existing RI editorial stages.
Input JSON must be supplied by the authorized connected Sheets/Drive caller.
No cloud publishing credentials or automatic publication.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
from editorial_queue import select,read_csv,norm_doi
from private_editorial_gate import prepare as prepare_article
from research_preview import prepare as prepare_research
from sheets_bridge import bridge

def _write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

def execute(values,active,source_states,private_root,research=None,article=None):
    root=private_root.resolve()
    steps=[]
    def step(name,status,note=""):steps.append({"stage":name,"status":status,"notes":note})
    snapshot=bridge(values,root/"sheets_snapshot")
    step("CONNECTED_SHEETS_SNAPSHOT","PASS",f"Master {snapshot['tabs']['Master_Index']} / Watch {snapshot['tabs']['MRI_Research_Watch']} rows supplied")
    master=read_csv(root/"sheets_snapshot"/"Master_Index.csv")
    watch=read_csv(root/"sheets_snapshot"/"MRI_Research_Watch.csv")
    decision=select(master,watch,active,source_states)
    _write(root/"queue_decision.json",decision)
    step("DOI_DEDUP_AND_SELECTION","PASS",decision["decision"])
    if decision["decision"]=="RESEARCH_ALTERNATE":
        if research is None:
            step("PRIVATE_RESEARCH_PREVIEW","BLOCKED","Research input missing")
        elif norm_doi(research.get("doi",""))!=decision["candidate_doi"]:
            step("PRIVATE_RESEARCH_PREVIEW","FAIL","Candidate DOI mismatch")
        else:
            outcome=prepare_research(research,root/"private_research")
            step("PRIVATE_RESEARCH_PREVIEW","PASS","No RI ID; noindex; approval_possible="+str(outcome["approval_possible"]))
    elif decision["decision"]=="RESUME_ACTIVE":
        if article is None:
            step("PRIVATE_FINAL_HTML_QA","BLOCKED","Source-verified article input missing")
        elif article.get("id")!=active.get("article_id"):
            step("PRIVATE_FINAL_HTML_QA","FAIL","Active article ID mismatch")
        else:
            source_doi=norm_doi(active.get("doi",""))
            refs=[norm_doi(v.split("doi.org/")[-1]) for v in article.get("references",[])]
            if source_doi and not any(source_doi in ref for ref in refs):
                step("PRIVATE_FINAL_HTML_QA","FAIL","Active DOI not in references")
            else:
                source_file=root/"source_article.json"
                _write(source_file,article)
                code=prepare_article(SimpleNamespace(input=source_file,private_dir=root/"private_article"))
                status=json.loads((root/"private_article"/article["id"]/"status.json").read_text(encoding="utf-8"))
                step("PRIVATE_FINAL_HTML_QA","PASS" if code==0 else "BLOCKED",status["state"])
    else:
        step("PRIVATE_FINAL_HTML_QA","BLOCKED","No eligible source")
    step("USER_APPROVAL","NOT_REQUESTED","Article-specific approval not in this run")
    step("PUBLISH_AND_SYNC","NOT_RUN","No GitHub/Sheets/Drive writes before approval")
    manifest={"run_type":"LOCAL_OFFLINE_INTEGRATION",
        "source_values_origin":values.get("_snapshot_scope","CALLER_PROVIDED_CONNECTED_SHEETS_SNAPSHOT"),
        "snapshot_complete":values.get("_snapshot_complete",False),
        "cloud_api_calls_by_script":0,"local_windows_kch_runner_confirmed":False,
        "state":"FAIL" if any(x["status"]=="FAIL" for x in steps) else "PARTIAL",
        "steps":steps,"selected":decision,"public_write_performed":False,"new_ri_id_assigned":False}
    _write(root/"run_manifest.json",manifest)
    return manifest

def main():
    p=argparse.ArgumentParser()
    for name in ("values-json","active-json","sources-json","private-dir"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--research-json",type=Path);p.add_argument("--article-json",type=Path)
    a=p.parse_args()
    try:
        def load(path):return json.loads(path.read_text(encoding="utf-8")) if path else None
        result=execute(load(a.values_json),load(a.active_json),load(a.sources_json),
            a.private_dir,load(a.research_json),load(a.article_json))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["state"]!="FAIL" else 2
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as err:
        print("ERROR: "+str(err),file=sys.stderr);return 3
if __name__=="__main__":sys.exit(main())
