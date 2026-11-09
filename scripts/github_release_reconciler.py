#!/usr/bin/env python3
"""Read-only reconciliation after a partially completed RI GitHub release.

Requires approved plan, original remote SHA lease and exact proposed payload.
All GitHub files are re-fetched. Never retries writes or declares external
Sheets/Drive/Notion/public HTTP release complete.
"""
from __future__ import annotations
import hashlib
import re
from publication_transaction import TARGETS


def _digest(s):
    if not isinstance(s,str):
        raise ValueError("NON_TEXT_GITHUB_READBACK")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _git_blob(s):
    raw=s.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()


def reconcile_github_release(plan,lease,contents,adapter):
    if not isinstance(plan,dict) or plan.get("status")!="READY_FOR_AUTHORIZED_DISPATCH":
        raise ValueError("APPROVED_PLAN_REQUIRED")
    if not isinstance(lease,dict) or lease.get("status")!="READY_FOR_CONDITIONAL_WRITE_PRECHECK":
        raise ValueError("SHA_LEASE_REQUIRED")
    paths=plan.get("required_targets")
    if paths!=[p.format(slug=plan.get("slug")) for p in TARGETS]:
        raise ValueError("INVALID_TARGET_ORDER")
    if lease.get("article_id")!=plan.get("article_id") or lease.get("approved_sha256")!=plan.get("approved_sha256"):
        raise ValueError("APPROVAL_LEASE_MISMATCH")
    originals=lease.get("remote_sha_expectations")
    if not isinstance(originals,dict) or set(originals)!=set(paths):
        raise ValueError("INCOMPLETE_SHA_LEASE")
    if not isinstance(contents,dict) or set(contents)!=set(paths):
        raise ValueError("INCOMPLETE_PAYLOAD")
    if any(not isinstance(contents[path],str) for path in paths):
        raise ValueError("NON_TEXT_RELEASE_PAYLOAD")
    if "noindex" in contents[paths[0]].lower():
        raise ValueError("PRIVATE_PREVIEW_NOT_PUBLIC")
    if any(plan["slug"] not in contents[path] for path in paths[1:]):
        raise ValueError("MISSING_RELEASE_LINK")
    observed={}
    for path in paths:
        # SHA before and after content read guards against mixed views.
        first=adapter.read(path)
        if first is None:
            observed[path]=(None,None)
        else:
            body=adapter.read_content(path)
            second=adapter.read(path)
            if first!=second or not isinstance(first,str) or not re.fullmatch(r"[a-f0-9]{40}",first):
                raise ValueError("REMOTE_CHANGED_DURING_RECONCILIATION:"+path)
            if _git_blob(body)!=first:
                raise ValueError("GITHUB_BLOB_SHA_CONTENT_MISMATCH:"+path)
            observed[path]=(first,_digest(body))
    states={}
    for path in paths:
        sha,digest=observed[path]
        target_digest=_digest(contents[path])
        old=originals[path]
        if sha is not None and digest==target_digest:
            states[path]="EXPECTED_NEW_CONTENT_PRESENT"
        elif sha==old:
            states[path]="UNCHANGED_FROM_PREPUBLICATION"
        else:
            states[path]="CONFLICT_OR_UNKNOWN_CONTENT"
    done=all(x=="EXPECTED_NEW_CONTENT_PRESENT" for x in states.values())
    conflicts=[p for p,x in states.items() if x=="CONFLICT_OR_UNKNOWN_CONTENT"]
    if conflicts:
        state="MANUAL_CONFLICT_REVIEW_REQUIRED"
    elif done:
        state="GITHUB_TARGETS_READBACK_MATCH"
    elif all(x=="UNCHANGED_FROM_PREPUBLICATION" for x in states.values()):
        state="NO_GITHUB_TARGETS_UPDATED"
    else:
        state="PARTIAL_GITHUB_TARGETS_PRESENT"
    return {
        "status":state,
        "article_id":plan["article_id"],
        "paths":states,
        "conflicts":conflicts,
        "any_remote_changes_detected":any(x=="EXPECTED_NEW_CONTENT_PRESENT" for x in states.values()),
        "github_target_readbacks_match":done,
        "manual_reconciliation_required":not done,
        "auto_retry_permitted":False,
        "sheets_drive_notion_sync_verified":False,
        "live_http_verified":False,
        "publication_complete":False,
        "public_write_performed_by_reconciler":False
    }
