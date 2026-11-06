#!/usr/bin/env python3
"""Prepare an approval-locked transaction manifest without publishing.
A separate authorized dispatcher must perform conditional GitHub/Google writes.
"""
import argparse,hashlib,json,re,sys
from pathlib import Path
POSTBASE="https://chunghwan-kang.github.io/radiology-intelligence/posts/"
TARGETS=("posts/{slug}","index.html","categories.html","feed.xml","sitemap.xml")

def plan_publish(private_root,article_id,published_dois=(),published_ids=(),existing_paths=()):
    if not re.fullmatch("RI-[0-9]{3}",article_id):
        raise ValueError("INVALID_ARTICLE_ID")
    path=private_root.resolve()/article_id
    if not path.resolve().is_relative_to(private_root.resolve()):
        raise ValueError("PRIVATE_STAGING_PATH_ESCAPE")
    st=json.loads((path/"status.json").read_text(encoding="utf-8"))
    source=json.loads((path/"article.json").read_text(encoding="utf-8"))
    page=(path/"review.html").read_bytes()
    sha=hashlib.sha256(page).hexdigest()
    if st.get("state")!="APPROVED_FOR_PUBLISH" or st.get("article_id")!=article_id:
        raise ValueError("ARTICLE_SPECIFIC_APPROVAL_REQUIRED")
    if st.get("approval_sha256")!=sha or st.get("sha256")!=sha:
        raise ValueError("APPROVED_HTML_CHANGED")
    if not st.get("source_sha256") or hashlib.sha256((path/"article.json").read_bytes()).hexdigest()!=st["source_sha256"]:
        raise ValueError("APPROVED_SOURCE_CHANGED")
    if source.get("id")!=article_id or not re.fullmatch(r"ri-[0-9]{3}-[a-z0-9-]+\.html",source.get("slug","")):
        raise ValueError("ARTICLE_ID_SLUG_MISMATCH")
    if source["slug"][:6]!=article_id.lower():
        raise ValueError("ARTICLE_ID_SLUG_MISMATCH")
    refs=source.get("references") or []
    dois=re.findall(r"10\.\d{4,9}/[^\s<>\";]+"," ".join(map(str,refs)))
    doi=dois[0].lower().rstrip(".,") if dois else ""
    if not doi:
        raise ValueError("ARTICLE_DOI_REQUIRED")
    if article_id in published_ids or doi in {str(d).lower() for d in published_dois} or "posts/"+source["slug"] in existing_paths:
        raise ValueError("ALREADY_PUBLISHED_OR_DUPLICATE")
    if b'content="noindex,nofollow"' not in page:
        raise ValueError("PREVIEW_IS_NOT_PRIVATE")
    if not source.get("source_verification",{}).get("original_methods_results"):
        raise ValueError("SOURCE_VERIFICATION_NOT_RECORDED")
    return {"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":article_id,"doi":doi,
            "approved_sha256":sha,"slug":source["slug"],"url":POSTBASE+source["slug"],
            "required_targets":[s.format(slug=source["slug"]) for s in TARGETS],
            "external_records":["Master_Index","MRI_Research_Watch","Google Drive Published Copy","Current_Handoff","Notion"],
            "preconditions":["article_specific_authorized_user_approval","github_optimistic_sha_lease","master_doi_and_id_duplicate_recheck","no_regression_existing_published","prepublication_qa"],
            "postconditions":["github_file_readbacks","sheets_rows_readback","drive_copy_readback","rss_and_sitemap_valid","live_url_http_200_and_html_render"],
            "public_write_performed":False,"auto_publish_enabled":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--private-dir",type=Path,required=True)
    p.add_argument("--article-id",required=True)
    p.add_argument("--duplicates-json",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        data=json.loads(a.duplicates_json.read_text(encoding="utf-8"))
        result=plan_publish(a.private_dir,a.article_id,data.get("dois",()),data.get("ids",()),data.get("paths",()))
        out=a.output.resolve()
        if any((x/".git").exists() for x in (out,*out.parents)):
            raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        print("ERROR: "+str(exc),file=sys.stderr);return 3
if __name__=="__main__":sys.exit(main())
