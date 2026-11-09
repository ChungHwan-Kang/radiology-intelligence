import unittest
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from publication_site_composer import compose_site_updates, TOPICS


class SiteComposerTests(unittest.TestCase):
    def setUp(self):
        sections=[]
        for cat,section_id in TOPICS.items():
            sections.append(
                f'<section class="category-section" id="{section_id}">\n'
                f'<div class="category-title-row"><h2>{cat}</h2><span>1건</span></div>'
                f'<a class="category-article" href="posts/ri-030-old.html"><strong>Old</strong><span>Prior</span></a>'
                '</section>\n'
            )
        self.existing={
            "index.html":'<section><span>현재 공개된 해설 33건</span>\n'
                '<div class="article-list">\n'
                '<a class="article-row" href="posts/ri-030-old.html">Old approved</a>'
                '</div></section>',
            "categories.html":'<main>'+''.join(sections)+'</main>',
            "feed.xml":'<?xml version="1.0"?><rss version="2.0"><channel>'
                '<lastBuildDate>Tue, 03 Nov 2026 01:00:00 GMT</lastBuildDate>'
                '  <item><title>Old approved</title><link>https://example.com/old</link></item>'
                '</channel></rss>',
            "sitemap.xml":'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/old</loc></url></urlset>'
        }
        self.article={
            "slug":"ri-999-synthetic-code-only.html",
            "title":"MRI & AI <quality>",
            "summary":"Evidence <checked> & limited",
            "categories":["MRI 검사와 기술","연구와 근거"],
            "published_at":"2026-11-09T10:00:00+09:00"
        }
    def test_additive_only_preserves_old_approved_entries(self):
        result=compose_site_updates(self.existing,self.article)
        self.assertIn('현재 공개된 해설 34건',result["index.html"])
        self.assertIn("Old approved",result["index.html"])
        self.assertIn("ri-030-old.html",result["categories.html"])
        self.assertIn("<h3>MRI &amp; AI &lt;quality&gt;</h3>",result["index.html"])
        self.assertIn('<span>2건</span>',result["categories.html"])
        self.assertIn('<h2>MRI 안전</h2><span>1건</span>',result["categories.html"])
        self.assertEqual(result["categories.html"].count("ri-999-synthetic-code-only.html"),2)
        feed=ET.fromstring(result["feed.xml"])
        sm=ET.fromstring(result["sitemap.xml"])
        self.assertEqual(len(feed.find("channel").findall("item")),2)
        self.assertEqual(len(sm),2)
        self.assertIn("2026-11-09",result["sitemap.xml"])
        self.assertIn("Mon, 09 Nov 2026 01:00:00 GMT",result["feed.xml"])
        self.assertIn("Old approved",result["feed.xml"])
        self.assertEqual(self.existing["index.html"].count("ri-999"),0)
    def test_duplicate_link_fails_closed_without_mutating_input(self):
        before=dict(self.existing)
        self.existing["feed.xml"]=self.existing["feed.xml"].replace("</channel>",
            "<!-- posts/"+self.article["slug"]+" -->"+"</channel>")
        with self.assertRaisesRegex(ValueError,"ARTICLE_ALREADY_INDEXED:feed.xml"):
            compose_site_updates(self.existing,self.article)
        self.assertEqual(before["index.html"],self.existing["index.html"])
    def test_unknown_category_fails_closed(self):
        self.article["categories"]=["Unknown"]
        with self.assertRaisesRegex(ValueError,"INVALID_CATEGORY"):
            compose_site_updates(self.existing,self.article)
    def test_duplicate_category_fails_closed(self):
        self.article["categories"]=["MRI 안전","MRI 안전"]
        with self.assertRaisesRegex(ValueError,"INVALID_CATEGORY"):
            compose_site_updates(self.existing,self.article)
    def test_invalid_existing_xml_fails_closed(self):
        self.existing["feed.xml"]="<rss>"
        with self.assertRaisesRegex(ValueError,"EXISTING_SITE_XML_INVALID"):
            compose_site_updates(self.existing,self.article)
    def test_missing_existing_category_section_fails_closed(self):
        self.existing["categories.html"]=self.existing["categories.html"].replace(
            'id="research"','id="research-missing"')
        with self.assertRaisesRegex(ValueError,"CATEGORY_SECTION_MISSING"):
            compose_site_updates(self.existing,self.article)
    def test_naive_date_and_incomplete_inputs_rejected(self):
        self.article["published_at"]="2026-11-09T10:00:00"
        with self.assertRaisesRegex(ValueError,"PUBLICATION_OFFSET_REQUIRED"):
            compose_site_updates(self.existing,self.article)
        self.article["published_at"]="2026-11-09T10:00:00+09:00"
        self.existing.pop("sitemap.xml")
        with self.assertRaisesRegex(ValueError,"FOUR_SOURCE_FILES_REQUIRED"):
            compose_site_updates(self.existing,self.article)
    def test_current_repository_site_files_compose_without_touching_old_content(self):
        root=Path(__file__).resolve().parents[1]
        actual={name:(root/name).read_text(encoding="utf-8") for name in
                ("index.html","categories.html","feed.xml","sitemap.xml")}
        result=compose_site_updates(actual,self.article)
        self.assertEqual(set(result),set(actual))
        for name in actual:
            self.assertNotEqual(actual[name],result[name])
            self.assertIn("ri-999-synthetic-code-only.html",result[name])
        # No previously published story is removed, even from other categories.
        import re
        for name in actual:
            old_links=set(re.findall(r'(?:ri|rb)-[0-9]{3}-[a-z0-9-]+\\.html',actual[name]))
            new_links=set(re.findall(r'(?:ri|rb)-[0-9]{3}-[a-z0-9-]+\\.html',result[name]))
            self.assertTrue(old_links.issubset(new_links),name)
        ET.fromstring(result["feed.xml"])
        ET.fromstring(result["sitemap.xml"])

    def test_second_application_never_duplicates(self):
        once=compose_site_updates(self.existing,self.article)
        with self.assertRaisesRegex(ValueError,"ARTICLE_ALREADY_INDEXED"):
            compose_site_updates(once,self.article)


if __name__=="__main__":
    unittest.main()
