"""Offline regression tests for RI private publishing gates. No network."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "private_editorial_gate.py"

def sample():
    return {
        "id": "RI-999", "slug": "ri-999-fixture.html",
        "title": "검증용 원고", "subtitle": "실제 기사 아님",
        "categories": ["MRI 검사와 기술", "연구와 근거"],
        "summary": "이 텍스트는 소프트웨어의 승인 차단 규칙을 시험하기 위한 가상 자료입니다.",
        "sections": [
            {"heading": "방법", "text": "가상의 검증용 데이터입니다."},
            {"heading": "한계", "text": "임상적 근거로 사용하지 않습니다."}
        ],
        "takeaway": "검증 성공 여부만 확인합니다.",
        "references": ["Fixture doi:10.1000/fictional-test"],
        "claims": [{"claim": "synthetic", "primary_source_location": "test fixture", "verified": True}],
        "source_verification": {
            "original_methods_results": True,
            "quantitative_claims": True,
            "supplement": "NOT_APPLICABLE",
            "source_url": "https://example.org/test-fixture"
        }
    }

class EditorialGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inp = self.root / "draft.json"
        self.private = self.root / "private"
        self.data = sample()
    def call(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True)
    def prepare(self):
        self.inp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        return self.call("prepare", "--input", str(self.inp), "--private-dir", str(self.private))
    def test_requires_verified_primary_methods(self):
        self.data["source_verification"]["original_methods_results"] = False
        result = self.prepare()
        self.assertEqual(result.returncode, 2)
        status = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "SOURCE_BLOCKED")
        self.assertFalse((self.private / "RI-999" / "review.html").exists())
    def test_generates_nonpublic_preview_without_publishing(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        html = (self.private / "RI-999" / "review.html").read_text(encoding="utf-8")
        self.assertEqual(status["state"], "APPROVAL_PENDING")
        self.assertFalse(status["public_write_permitted"])
        self.assertIn('content="noindex,nofollow"', html)
        self.assertIn("먼저 읽는 요약", html)
        self.assertNotIn("2026-11-04T", html)
    def test_refuse_approval_without_exact_token(self):
        self.prepare()
        status = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        result = self.call("approve", "--article-id", "RI-999", "--private-dir", str(self.private),
                           "--sha256", status["sha256"], "--explicit", "yes")
        self.assertEqual(result.returncode, 3)
        self.assertIn("EXPLICIT_APPROVAL_REQUIRED", result.stderr)
    def test_refuse_mutated_preview(self):
        self.prepare()
        status = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        with (self.private / "RI-999" / "review.html").open("a", encoding="utf-8") as f:
            f.write("modified")
        result = self.call("approve", "--article-id", "RI-999", "--private-dir", str(self.private),
                           "--sha256", status["sha256"], "--explicit", "APPROVE_FOR_PUBLICATION")
        self.assertEqual(result.returncode, 3)
        self.assertIn("APPROVAL_SHA256_MISMATCH", result.stderr)
    def test_approval_is_record_only(self):
        self.prepare()
        status = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        result = self.call("approve", "--article-id", "RI-999", "--private-dir", str(self.private),
                           "--sha256", status["sha256"], "--explicit", "APPROVE_FOR_PUBLICATION")
        self.assertEqual(result.returncode, 0, result.stderr)
        approved = json.loads((self.private / "RI-999" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(approved["state"], "APPROVED_FOR_PUBLISH")
        self.assertFalse(approved["public_write_permitted"])
        self.assertEqual(approved["approval_sha256"], status["sha256"])
    def test_reject_article_id_path_traversal(self):
        self.data["id"] = "../../escaped"
        result = self.prepare()
        self.assertEqual(result.returncode, 3)
        self.assertIn("INVALID_ARTICLE_ID_PATH", result.stderr)
        self.assertFalse((self.root / "escaped").exists())
    def test_reject_private_symlink_escape(self):
        self.inp.write_text(json.dumps(self.data), encoding="utf-8")
        self.private.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.private / "RI-999").symlink_to(elsewhere, target_is_directory=True)
        result = self.call("prepare", "--input", str(self.inp), "--private-dir", str(self.private))
        self.assertEqual(result.returncode, 3)
        self.assertIn("PRIVATE_STAGING_PATH_ESCAPE", result.stderr)
        self.assertFalse((elsewhere / "status.json").exists())
    def test_reject_git_worktree_storage(self):
        self.inp.write_text(json.dumps(self.data), encoding="utf-8")
        work = self.root / "repo"; work.mkdir(); (work / ".git").mkdir()
        result = self.call("prepare", "--input", str(self.inp), "--private-dir", str(work / "private"))
        self.assertEqual(result.returncode, 3)
        self.assertIn("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY", result.stderr)

if __name__ == "__main__":
    unittest.main()
