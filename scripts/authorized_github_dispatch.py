#!/usr/bin/env python3
"""Approval-locked conditional GitHub dispatch through an injected adapter.

No credentials, network configuration or automatic scheduling in this file.
The caller must supply an authenticated adapter implementing read(path) and
write(path, content, expected_sha); the write must be atomic/conditional.
Google writebacks are NOT part of this GitHub-only phase.
"""
from __future__ import annotations

import hashlib
import json

from publication_transaction import TARGETS


class DispatchBlocked(ValueError):
    pass


def _digest(content):
    if not isinstance(content, str):
        raise DispatchBlocked("CONTENT_MUST_BE_UTF8_TEXT")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def dispatch_github_approved(plan, lease, rendered, contents, adapter, approval_token):
    """Try one ordered GitHub release; stop at first failed remote verification.

    A returned PARTIAL status must be preserved by the caller. A network
    exception deliberately propagates rather than guessing whether a write
    took place; recheck the remote before any manual retry.
    """
    if approval_token != "EXECUTE_ARTICLE_SPECIFIC_APPROVED_DISPATCH":
        raise DispatchBlocked("EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED")
    if plan.get("status") != "READY_FOR_AUTHORIZED_DISPATCH":
        raise DispatchBlocked("APPROVED_ARTICLE_PLAN_REQUIRED")
    if lease.get("status") != "READY_FOR_CONDITIONAL_WRITE_PRECHECK":
        raise DispatchBlocked("SHA_LEASE_REQUIRED")
    if rendered.get("status") != "PUBLIC_HTML_RENDERED_NOT_PUBLISHED":
        raise DispatchBlocked("PUBLIC_HTML_RENDER_REQUIRED")
    article_id=plan.get("article_id")
    if not isinstance(article_id,str) or any(x.get("article_id") != article_id for x in (lease,rendered)):
        raise DispatchBlocked("ARTICLE_ID_LOCK_MISMATCH")
    if plan.get("approved_sha256") != lease.get("approved_sha256") or plan.get("approved_sha256") != rendered.get("approved_private_sha256"):
        raise DispatchBlocked("APPROVED_CONTENT_LOCK_MISMATCH")
    paths=plan.get("required_targets")
    if not isinstance(paths,list) or paths != [s.format(slug=plan.get("slug")) for s in TARGETS]:
        raise DispatchBlocked("INVALID_TARGET_ORDER")
    if not isinstance(contents,dict) or set(contents) != set(paths):
        raise DispatchBlocked("INCOMPLETE_RELEASE_PAYLOAD")
    if contents[paths[0]] != rendered.get("html") or _digest(contents[paths[0]]) != rendered.get("public_html_sha256"):
        raise DispatchBlocked("PUBLIC_ARTICLE_PAYLOAD_MISMATCH")
    lease_shas=lease.get("remote_sha_expectations")
    if not isinstance(lease_shas,dict) or set(lease_shas)!=set(paths):
        raise DispatchBlocked("INCOMPLETE_SHA_LEASE")
    if "noindex" in contents[paths[0]].lower():
        raise DispatchBlocked("PRIVATE_PAGE_NOT_PUBLISHABLE")
    for path in paths[1:]:
        if plan["slug"] not in contents[path]:
            raise DispatchBlocked("MISSING_ARTICLE_LINK:"+path)
    report={
        "state":"PREFLIGHT_COMPLETE",
        "article_id":article_id,
        "github_only":True,
        "writes":[],
        "external_system_sync":"NOT_RUN",
        "live_render_qa":"NOT_RUN",
        "publication_complete":False
    }
    # Fresh reads of EVERY target precede the FIRST write. Prevent a stale lease
    # from causing an unintentional overwrite, even if an unrelated target moved.
    for path in paths:
        observed=adapter.read(path)
        expected=lease_shas[path]
        if observed != expected:
            report.update(state="BLOCKED_REMOTE_CHANGED",blocker=path)
            return report
    for path in paths:
        expected=lease_shas[path]
        result_sha=adapter.write(path,contents[path],expected)
        if not isinstance(result_sha,str) or len(result_sha)!=40:
            raise DispatchBlocked("WRITE_RECEIPT_NOT_SHA:"+path)
        observed_content=adapter.read_content(path)
        if _digest(observed_content)!=_digest(contents[path]):
            report.update(state="PARTIAL_READBACK_MISMATCH",blocker=path)
            return report
        report["writes"].append({"path":path,"returned_blob_sha":result_sha,
                                "readback_sha256":_digest(observed_content)})
    report["state"]="GITHUB_WRITES_READBACK_PASS"
    report["external_system_sync"]="PENDING_SHEETS_DRIVE_NOTION"
    report["live_render_qa"]="PENDING"
    report["publication_complete"]=False
    return report
