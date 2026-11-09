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


def prepare_release_with_provider_reads(
        private_root,article_id,published_at,github_adapter,sheets_reader):
    """Live double-read data gate plus GitHub no-write preparation.

    Provider read provenance is the actual reader method invocation in this
    process. External Google access token and connected GitHub authentication
    remain the transports' responsibility. Never authorizes public writes.
    """
    from native_sheets_reader import NativeSheetsReader
    if not isinstance(sheets_reader,NativeSheetsReader):
        raise ValueError("NATIVE_SHEETS_READER_REQUIRED")
    initial=sheets_reader.read()
    result=prepare_connected_release_from_native_sheets(
        private_root,article_id,published_at,github_adapter,
        initial["values"]["Master_Index"],
        initial["values"]["MRI_Research_Watch"],
        initial["spreadsheet_id"],initial["read_ranges"])
    confirm=sheets_reader.read()
    if initial["sha256"]!=confirm["sha256"] or initial["tab_ids"]!=confirm["tab_ids"]:
        raise ValueError("NATIVE_SHEETS_CHANGED_DURING_PREFLIGHT")
    result["native_provider_read_receipt"]={
        "status":confirm["status"],
        "spreadsheet_id":confirm["spreadsheet_id"],
        "tab_ids":confirm["tab_ids"],
        "ranges":confirm["read_ranges"],
        "sha256":confirm["sha256"],
        "read_is_not_release_time_lease":True}
    result["ready_for_unattended_publication"]=False
    result["public_write_performed"]=False
    return result


def prepare_connected_release_from_native_sheets(
        private_root, article_id, published_at, adapter,
        master_values, watch_values, spreadsheet_id, read_ranges):
    """Bind provider-native row data to the approved no-write GitHub preflight.

    This wrapper checks the actual values supplied by a connector caller;
    it cannot authenticate the source of an in-memory array.
    """
    from native_sheets_duplicate_guard import build_native_duplicate_guard
    plan=plan_publish(private_root,article_id)
    checked=build_native_duplicate_guard(
        master_values,watch_values,article_id,plan["doi"],
        spreadsheet_id=spreadsheet_id,read_ranges=read_ranges)
    prepared=prepare_connected_github_release(
        private_root,article_id,published_at,adapter,
        published_dois=(),published_ids=())
    if prepared["plan"]["doi"]!=checked["doi"]:
        raise ValueError("NATIVE_SHEET_DOI_PREFLIGHT_MISMATCH")
    prepared["native_sheets_duplicate_guard"]=checked
    prepared["duplicate_guard_source"]="NATIVE_VALUES_CALLER_SUPPLIED_NOT_PROVIDER_ATTESTED"
    prepared["ready_for_unattended_publication"]=False
    return prepared


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
