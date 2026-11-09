#!/usr/bin/env python3
"""Read-only connected GitHub release preflight for a SHA-locked approved article.

The adapter can be backed by GitHub Contents API, but this module only calls
read() and read_content(). It never invokes a remote write. The returned
payload is private and must not be committed to a public repository.
"""
from __future__ import annotations

from publication_transaction import (
    plan_publish, prepare_approved_site_bundle, prepare_github_sha_lease
)

INDEX_PATHS=("index.html","categories.html","feed.xml","sitemap.xml")


def prepare_connected_github_release(private_root, article_id, published_at,
                                     adapter, published_dois, published_ids):
    """Fetch fresh GitHub objects, then build a private, no-write 5-file plan.

    Callers must separately query authoritative Sheets for ID/DOI duplicates
    and supply those lists; this helper cannot independently verify them.
    """
    if published_dois is None or published_ids is None:
        raise ValueError("AUTHORITATIVE_DUPLICATE_GUARD_INPUT_REQUIRED")
    # Approval and its exact source/HTML bytes checked before any remote fetch.
    plan=plan_publish(private_root,article_id,published_dois,published_ids)
    current_sha={}
    current_site={}
    # Read content first, then acquire a second SHA snapshot. If a concurrent
    # publisher changes any object between reads, fail rather than compose
    # from an obsolete baseline.
    for path in INDEX_PATHS:
        current_site[path]=adapter.read_content(path)
    for path in plan["required_targets"]:
        current_sha[path]=adapter.read(path)
    for path in INDEX_PATHS:
        second=adapter.read_content(path)
        if second!=current_site[path]:
            raise ValueError("REMOTE_CONTENT_CHANGED_DURING_PREFLIGHT:"+path)
    lease=prepare_github_sha_lease(plan,current_sha)
    bundle=prepare_approved_site_bundle(private_root,article_id,published_at,current_site)
    if bundle["plan"]["approved_sha256"]!=plan["approved_sha256"]:
        raise ValueError("APPROVED_PLAN_CHANGED_DURING_PREFLIGHT")
    if bundle["plan"]["doi"]!=plan["doi"]:
        raise ValueError("APPROVED_DOI_CHANGED_DURING_PREFLIGHT")
    return {
        "status":"CONNECTED_GITHUB_READONLY_PREFLIGHT_READY",
        "article_id":article_id,
        "plan":plan,
        "lease":lease,
        "bundle":bundle,
        "github_blob_shas":current_sha,
        "duplicate_guard_source":"CALLER_REPORTED_NOT_INDEPENDENTLY_VERIFIED",
        "public_write_performed":False,
        "external_sync_performed":False,
        "ready_for_unattended_publication":False
    }
