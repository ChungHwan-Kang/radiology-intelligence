#!/usr/bin/env python3
"""Two-stage approved RI release: GitHub+live QA, then retryable provider sync.

This module never creates approval or credentials. Both stages are explicitly
invoked by an authorized Windows operator. The existing GitHub SHA/CAS writer,
live verifier, canonical provider adapters and private journal are reused.
The old all-or-nothing entry point is deliberately unchanged.
"""
from __future__ import annotations

import hashlib

from approved_publication_runtime import (
    _release_parts, execute_prepared_github_release, verify_prepared_live_release,
)
from authorized_github_dispatch import execution_authorization_value
from connected_publication_coordinator import _release_components, _record, _sync_one
from durable_release_runner import PrivateReleaseJournal
from live_publication_verifier import fetch_public_text


SITE_DONE = "PUBLISHED_SYNC_PENDING"
SYNC_DONE = "PUBLISHED_SYNC_DONE"


class SiteFirstBlocked(ValueError):
    """No public or provider writes may follow an unverified boundary."""


def _identity(prepared, authorization):
    plan, _, _, contents = _release_parts(prepared)
    if authorization != execution_authorization_value(plan):
        raise SiteFirstBlocked("ARTICLE_SHA_APPROVAL_REQUIRED")
    source, components = _release_components(prepared)
    guard = prepared.get("native_sheets_duplicate_guard")
    receipt = prepared.get("native_provider_read_receipt")
    if (not isinstance(guard, dict)
            or guard.get("status") != "CALLER_NATIVE_SHEETS_DUPLICATE_GUARD_PASS"
            or guard.get("article_id") != plan["article_id"]
            or guard.get("doi") != plan["doi"]
            or guard.get("source_contract") != source
            or guard.get("record_components") != list(components)
            or not isinstance(receipt, dict)
            or receipt.get("spreadsheet_id") != "1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM"):
        raise SiteFirstBlocked("NATIVE_SHEET_DUPLICATE_GATE_REQUIRED")
    return plan, contents, components


def _site_history(history):
    for entry in history:
        f = entry["fields"]
        if f["event"] == "SITE_RESULT" and f["report"].get("status") == SITE_DONE:
            return True
    return False


def _live(prepared, fetch):
    return verify_prepared_live_release(
        prepared, {"state": "GITHUB_WRITES_READBACK_PASS"}, fetch=fetch
    )


def _fresh_duplicates(prepared, recheck):
    """Recheck authoritative native Sheet rows just before GitHub writes.

    recheck must perform NEW authenticated provider reads and re-run the
    canonical native duplicate guard. A caller-supplied result cannot by
    itself authenticate the provider; the production Windows CLI binds it.
    """
    if not callable(recheck):
        raise SiteFirstBlocked("FRESH_NATIVE_DUPLICATE_RECHECK_REQUIRED")
    current = recheck()
    before = prepared["native_sheets_duplicate_guard"]
    if (not isinstance(current, dict)
            or current.get("status") != "CALLER_NATIVE_SHEETS_DUPLICATE_GUARD_PASS"
            or any(current.get(k) != before.get(k) for k in (
                "article_id", "doi", "source_contract", "record_components"
            ))):
        raise SiteFirstBlocked("FRESH_NATIVE_DUPLICATE_RECHECK_FAILED")


def release_site(prepared, github_adapter, authorization, journal_dir, *,
                 fresh_duplicate_check, fetch=fetch_public_text, recover=False):
    """Publish five GitHub files with existing CAS, then verify actual live HTTP.

    Website publication is complete ONLY on SITE_DONE. Any failed/uncertain
    GitHub or live step retains a private recovery journal. Nothing here writes
    Sheets, Drive, Docs or Notion. No background retry is created.
    """
    plan, _, _ = _identity(prepared, authorization)
    with PrivateReleaseJournal(journal_dir, plan["article_id"], plan["approved_sha256"]) as journal:
        history = journal.entries()
        if _site_history(history):
            live = _live(prepared, fetch)
            return {"status": "ALREADY_PUBLISHED_SYNC_PENDING"
                    if live["status"] == "LIVE_PUBLICATION_QA_PASS" else "LIVE_QA_RECHECK_BLOCKED",
                    "article_id": plan["article_id"], "live": live,
                    "journal": str(journal.path), "public_write_performed": False}
        if journal.preexisting and not recover:
            return {"status": "EXPLICIT_RECOVERY_REQUIRED",
                    "journal": str(journal.path), "public_write_performed": False}
        _fresh_duplicates(prepared, fresh_duplicate_check)
        journal.append("SITE_ATTEMPT", {"recover": bool(recover)})
        github = execute_prepared_github_release(
            prepared, github_adapter, authorization, recover=recover
        )
        journal.append("SITE_GITHUB", github)
        if github.get("state") != "GITHUB_WRITES_READBACK_PASS":
            return {"status": "GITHUB_PARTIAL_RECONCILE_REQUIRED",
                    "github": github, "journal": str(journal.path),
                    "publication_complete": False}
        live = _live(prepared, fetch)
        journal.append("SITE_LIVE", live)
        if live.get("status") != "LIVE_PUBLICATION_QA_PASS":
            return {"status": "LIVE_QA_PENDING", "live": live,
                    "journal": str(journal.path), "publication_complete": False}
        result = {"status": SITE_DONE, "article_id": plan["article_id"],
                  "approved_sha256": plan["approved_sha256"],
                  "github": github, "live": live,
                  "publication_complete": True,
                  "external_system_sync": "PENDING",
                  "sync_complete": False}
        journal.append("SITE_RESULT", result)
        return {**result, "journal": str(journal.path), "durable_result_saved": True}


def sync_records(prepared, github_adapter, authorization, provider_adapter,
                 journal_dir, *, fetch=fetch_public_text):
    """Retry provider records independently after successful site publication.

    The provider's EXISTING actual-write-scope and external-writer attestation
    remains mandatory for this phase. No GitHub mutations occur here. Each
    provider component uses read-before-create for loss-of-ACK recovery.
    """
    plan, contents, components = _identity(prepared, authorization)
    with PrivateReleaseJournal(journal_dir, plan["article_id"], plan["approved_sha256"]) as journal:
        history = journal.entries()
        if not journal.preexisting or not _site_history(history):
            raise SiteFirstBlocked("VERIFIED_SITE_PUBLICATION_REQUIRED")
        if any(e["fields"]["event"] == "SYNC_RESULT"
               and e["fields"]["report"].get("status") == SYNC_DONE for e in history):
            return {"status": "SYNC_ALREADY_DONE", "journal": str(journal.path)}
        # Recheck the actual current GitHub article/index/category/RSS/sitemap.
        # A hash mismatch or unreadable path blocks ALL provider writes.
        for path, expected in contents.items():
            observed = github_adapter.read_content(path)
            if hashlib.sha256(observed.encode("utf-8")).digest() != hashlib.sha256(
                    expected.encode("utf-8")).digest():
                raise SiteFirstBlocked("GITHUB_SITE_CHANGED_BEFORE_SYNC")
        live = _live(prepared, fetch)
        if live.get("status") != "LIVE_PUBLICATION_QA_PASS":
            raise SiteFirstBlocked("LIVE_PUBLICATION_QA_REQUIRED_BEFORE_SYNC")
        provider_adapter.local_lock_held = True
        try:
            readiness = provider_adapter.assert_ready(list(components))
            if (not isinstance(readiness, dict)
                    or readiness.get("status") != "ALL_TARGETS_READ_WRITE_READY"
                    or tuple(readiness.get("components", ())) != components
                    or readiness.get("actual_write_scopes_verified") is not True
                    or readiness.get("caller_single_writer_lease_attested") is not True):
                raise SiteFirstBlocked("PROVIDER_WRITE_AND_EXTERNAL_LOCK_REQUIRED")
            journal.append("SYNC_ATTEMPT", {"components": list(components)})
            written = []
            for component in components:
                try:
                    receipt = _sync_one(provider_adapter, component, _record(prepared, component))
                    written.append(receipt)
                    journal.append("SYNC_COMPONENT", receipt)
                except Exception as exc:
                    result = {"status": "SYNC_PENDING_RETRY", "blocker": component,
                              "error_type": type(exc).__name__, "writeback": written}
                    journal.append("SYNC_RESULT", result)
                    return {**result, "journal": str(journal.path),
                            "publication_complete": True, "sync_complete": False}
            result = {"status": SYNC_DONE, "article_id": plan["article_id"],
                      "writeback": written, "publication_complete": True,
                      "sync_complete": True}
            journal.append("SYNC_RESULT", result)
            return {**result, "journal": str(journal.path), "durable_result_saved": True}
        finally:
            provider_adapter.local_lock_held = False
