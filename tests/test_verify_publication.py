import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_publication import check, discover_published


class PublicationIntegrityTests(unittest.TestCase):
    def test_discovers_and_validates_every_published_article(self):
        articles = discover_published(ROOT)
        self.assertIn("ri-032-endolymphatic-hydrops-mri-tr-te-ti.html", articles)
        self.assertGreaterEqual(len(articles), 34)
        failures = {slug: issues for slug in articles if (issues := check(ROOT, slug))}
        self.assertEqual(failures, {})

    def test_discovery_excludes_html_without_published_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            posts = root / "posts"
            posts.mkdir()
            (posts / "ri-999-draft.html").write_text("<html><body>draft</body></html>", encoding="utf-8")
            (posts / "ri-998-published.html").write_text(
                '<meta property="article:published_time" content="2026-11-15T10:00:00+09:00">',
                encoding="utf-8",
            )
            self.assertEqual(discover_published(root), ["ri-998-published.html"])

    def test_explicit_article_requires_published_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "posts").mkdir()
            (root / "posts" / "ri-999-draft.html").write_text("<h1>draft</h1>", encoding="utf-8")
            self.assertIn("exactly one article:published_time required", check(root, "ri-999-draft.html"))


if __name__ == "__main__":
    unittest.main()
