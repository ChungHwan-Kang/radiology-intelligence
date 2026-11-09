#!/usr/bin/env python3
"""Private, no-network release transaction journal for authorized dispatchers.

This module never performs GitHub/Sheets/Drive writes. It records which remote
readbacks a connected, separately authorized dispatcher must supply, so a
partial release is never mistaken for successful end-to-end publication.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REQUIRED_RECORDS = (
    "github_post", "github_index", "github_categories", "github_feed",
    "github_sitemap", "sheets_master", "sheets_watch", "drive_published_copy",
    "current_handoff", "notion", "live_page", "rss_and_sitemap"
)


def start_release_journal(plan, sha_lease, public_html):
    if not isinstance(plan, dict) or plan.get("status") != "READY_FOR_AUTHORIZED_DISPATCH":
        raise ValueError("APPROVED_PUBLISH_PLAN_REQUIRED")
    if not isinstance(sha_lease, dict) or sha_lease.get("status") != "READY_FOR_CONDITIONAL_WRITE_PRECHECK":
        raise ValueError("SHA_LEASE_REQUIRED")
    if sha_lease.get("article_id") != plan.get("article_id") or sha_lease.get("approved_sha256") != plan.get("approved_sha256"):
        raise ValueError("APPROVAL_LEASE_MISMATCH")
    if sha_lease.get("public_write_performed") is not False:
        raise ValueError("LEASE_MUST_NOT_REPORT_PUBLICATION")
    if not isinstance(public_html, dict) or public_html.get("status") != "PUBLIC_HTML_RENDERED_NOT_PUBLISHED":
        raise ValueError("PUBLIC_HTML_NOT_RENDERED")
    if public_html.get("article_id") != plan.get("article_id") or public_html.get("slug") != plan.get("slug"):
        raise ValueError("PUBLIC_RENDER_PLAN_MISMATCH")
    if public_html.get("approved_private_sha256") != plan.get("approved_sha256"):
        raise ValueError("APPROVED_PREVIEW_HASH_MISMATCH")
    body = public_html.get("html")
    if not isinstance(body, str) or hashlib.sha256(body.encode("utf-8")).hexdigest() != public_html.get("public_html_sha256"):
        raise ValueError("PUBLIC_HTML_HASH_MISMATCH")
    if "noindex" in body.lower() or "[비공개 검토]" in body:
        raise ValueError("PUBLIC_HTML_CONTAINS_PRIVATE_MARKERS")
    if set(sha_lease.get("remote_sha_expectations", {})) != set(plan.get("required_targets", [])):
        raise ValueError("REMOTE_TARGETS_CHANGED")
    return {
        "status": "RELEASE_NOT_STARTED",
        "article_id": plan["article_id"],
        "slug": plan["slug"],
        "approved_private_sha256": plan["approved_sha256"],
        "public_html_sha256": public_html["public_html_sha256"],
        "required_remote_sha_expectations": sha_lease["remote_sha_expectations"],
        "checks": {name: "NOT_OBSERVED" for name in REQUIRED_RECORDS},
        "readback_receipts": {},
        "public_write_performed_by_this_module": False,
        "external_execution_unverified": True,
        "completion_claim_permitted": False
    }


def record_external_readback(journal, component, expected_digest, observed_digest, evidence_ref):
    """Track a caller-reported readback; never claim independently checked URL."""
    if not isinstance(journal, dict) or journal.get("status") not in ("RELEASE_NOT_STARTED", "PARTIAL_READBACK_REPORTED"):
        raise ValueError("INVALID_RELEASE_JOURNAL_STATE")
    if component not in REQUIRED_RECORDS:
        raise ValueError("UNKNOWN_RELEASE_COMPONENT")
    for digest in (expected_digest, observed_digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("INVALID_READBACK_DIGEST")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise ValueError("READBACK_EVIDENCE_REQUIRED")
    if expected_digest != observed_digest:
        raise ValueError("REMOTE_READBACK_MISMATCH")
    previous = journal.get("readback_receipts", {}).get(component)
    receipt = {"sha256": observed_digest, "evidence_ref": evidence_ref.strip()}
    if previous is not None and previous != receipt:
        raise ValueError("CONFLICTING_RETRY_RECEIPT")
    result = json.loads(json.dumps(journal))
    result["readback_receipts"][component] = receipt
    result["checks"][component] = "MATCH_REPORTED_BY_CALLER"
    result["status"] = "PARTIAL_READBACK_REPORTED"
    result["external_execution_unverified"] = True
    result["completion_claim_permitted"] = False
    return result


def persist_private_journal(path, journal):
    target = Path(path).resolve()
    if any((p / ".git").exists() for p in (target.parent, *target.parents)):
        raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
    if target.exists():
        raise ValueError("EXISTING_RELEASE_JOURNAL_PROTECTED")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive create avoids erasing an earlier transaction after a retry.
    with target.open("x", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    return target
