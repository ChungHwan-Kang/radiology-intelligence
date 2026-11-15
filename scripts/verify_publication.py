#!/usr/bin/env python3
"""Read-only publication integrity gate. No publishing, tokens, or network calls."""
from __future__ import annotations
import argparse
from datetime import datetime
from html.parser import HTMLParser
import json
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
        self.published_times = []
        self.resource_links = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "h1": self.h1 += 1
        if "class" in d: self.classes.extend(d["class"].split())
        if tag == "a" and d.get("href"): self.links.append(d["href"])
        if tag == "link":
            rel = set(d.get("rel", "").split())
            href = d.get("href")
            self.resource_links.append((rel, href, d.get("type")))
            if "canonical" in rel: self.canonical.append(href)
        if tag == "meta" and d.get("name") == "robots": self.robots.append(d.get("content", ""))
        if tag == "meta" and d.get("property") == "article:published_time":
            self.published_times.append(d.get("content", ""))
        if tag == "script" and d.get("type") == "application/ld+json": self.jsonld += 1
    def handle_data(self, data): self.text.append(data)

def discover_published(root: Path) -> list[str]:
    """Return repository articles explicitly marked as Published HTML."""
    published = []
    for path in sorted((root / "posts").glob("*.html")):
        parser = ArticleParser()
        parser.feed(path.read_text(encoding="utf-8"))
        if parser.published_times:
            published.append(path.name)
    return published

def _valid_published_time(value: str) -> bool:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return False
    return moment.tzinfo is not None

def _blog_posting_jsonld(html: str) -> list[dict]:
    blocks = re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    results = []
    for block in blocks:
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        values = value if isinstance(value, list) else [value]
        results.extend(item for item in values if isinstance(item, dict) and item.get("@type") == "BlogPosting")
    return results

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
    jsonld = _blog_posting_jsonld(html)
    require(parser.h1 == 1, "exactly one H1 required")
    require(parser.canonical == [url], "canonical URL mismatch")
    require(len(parser.published_times) == 1, "exactly one article:published_time required")
    require(len(parser.published_times) == 1 and _valid_published_time(parser.published_times[0]), "published time must be ISO 8601 with timezone")
    require(bool(jsonld), "valid BlogPosting JSON-LD missing")
    require(any(item.get("datePublished") for item in jsonld), "JSON-LD datePublished missing")
    require(not any("noindex" in x for x in parser.robots), "published article marked noindex")
    for cls in ("article-category", "article-subtitle", "article-meta", "takeaway", "sources"):
        require(cls in parser.classes, f"missing section: {cls}")
    require("먼저 읽는 요약" in html, "summary heading missing")
    require("핵심 정리" in html, "takeaway heading missing")
    summary_position = html.find("article-summary")
    if summary_position < 0: summary_position = html.find("먼저 읽는 요약")
    order = [html.find(x) for x in ("article-category", "<h1", "article-subtitle", "article-meta")]
    order.extend((summary_position, html.find("takeaway"), html.find("sources")))
    require(all(x >= 0 for x in order) and order == sorted(order), "editorial order invalid")
    require(any("stylesheet" in rel and href == "../styles.css" for rel, href, _ in parser.resource_links), "missing site stylesheet ../styles.css")
    require(any("alternate" in rel and kind == "application/rss+xml" and href and href.endswith("feed.xml") for rel, href, kind in parser.resource_links), "missing RSS alternate link")
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
    ap.add_argument("--article", action="append", help="published article basename; repeatable; omit to validate every Published article")
    args = ap.parse_args()
    articles = args.article or discover_published(args.root)
    if not articles:
        print("FAIL no Published articles discovered")
        return 1
    bad = 0
    for slug in articles:
        if not re.fullmatch(r"(ri|rb)-[0-9]{3}-[a-z0-9-]+\.html", slug):
            print(f"FAIL invalid article basename: {slug}")
            bad += 1
            continue
        issues = check(args.root, slug)
        print(f"{'FAIL' if issues else 'PASS'} {slug}: " + ("; ".join(issues) if issues else "published metadata, HTML structure, canonical, JSON-LD, site links, RSS and sitemap XML"))
        bad += bool(issues)
    print(f"SUMMARY {len(articles)} Published article(s), {bad} failed")
    return int(bool(bad))
if __name__ == "__main__":
    sys.exit(main())
