#!/usr/bin/env python3
"""Approval-locked, fail-closed coordination of RI publication and writeback.

This module does NOT obtain credentials or configure a job. An authorized caller
injects authenticated GitHub and provider-specific adapters, and preserves
the return report privately. Provider adapters must implement:

    assert_ready(components) -> {"status": "ALL_TARGETS_READ_WRITE_READY",\n                                  "components": complete list}\n    read(component, article_id) -> None or {
        "record": exact canonical record dict, "revision": provider revision,
        "evidence_ref": provider-native URL / id
    }
    create(component, record, expected_absent=True) -> provider receipt

create MUST be conditional on absence of that article identity and may not
silently replace an unrelated record. Before retrying an uncertain result, the
coordinator re-reads the provider; it never blindly creates a second record.
This is an integration boundary, NOT an implementation of Google or Notion auth.
"""
from __future__ import annotations

import hashlib
import json
import re

from approved_publication_runtime import (
    _release_parts, execute_prepared_github_release, verify_prepared_live_release
)
from authorized_github_dispatch import execution_authorization_value
from live_publication_verifier import fetch_public_text

RECORD_COMPONENTS = (
    "sheets_master",
    "sheets_watch",
    "drive_published_copy",
    "current_handoff",
    "notion",
)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def private_candidate_preflight(candidate):
    """Allow inspection of a no-ID research draft, never a simulated approval."""
    if not isinstance(candidate, dict):
        raise ValueError("PRIVATE_CANDIDATE_REQUIRED")
    if candidate.get("article_id") or candidate.get("approved_sha256"):
        raise ValueError("NOT_A_NO_ID_PRIVATE_CANDIDATE")
    return {
        "status": "PRIVATE_RESEARCH_ONLY",
        "source": candidate.get("source", "PRIVATE_CANDIDATE"),
        "release_eligible": False,
        "public_write_performed": False,
        "provider_write_performed": False,
        "reason": "ARTICLE_SPECIFIC_ID_HASH_APPROVAL_NOT_PRESENT",
    }


def _record(prepared, component):
    plan, _, _, contents = _release_parts(prepared)
    if component not in RECORD_COMPONENTS:
        raise ValueError("UNKNOWN_WRITEBACK_COMPONENT")
    post_path = plan["required_targets"][0]
    meta = {
        "article_id": plan["article_id"],
        "doi": plan["doi"],
        "slug": plan["slug"],
        "published_url": plan["url"],
        "approved_private_sha256": plan["approved_sha256"],
        "published_html_sha256": _digest(contents[post_path]),
        "component": component,
    }
    # The adapter maps this identity to its existing canonical schema. This
    # record is deliberately not a guessed Sheet row / Notion property payload.
    return meta


def _validate_read(component, article_id, observed):
    if observed is None:
        return None
    if not isinstance(observed, dict):
        raise ValueError("INVALID_PROVIDER_READBACK:" + component)
    record = observed.get("record")
    if not isinstance(record, dict) or record.get("article_id") != article_id:
        raise ValueError("PROVIDER_IDENTITY_MISMATCH:" + component)
    ref = observed.get("evidence_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("PROVIDER_EVIDENCE_REF_REQUIRED:" + component)
    return observed


def _sync_one(adapter, component, record):
    article_id = record["article_id"]
    # Read-before-create supports re-entry following a network timeout. No
    # "overwrite" path is available, so conflicting records stop the release.
    before = _validate_read(component, article_id, adapter.read(component, article_id))
    if before is not None:
        if before["record"] != record:
            raise ValueError("PROVIDER_RECORD_CONFLICT:" + component)
        return {
            "component": component,
            "action": "ALREADY_PRESENT_VERIFIED",
            "evidence_ref": before["evidence_ref"],
            "sha256": _digest(json.dumps(record, sort_keys=True)),
        }

    # A failed create could have committed remotely. The caller must persist
    # PARTIAL outcome and call this function afresh, which always re-reads.
    adapter.create(component, record, expected_absent=True)
    after = _validate_read(component, article_id, adapter.read(component, article_id))
    if after is None or after["record"] != record:
        raise ValueError("PROVIDER_WRITE_READBACK_MISMATCH:" + component)
    return {
        "component": component,
        "action": "CREATED_AND_READBACK_VERIFIED",
        "evidence_ref": after["evidence_ref"],
        "sha256": _digest(json.dumps(record, sort_keys=True)),
    }


def run_approved_connected_release(prepared, github_adapter, authorization,
                                   provider_adapter, *, fetch=fetch_public_text,
                                   recover=False):
    """Run the postapproval unit, stopping at the first uncertain boundary.

    The approval event MUST originate outside this module. A generated
    authorization phrase is necessary but is not by itself evidence of consent.
    All provider receipts are adapter-attested, not an independent OAuth audit.
    """
    plan, _, _, _ = _release_parts(prepared)
    if authorization != execution_authorization_value(plan):
        raise ValueError("ARTICLE_HASH_AUTHORIZATION_REQUIRED")
    report = {
        "article_id": plan["article_id"],
        "approved_sha256": plan["approved_sha256"],
        "status": "PRECHECK",
        "github": None,
        "live": None,
        "writeback": [],
        "provider_authentication_independently_verified": False,
        "publication_complete": False,
        "public_write_attempted": False,
    }
    # Provider capability/read-only conflict checks must precede irreversible
    # GitHub writes. This does not establish independent OAuth provenance.
    try:
        readiness = provider_adapter.assert_ready(RECORD_COMPONENTS)
        if not isinstance(readiness, dict) or readiness.get("status") != "ALL_TARGETS_READ_WRITE_READY":
            raise ValueError("PROVIDER_READ_WRITE_CAPABILITIES_NOT_READY")
        if set(readiness.get("components", [])) != set(RECORD_COMPONENTS):
            raise ValueError("PROVIDER_COMPONENT_SET_INCOMPLETE")
        # A GET-only provider must never authorize irreversible GitHub writes.
        # Provider capability is established separately by an authorized
        # operator/runner and must be proven rather than inferred from GETs.
        if readiness.get("actual_write_scopes_verified") is not True:
            raise ValueError("PROVIDER_WRITE_SCOPES_NOT_VERIFIED")
        if readiness.get("caller_single_writer_lease_attested") is not True:
            raise ValueError("PROVIDER_SINGLE_WRITER_LOCK_NOT_ATTESTED")
        for component in RECORD_COMPONENTS:
            expected = _record(prepared, component)
            observed = _validate_read(
                component, plan["article_id"],
                provider_adapter.read(component, plan["article_id"]))
            if observed is not None and observed["record"] != expected:
                raise ValueError("PREPUBLICATION_PROVIDER_RECORD_CONFLICT:" + component)
    except Exception as exc:
        report.update(status="EXTERNAL_PREFLIGHT_BLOCKED", blocker="provider",
                      error_type=type(exc).__name__,
                      recovery_action="FIX_PROVIDER_PERMISSIONS_OR_CONFLICT_BEFORE_RELEASE")
        return report
    report["external_preflight"] = "ADAPTER_ATTESTED_READY"

    try:
        github = execute_prepared_github_release(
            prepared, github_adapter, authorization, recover=recover
        )
    except Exception as exc:
        report.update(status="GITHUB_OUTCOME_UNKNOWN",
                      blocker="github", error_type=type(exc).__name__,
                      recovery_action="RECONCILE_GITHUB_BEFORE_RETRY")
        return report
    report["github"] = github
    report["public_write_attempted"] = True
    if github.get("state") != "GITHUB_WRITES_READBACK_PASS":
        report.update(status="GITHUB_PARTIAL_OR_BLOCKED",
                      blocker=github.get("blocker", "github"),
                      recovery_action="RECONCILE_GITHUB_BEFORE_RETRY")
        return report

    try:
        live = verify_prepared_live_release(prepared, github, fetch=fetch)
    except Exception as exc:
        report.update(status="LIVE_QA_UNKNOWN", blocker="live",
                      error_type=type(exc).__name__,
                      recovery_action="VERIFY_LIVE_BEFORE_WRITEBACK")
        return report
    report["live"] = live
    if live.get("status") != "LIVE_PUBLICATION_QA_PASS":
        report.update(status="LIVE_QA_BLOCKED", blocker=live.get("failed_path", "live"),
                      recovery_action="VERIFY_DEPLOYMENT_BEFORE_WRITEBACK")
        return report

    # Google and Notion records are separate provider transactions. Failure is
    # not a rollback; resume safely using read-before-create on every target.
    for component in RECORD_COMPONENTS:
        record = _record(prepared, component)
        try:
            receipt = _sync_one(provider_adapter, component, record)
        except Exception as exc:
            report.update(status="EXTERNAL_WRITEBACK_PARTIAL",
                          blocker=component, error_type=type(exc).__name__,
                          recovery_action="REREAD_COMPONENT_AND_RESUME")
            return report
        report["writeback"].append(receipt)
    report["status"] = "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS"
    report["external_records_count"] = len(report["writeback"])
    report["requires_independent_provider_operational_acceptance"] = True
    # This library cannot independently verify the injected provider identity,
    # the real approval event, or transaction-log durability.
    return report
