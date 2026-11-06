#!/usr/bin/env python3
"""Fail-closed, read-only-to-public RI editorial staging tool.

Input: a locally prepared, evidence-checked JSON article. This is NOT an AI
researcher: it validates supplied evidence declarations and static structure,
but cannot establish that source claims are actually true.
Writes ONLY to --private-dir, never GitHub, site HTML, Sheets, or email.
"""
import argparse
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys

BASE = "https://chunghwan-kang.github.io/radiology-intelligence/"
REQUIRED = ("id", "slug", "title", "subtitle", "categories", "summary",
            "sections", "takeaway", "references", "source_verification", "claims")

def assess(a):
    errors = []
    for key in REQUIRED:
        if not a.get(key):
            errors.append("MISSING_" + key.upper())
    id_ = a.get("id", "")
    slug = a.get("slug", "")
    if not re.fullmatch(r"RI-[0-9]{3}", id_):
        errors.append("INVALID_ID")
    if not re.fullmatch(r"ri-[0-9]{3}-[a-z0-9-]+\.html", slug):
        errors.append("INVALID_SLUG")
    if id_.lower() != slug[:6]:
        errors.append("ID_SLUG_MISMATCH")
    v = a.get("source_verification", {})
    if v.get("original_methods_results") is not True:
        errors.append("SOURCE_BLOCKED_ORIGINAL_METHODS_RESULTS")
    if v.get("quantitative_claims") is not True:
        errors.append("SOURCE_BLOCKED_NUMERIC_CROSSCHECK")
    if v.get("supplement") not in ("VERIFIED", "NOT_APPLICABLE", "UNAVAILABLE_DISCLOSED"):
        errors.append("SOURCE_BLOCKED_SUPPLEMENT_STATUS")
    if not str(v.get("source_url", "")).startswith("https://"):
        errors.append("SOURCE_BLOCKED_SOURCE_URL")
    references = a.get("references", [])
    if not isinstance(references, list) or not any(re.search(r"10\.\d{4,9}/", str(x)) for x in references):
        errors.append("MISSING_DOI_REFERENCE")
    sections = a.get("sections", [])
    if not isinstance(sections, list) or len(sections) < 2 or not all(isinstance(s, dict) and s.get("heading") and s.get("text") for s in sections):
        errors.append("INCOMPLETE_SECTIONS")
    claims = a.get("claims", [])
    if not isinstance(claims, list) or not claims or not all(
        isinstance(c, dict) and c.get("claim") and c.get("primary_source_location") and c.get("verified") is True
        for c in claims
    ):
        errors.append("MISSING_CLAIM_PROVENANCE")
    return errors

def preview(a):
    e = escape
    canonical = BASE + "posts/" + a["slug"]
    title = e(a["title"])
    summary = e(a["summary"])
    detail = "".join("<h2>" + e(s["heading"]) + "</h2><p>" + e(s["text"]) + "</p>" for s in a["sections"])
    citations = "".join("<li>" + e(str(v)) + "</li>" for v in a["references"])
    data = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": a["title"], "inLanguage": "ko-KR", "mainEntityOfPage": canonical}
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>[비공개 검토] ' + title + ' · Radiology Intelligence</title>'
        '<meta name="description" content="' + e(a["summary"][:150], quote=True) + '">'
        '<link rel="canonical" href="' + canonical + '">'
        '<link rel="alternate" type="application/rss+xml" href="../feed.xml">'
        '<link rel="icon" href="../assets/ri-mark.svg" type="image/svg+xml">'
        '<link rel="manifest" href="../site.webmanifest">'
        '<meta property="og:title" content="' + e(a["title"], quote=True) + '">'
        '<meta property="og:description" content="' + e(a["summary"][:150], quote=True) + '">'
        '<meta property="og:url" content="' + canonical + '">'
        '<meta property="og:image" content="' + BASE + 'assets/og-default.jpg">'
        '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + '</script>'
        '<link rel="stylesheet" href="../styles.css"></head><body>'
        '<header class="site-header"><a href="../index.html">Radiology Intelligence</a>'
        '<nav aria-label="주요 메뉴"><a href="../categories.html">주제별 보기</a></nav></header>'
        '<main><article class="article-wrap">'
        '<div class="article-category">' + e(" · ".join(a["categories"])) + '</div>'
        '<h1>' + title + '</h1><p class="article-subtitle">' + e(a["subtitle"]) + '</p>'
        '<div class="article-meta">비공개 검토 · 발행일 승인 후 확정</div>'
        '<div class="article-summary"><strong>먼저 읽는 요약</strong><p>' + summary + '</p></div>'
        + detail + '<div class="takeaway"><strong>핵심 정리</strong><p>' + e(a["takeaway"]) + '</p></div>'
        + '<section class="sources"><h2>출처</h2><ol>' + citations + '</ol></section>'
        '</article></main></body></html>'
    )

class CheckHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.classes = set()
        self.robots = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.classes.update(d.get("class", "").split())
        if tag == "h1": self.h1 += 1
        if tag == "meta" and d.get("name") == "robots":
            self.robots.append(d.get("content", ""))

def html_issues(text):
    h = CheckHTML()
    h.feed(text)
    errors = []
    if h.h1 != 1: errors.append("H1_COUNT")
    if not any("noindex" in x for x in h.robots): errors.append("PRIVATE_NOINDEX_MISSING")
    for x in ("article-category", "article-subtitle", "article-meta", "article-summary", "takeaway", "sources"):
        if x not in h.classes: errors.append("HTML_MISSING_" + x)
    positions = [text.find(x) for x in ("article-category", "<h1", "article-subtitle", "article-meta", "article-summary", "takeaway", "sources")]
    if -1 in positions or positions != sorted(positions): errors.append("HTML_WRONG_ORDER")
    return errors

def safe_dir(path):
    p = path.resolve()
    for item in (p, *p.parents):
        if (item / ".git").exists():
            raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
    return p

def save_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def prepare(args):
    article = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(article, dict): raise ValueError("ARTICLE_NOT_OBJECT")
    article_id = article.get("id")
    if not isinstance(article_id, str) or not re.fullmatch(r"RI-[0-9]{3}", article_id):
        raise ValueError("INVALID_ARTICLE_ID_PATH")
    errors = assess(article)
    private_root = safe_dir(args.private_dir)
    output = (private_root / article_id).resolve()
    if not output.is_relative_to(private_root):
        raise ValueError("PRIVATE_STAGING_PATH_ESCAPE")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Store and bind approval to the exact input JSON as well as the HTML.
    source_bytes = json.dumps(article, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    (output / "article.json").write_bytes(source_bytes)
    page = preview(article) if not errors else ""
    if page: errors.extend(html_issues(page))
    state = "SOURCE_BLOCKED" if any("SOURCE_BLOCKED" in x for x in errors) else ("QA_BLOCKED" if errors else "APPROVAL_PENDING")
    record = {"article_id": article.get("id"), "state": state, "qa_issues": errors,
              "public_write_permitted": False, "publisher": "NONE",
              "source_sha256": source_sha,
              "source_checks_are_declarations_not_independent_verification": True}
    target = output / "review.html"
    if not errors:
        target.write_text(page, encoding="utf-8")
        record["sha256"] = hashlib.sha256(page.encode("utf-8")).hexdigest()
    else:
        target.unlink(missing_ok=True)
    save_json(output / "status.json", record)
    print(json.dumps(record, ensure_ascii=False))
    return 2 if errors else 0

def approve(args):
    if not re.fullmatch(r"RI-[0-9]{3}", args.article_id):
        raise ValueError("INVALID_ARTICLE_ID_PATH")
    private_root = safe_dir(args.private_dir)
    target = (private_root / args.article_id).resolve()
    if not target.is_relative_to(private_root):
        raise ValueError("PRIVATE_STAGING_PATH_ESCAPE")
    record = json.loads((target / "status.json").read_text(encoding="utf-8"))
    if args.explicit != "APPROVE_FOR_PUBLICATION":
        raise ValueError("EXPLICIT_APPROVAL_REQUIRED")
    if record["article_id"] != args.article_id or record["state"] != "APPROVAL_PENDING":
        raise ValueError("NOT_READY_FOR_APPROVAL")
    digest = hashlib.sha256((target / "review.html").read_bytes()).hexdigest()
    source_digest = hashlib.sha256((target / "article.json").read_bytes()).hexdigest()
    if source_digest != record.get("source_sha256"):
        raise ValueError("APPROVAL_SOURCE_CHANGED")
    if digest != record.get("sha256") or args.sha256 != digest:
        raise ValueError("APPROVAL_SHA256_MISMATCH")
    record["state"] = "APPROVED_FOR_PUBLISH"
    record["approval_sha256"] = digest
    record["public_write_permitted"] = False  # This tool never publishes.
    save_json(target / "status.json", record)
    print(json.dumps(record, ensure_ascii=False))
    return 0

def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="command", required=True)
    q = s.add_parser("prepare")
    q.add_argument("--input", required=True, type=Path)
    q.add_argument("--private-dir", required=True, type=Path)
    r = s.add_parser("approve")
    r.add_argument("--article-id", required=True)
    r.add_argument("--sha256", required=True)
    r.add_argument("--explicit", required=True)
    r.add_argument("--private-dir", required=True, type=Path)
    a = p.parse_args()
    try:
        return prepare(a) if a.command == "prepare" else approve(a)
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        print("ERROR " + str(exc), file=sys.stderr)
        return 3

if __name__ == "__main__":
    sys.exit(main())
