#!/usr/bin/env python3
"""Read-only publication integrity gate. No publishing, tokens, or network calls."""
from __future__ import annotations
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

BASE = "https://chunghwan-kang.github.io/radiology-intelligence/"

class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0
        self.classes = []
        self.links = []
        self.canonical = []
        self.robots = []
        self.jsonld = 0
        self.text = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "h1": self.h1 += 1
        if "class" in d: self.classes.extend(d["class"].split())
        if tag == "a" and d.get("href"): self.links.append(d["href"])
        if tag == "link" and d.get("rel") == "canonical": self.canonical.append(d.get("href"))
        if tag == "meta" and d.get("name") == "robots": self.robots.append(d.get("content", ""))
        if tag == "script" and d.get("type") == "application/ld+json": self.jsonld += 1
    def handle_data(self, data): self.text.append(data)

def check(root: Path, slug: str) -> list[str]:
    issues = []
    def require(cond, msg):
        if not cond: issues.append(msg)
    path = root / "posts" / slug
    if not path.is_file(): return [f"article missing: {path}"]
    html = path.read_text(encoding="utf-8")
    parser = ArticleParser()
    parser.feed(html)
    url = BASE + "posts/" + slug
    require(parser.h1 == 1, "exactly one H1 required")
    require(parser.canonical == [url], "canonical URL mismatch")
    require(parser.jsonld >= 1, "JSON-LD missing")
    require(not any("noindex" in x for x in parser.robots), "published article marked noindex")
    for cls in ("article-category", "article-subtitle", "article-meta", "article-summary", "takeaway", "sources"):
        require(cls in parser.classes, f"missing section: {cls}")
    require("먼저 읽는 요약" in html, "summary heading missing")
    require("핵심 정리" in html, "takeaway heading missing")
    require(bool(re.search(r"10\.\d{4,9}/\S+", html)), "DOI missing")
    order = [html.find(x) for x in ("article-category", "<h1", "article-subtitle", "article-meta", "article-summary", "takeaway", "sources")]
    require(all(x >= 0 for x in order) and order == sorted(order), "editorial order invalid")
    for href in ("../styles.css", "../feed.xml", "../site.webmanifest"):
        require(href in html, f"missing site resource {href}")
    for file in ("index.html", "categories.html", "feed.xml", "sitemap.xml"):
        p = root / file
        require(p.is_file(), f"missing {file}")
        if p.is_file():
            contents = p.read_text(encoding="utf-8")
            require(slug in contents, f"article missing from {file}")
    for file in ("feed.xml", "sitemap.xml"):
        p = root / file
        if p.is_file():
            try: ET.parse(p)
            except ET.ParseError as e: issues.append(f"{file} invalid XML: {e}")
    return issues

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--article", action="append", required=True, help="published article basename; repeatable")
    args = ap.parse_args()
    bad = 0
    for slug in args.article:
        if not re.fullmatch(r"(ri|rb)-[0-9]{3}-[a-z0-9-]+\.html", slug):
            print(f"FAIL invalid article basename: {slug}")
            bad += 1
            continue
        issues = check(args.root, slug)
        print(f"{'FAIL' if issues else 'PASS'} {slug}: " + ("; ".join(issues) if issues else "HTML structure, canonical, metadata, site links, RSS and sitemap XML"))
        bad += bool(issues)
    return int(bool(bad))
if __name__ == "__main__":
    sys.exit(main())
