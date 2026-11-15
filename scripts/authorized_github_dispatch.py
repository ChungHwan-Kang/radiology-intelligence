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


def execution_authorization_value(plan):
    """Return the exact, article-and-review-hash-bound execution phrase.

    This value is not a credential and does not create approval. The caller may
    supply it only after the user explicitly authorizes this exact article and
    approved review hash for public GitHub dispatch.
    """
    if not isinstance(plan,dict) or plan.get("status")!="READY_FOR_AUTHORIZED_DISPATCH":
        raise DispatchBlocked("APPROVED_ARTICLE_PLAN_REQUIRED")
    article_id=plan.get("article_id")
    approved=plan.get("approved_sha256")
    if not isinstance(article_id,str) or not isinstance(approved,str) or len(approved)!=64:
        raise DispatchBlocked("INVALID_APPROVAL_IDENTITY")
    return "EXECUTE_APPROVED_GITHUB_PUBLICATION:"+article_id+":"+approved


def _validate_release(plan,lease,rendered,contents,approval_token):
    if approval_token != execution_authorization_value(plan):
        raise DispatchBlocked("EXPLICIT_ARTICLE_HASH_AUTHORIZATION_REQUIRED")
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
    return article_id,paths,lease_shas


def _write_paths(report,paths,lease_shas,contents,adapter):
    for path in paths:
        expected=lease_shas[path]
        try:
            result_sha=adapter.write(path,contents[path],expected)
            if not isinstance(result_sha,str) or len(result_sha)!=40:
                raise DispatchBlocked("WRITE_RECEIPT_NOT_SHA:"+path)
            observed_content=adapter.read_content(path)
        except Exception as exc:
            report.update(state="PARTIAL_WRITE_OUTCOME_UNKNOWN",blocker=path,
                          recovery_action="REFETCH_REMOTE_AND_RECONCILE_BEFORE_RETRY",
                          error_type=type(exc).__name__)
            return report
        if _digest(observed_content)!=_digest(contents[path]):
            report.update(state="PARTIAL_READBACK_MISMATCH",blocker=path,
                          recovery_action="REFETCH_REMOTE_AND_RECONCILE_BEFORE_RETRY")
            return report
        report["writes"].append({"path":path,"returned_blob_sha":result_sha,
                                "readback_sha256":_digest(observed_content)})
    return report


def dispatch_github_approved(plan, lease, rendered, contents, adapter, approval_token):
    """Try one ordered GitHub release; stop at first failed remote verification.

    A returned PARTIAL status must be preserved by the caller. A network
    exception deliberately propagates rather than guessing whether a write
    took place; recheck the remote before any manual retry.
    """
    article_id,paths,lease_shas=_validate_release(
        plan,lease,rendered,contents,approval_token)
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
    report=_write_paths(report,paths,lease_shas,contents,adapter)
    if report["state"]!="PREFLIGHT_COMPLETE":
        return report
    report["state"]="GITHUB_WRITES_READBACK_PASS"
    report["external_system_sync"]="PENDING_SHEETS_DRIVE_NOTION"
    report["live_render_qa"]="PENDING"
    report["publication_complete"]=False
    return report


def resume_github_approved(plan,lease,rendered,contents,adapter,approval_token):
    """Reconcile an interrupted release and write only untouched targets.

    This is an explicit recovery operation using the same article/hash-bound
    authorization. Expected new content is never written again. Conflicting
    content always requires manual review.
    """
    article_id,paths,lease_shas=_validate_release(
        plan,lease,rendered,contents,approval_token)
    from github_release_reconciler import reconcile_github_release
    reconciliation=reconcile_github_release(plan,lease,contents,adapter)
    if reconciliation["status"]=="MANUAL_CONFLICT_REVIEW_REQUIRED":
        return {"state":"RECOVERY_BLOCKED_CONFLICT","article_id":article_id,
                "reconciliation":reconciliation,"writes":[],
                "publication_complete":False}
    if reconciliation["status"]=="GITHUB_TARGETS_READBACK_MATCH":
        return {"state":"GITHUB_WRITES_READBACK_PASS","article_id":article_id,
                "reconciliation":reconciliation,"writes":[],
                "already_present":list(paths),"publication_complete":False,
                "external_system_sync":"PENDING_SHEETS_DRIVE_NOTION",
                "live_render_qa":"PENDING"}
    states=reconciliation["paths"]
    if any(state not in ("EXPECTED_NEW_CONTENT_PRESENT","UNCHANGED_FROM_PREPUBLICATION")
           for state in states.values()):
        raise DispatchBlocked("RECOVERY_STATE_NOT_SAFE")
    remaining=[path for path in paths if states[path]=="UNCHANGED_FROM_PREPUBLICATION"]
    report={"state":"RECOVERY_PREFLIGHT_COMPLETE","article_id":article_id,
            "github_only":True,"writes":[],
            "already_present":[path for path in paths if path not in remaining],
            "reconciliation":reconciliation,"external_system_sync":"NOT_RUN",
            "live_render_qa":"NOT_RUN","publication_complete":False}
    # Recheck all five targets immediately before resuming. Already completed
    # targets must still match the exact payload; untouched targets must still
    # match the original SHA lease.
    for path in paths:
        if states[path]=="EXPECTED_NEW_CONTENT_PRESENT":
            try:
                if _digest(adapter.read_content(path))!=_digest(contents[path]):
                    report.update(state="RECOVERY_BLOCKED_REMOTE_CHANGED",blocker=path)
                    return report
            except Exception as exc:
                report.update(state="RECOVERY_READ_FAILED",blocker=path,
                              error_type=type(exc).__name__)
                return report
        elif adapter.read(path)!=lease_shas[path]:
            report.update(state="RECOVERY_BLOCKED_REMOTE_CHANGED",blocker=path)
            return report
    report=_write_paths(report,remaining,lease_shas,contents,adapter)
    if report["state"]!="RECOVERY_PREFLIGHT_COMPLETE":
        return report
    final=reconcile_github_release(plan,lease,contents,adapter)
    report["reconciliation_after_resume"]=final
    if final["status"]!="GITHUB_TARGETS_READBACK_MATCH":
        report["state"]="RECOVERY_FINAL_READBACK_FAILED"
        return report
    report.update(state="GITHUB_WRITES_READBACK_PASS",
                  external_system_sync="PENDING_SHEETS_DRIVE_NOTION",
                  live_render_qa="PENDING")
    return report
