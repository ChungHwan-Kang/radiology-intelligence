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
    verification=source.get("source_verification")
    if not isinstance(verification,dict) or verification.get("original_methods_results") is not True:
        raise ValueError("SOURCE_VERIFICATION_NOT_RECORDED")
    if verification.get("quantitative_claims") is not True:
        raise ValueError("QUANTITATIVE_CLAIMS_NOT_VERIFIED")
    if verification.get("supplement") not in ("VERIFIED","NOT_APPLICABLE","UNAVAILABLE_DISCLOSED"):
        raise ValueError("SUPPLEMENT_STATUS_UNRESOLVED")
    if not isinstance(verification.get("source_url"),str) or not verification["source_url"].startswith("https://"):
        raise ValueError("PRIMARY_SOURCE_URL_MISSING")
    claims=source.get("claims")
    if not isinstance(claims,list) or not claims or not all(
        isinstance(item,dict) and item.get("verified") is True
        and isinstance(item.get("primary_source_location"),str)
        and item["primary_source_location"].strip()
        and isinstance(item.get("claim"),str) and item["claim"].strip()
        for item in claims
    ):
        raise ValueError("CLAIM_PROVENANCE_INCOMPLETE")
    return {"status":"READY_FOR_AUTHORIZED_DISPATCH","article_id":article_id,"doi":doi,
            "approved_sha256":sha,"slug":source["slug"],"url":POSTBASE+source["slug"],
            "required_targets":[s.format(slug=source["slug"]) for s in TARGETS],
            "external_records":["Master_Index","MRI_Research_Watch","Google Drive Published Copy","Current_Handoff","Notion"],
            "preconditions":["article_specific_authorized_user_approval","github_optimistic_sha_lease","master_doi_and_id_duplicate_recheck","no_regression_existing_published","prepublication_qa"],
            "postconditions":["github_file_readbacks","sheets_rows_readback","drive_copy_readback","rss_and_sitemap_valid","live_url_http_200_and_html_render"],
            "public_write_performed":False,"auto_publish_enabled":False}

def prepare_github_sha_lease(plan, remote_targets):
    """Build a non-publishing optimistic-lock lease from fresh remote SHA reads.

    The authorized dispatcher must recheck every SHA at write time. This
    structure is never proof that a remote write was performed.
    """
    if not isinstance(plan,dict) or plan.get("status")!="READY_FOR_AUTHORIZED_DISPATCH":
        raise ValueError("APPROVED_PUBLISH_PLAN_REQUIRED")
    expected=plan.get("required_targets")
    if not isinstance(expected,list) or len(expected)!=len(TARGETS) or len(set(expected))!=len(expected):
        raise ValueError("INVALID_PUBLISH_TARGETS")
    if not isinstance(remote_targets,dict) or set(remote_targets)!=set(expected):
        raise ValueError("INCOMPLETE_REMOTE_SHA_SNAPSHOT")
    created=f"posts/{plan.get('slug','')}"
    if created not in remote_targets:
        raise ValueError("ARTICLE_TARGET_NOT_IN_SNAPSHOT")
    if remote_targets[created] is not None:
        raise ValueError("ARTICLE_ALREADY_EXISTS_REMOTE")
    for path in expected:
        if path==created: continue
        sha=remote_targets[path]
        if not isinstance(sha,str) or not re.fullmatch(r"[a-f0-9]{40}",sha):
            raise ValueError("INVALID_REMOTE_SHA:"+path)
    return {
        "status":"READY_FOR_CONDITIONAL_WRITE_PRECHECK",
        "article_id":plan["article_id"],
        "approved_sha256":plan["approved_sha256"],
        "remote_sha_expectations":dict(remote_targets),
        "remote_shas_must_be_revalidated_immediately_before_each_write":True,
        "requires_independent_public_html_render":True,
        "approved_noindex_preview_must_not_be_published":True,
        "public_write_performed":False
    }


def render_approved_public_html(private_root, article_id, published_date):
    """Return unpublished UTF-8 HTML derived solely from the locked preview.

    Never writes GitHub or Google. The approved private source and HTML hashes
    are rechecked by plan_publish before the limited metadata transformation.
    """
    from datetime import date
    from html.parser import HTMLParser
    from private_editorial_gate import BASE

    try:
        if date.fromisoformat(published_date).isoformat()!=published_date:
            raise ValueError("INVALID_PUBLICATION_DATE")
    except (TypeError, ValueError):
        raise ValueError("INVALID_PUBLICATION_DATE")
    plan=plan_publish(private_root,article_id)
    page=(private_root.resolve()/article_id/"review.html").read_text(encoding="utf-8")
    source=json.loads((private_root.resolve()/article_id/"article.json").read_text(encoding="utf-8"))
    replacements=(
        ('<meta name="robots" content="noindex,nofollow">',''),
        ('<title>[비공개 검토] ','<title>'),
        ('<div class="article-meta">비공개 검토 · 발행일 승인 후 확정</div>',
         '<div class="article-meta">발행일 '+published_date+'</div>')
    )
    for before,after in replacements:
        if page.count(before)!=1:
            raise ValueError("UNEXPECTED_APPROVED_PREVIEW_STRUCTURE")
        page=page.replace(before,after,1)
    if "noindex" in page.lower() or "[비공개 검토]" in page or "발행일 승인 후 확정" in page:
        raise ValueError("PRIVATE_PREVIEW_MARKER_REMAINS")
    # Check post conversion with the same metadata parser as production QA.
    from verify_publication import ArticleParser
    parser=ArticleParser()
    parser.feed(page)
    expected=BASE+"posts/"+source["slug"]
    if parser.h1!=1 or parser.canonical!=[expected] or parser.jsonld<1:
        raise ValueError("PUBLIC_HTML_METADATA_INVALID")
    for required in ("article-category","article-subtitle","article-meta","article-summary","takeaway","sources"):
        if required not in parser.classes:
            raise ValueError("PUBLIC_HTML_SECTION_MISSING:"+required)
    return {
        "status":"PUBLIC_HTML_RENDERED_NOT_PUBLISHED",
        "article_id":article_id,
        "slug":source["slug"],
        "published_date":published_date,
        "approved_private_sha256":plan["approved_sha256"],
        "public_html_sha256":hashlib.sha256(page.encode("utf-8")).hexdigest(),
        "html":page,
        "public_write_performed":False,
        "dispatch_authorized_by_renderer":False
    }


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
