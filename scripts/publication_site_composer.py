#!/usr/bin/env python3
"""Compose the four existing RI site index files without altering old entries.

Pure function. Call only with separately approved article metadata and freshly
read site files. No GitHub, Sheets, Drive or other network operations here.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape, unescape
import re
import xml.etree.ElementTree as ET

BASE="https://chunghwan-kang.github.io/radiology-intelligence/"
TOPICS={
    "MRI 검사와 기술":"mri-tech",
    "MRI 안전":"mri-safety",
    "품질과 운영":"quality-operations",
    "AI와 디지털":"ai-digital",
    "교육과 역량":"education",
    "연구와 근거":"research",
    "정책과 전문직":"policy",
}
FILES=("index.html","categories.html","feed.xml","sitemap.xml")


def _require(condition, code):
    if not condition: raise ValueError(code)


def _single_replace(source, old, new, issue):
    _require(source.count(old)==1, issue)
    return source.replace(old,new,1)


def _metadata(article):
    _require(isinstance(article,dict), "ARTICLE_METADATA_REQUIRED")
    slug=article.get("slug")
    _require(isinstance(slug,str) and re.fullmatch(r"ri-[0-9]{3}-[a-z0-9-]+\.html",slug) is not None,"INVALID_SLUG")
    title=article.get("title")
    summary=article.get("summary")
    _require(all(isinstance(x,str) and x.strip() for x in (title,summary)),"ARTICLE_TITLE_SUMMARY_REQUIRED")
    categories=article.get("categories")
    _require(isinstance(categories,list) and categories and len(set(categories))==len(categories) and
             all(isinstance(x,str) and x in TOPICS for x in categories),"INVALID_CATEGORY")
    published=article.get("published_at")
    try:
        moment=datetime.fromisoformat(published)
    except (TypeError,ValueError,AttributeError):
        raise ValueError("INVALID_PUBLICATION_DATETIME")
    _require(moment.tzinfo is not None and moment.utcoffset() is not None,"PUBLICATION_OFFSET_REQUIRED")
    return slug,title,summary,categories,moment


def compose_site_updates(existing, article):
    """Produce exactly four changed texts, never mutating any input."""
    slug,title,summary,categories,moment=_metadata(article)
    _require(isinstance(existing,dict) and set(existing)==set(FILES) and
             all(isinstance(x,str) for x in existing.values()),"FOUR_SOURCE_FILES_REQUIRED")
    href="posts/"+slug
    url=BASE+href
    # Never overwrite or reintroduce an existing article, even partially indexed.
    for path,body in existing.items():
        _require(href not in body and url not in body, "ARTICLE_ALREADY_INDEXED:"+path)
    iso_date=moment.date().isoformat()
    display_date=moment.strftime("%Y.%m.%d")
    title_html=escape(title,quote=True)
    summary_html=escape(summary,quote=True)
    cat_html=escape(" · ".join(categories),quote=True)

    # Homepage: preserve the pre-approved featured story and every old row.
    index=existing["index.html"]
    count=re.search(r'<span>현재 공개된 해설 (\d+)건</span>',index)
    _require(count is not None and index.count(count.group(0))==1,"HOME_COUNT_ANCHOR_CHANGED")
    index=index.replace(count.group(0),f'<span>현재 공개된 해설 {int(count.group(1))+1}건</span>',1)
    anchors=list(re.finditer(r'(?m)^[ \\t]*<div class="article-list">\\n',index))
    _require(len(anchors)==1,"HOME_ARTICLE_LIST_ANCHOR_CHANGED")
    anchor=anchors[0].group(0)
    newrow=(f'        <a class="article-row" href="{href}"><div>'
            f'<div class="row-category">{cat_html}</div><h3>{title_html}</h3>'
            f'<p>{summary_html}</p></div><div class="row-meta">{display_date}<br>{escape(categories[0])}</div></a>\n')
    index=index.replace(anchor,anchor+newrow,1)

    # Category pages: change only category count and prepend one entry to each
    # relevant existing section, preserving all previously published entries.
    cat_page=existing["categories.html"]
    for category in categories:
        cat_id=TOPICS[category]
        section_start=f'<section class="category-section" id="{cat_id}">'
        _require(cat_page.count(section_start)==1,"CATEGORY_SECTION_MISSING:"+cat_id)
        position=cat_page.index(section_start)
        next_section=cat_page.find('<section class="category-section"',position+len(section_start))
        end=next_section if next_section>=0 else cat_page.find('</main>',position)
        _require(end>position,"CATEGORY_SECTION_END_MISSING:"+cat_id)
        before=cat_page[:position]
        section=cat_page[position:end]
        after=cat_page[end:]
        heading=re.search(r'<div class="category-title-row"><h2>([^<]+)</h2><span>(\d+)건</span></div>',section)
        _require(heading is not None and unescape(heading.group(1))==category,"CATEGORY_HEADING_CHANGED:"+cat_id)
        new_heading=heading.group(0).replace(f'{heading.group(2)}건',f'{int(heading.group(2))+1}건')
        section=section.replace(heading.group(0),new_heading,1)
        entry=(f'<a class="category-article" href="{href}"><strong>{title_html}</strong>'
               f'<span>{summary_html}</span></a>')
        section=section.replace(new_heading,new_heading+entry,1)
        cat_page=before+section+after

    feed=existing["feed.xml"]
    sitemap=existing["sitemap.xml"]
    try:
        rssroot=ET.fromstring(feed)
        smroot=ET.fromstring(sitemap)
    except ET.ParseError as exc:
        raise ValueError("EXISTING_SITE_XML_INVALID") from exc
    _require(rssroot.tag=="rss" and rssroot.find("channel") is not None,"RSS_CHANNEL_INVALID")
    _require(smroot.tag=="{http://www.sitemaps.org/schemas/sitemap/0.9}urlset","SITEMAP_ROOT_INVALID")
    item=(
        f'  <item><title>{escape(title)}</title><link>{escape(url)}</link>'
        f'<guid isPermaLink="true">{escape(url)}</guid>'
        f'<pubDate>{format_datetime(moment)}</pubDate>'
        f'<description>{escape(summary)}</description></item>\n'
    )
    _require(feed.count("  <item>")==1 or "  <item>" in feed,"RSS_ITEM_ANCHOR_MISSING")
    first_item=feed.find("  <item>")
    feed=feed[:first_item]+item+feed[first_item:]
    old_build=re.search(r'<lastBuildDate>[^<]+</lastBuildDate>',feed)
    _require(old_build is not None and feed.count("<lastBuildDate>")==1,"RSS_BUILD_DATE_MISSING")
    replacement='<lastBuildDate>'+format_datetime(moment.astimezone(timezone.utc),usegmt=True)+'</lastBuildDate>'
    feed=feed.replace(old_build.group(0),replacement,1)

    loc=(f'  <url><loc>{escape(url)}</loc><lastmod>{iso_date}</lastmod>'
         f'<changefreq>monthly</changefreq><priority>0.9</priority></url>\n')
    _require(sitemap.count("</urlset>")==1,"SITEMAP_CLOSE_MISSING")
    sitemap=sitemap.replace("</urlset>",loc+"</urlset>",1)
    try:
        ET.fromstring(feed)
        ET.fromstring(sitemap)
    except ET.ParseError as exc:
        raise ValueError("COMPOSED_XML_INVALID") from exc
    result={"index.html":index,"categories.html":cat_page,"feed.xml":feed,"sitemap.xml":sitemap}
    for path in FILES:
        _require(url in result[path] or href in result[path],"NEW_ARTICLE_LINK_MISSING:"+path)
    return result
