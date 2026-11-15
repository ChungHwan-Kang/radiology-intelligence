#!/usr/bin/env python3
"""Connect approved preflight, GitHub dispatch/recovery, and live readback QA.

This module never creates approval, credentials, OAuth, or external data writes.
The caller must inject the already authenticated GitHub adapter and the exact
article/hash-bound authorization recorded after explicit user approval.
"""
from __future__ import annotations

from authorized_github_dispatch import dispatch_github_approved,resume_github_approved
from live_publication_verifier import fetch_public_text,verify_live_publication


def _release_parts(prepared):
    if not isinstance(prepared,dict) or prepared.get("status")!="CONNECTED_GITHUB_READONLY_PREFLIGHT_READY":
        raise ValueError("CONNECTED_READONLY_PREFLIGHT_REQUIRED")
    plan=prepared.get("plan")
    lease=prepared.get("lease")
    bundle=prepared.get("bundle")
    if not isinstance(bundle,dict) or bundle.get("status")!="APPROVED_SITE_PAYLOAD_READY_NOT_PUBLISHED":
        raise ValueError("APPROVED_SITE_BUNDLE_REQUIRED")
    if bundle.get("plan")!=plan:
        raise ValueError("PREFLIGHT_PLAN_BUNDLE_MISMATCH")
    rendered=bundle.get("rendered")
    contents=bundle.get("contents")
    return plan,lease,rendered,contents


def execute_prepared_github_release(prepared,adapter,execution_authorization,*,recover=False):
    """Execute or explicitly recover the five-file GitHub publication unit."""
    plan,lease,rendered,contents=_release_parts(prepared)
    operation=resume_github_approved if recover else dispatch_github_approved
    return operation(plan,lease,rendered,contents,adapter,execution_authorization)


def verify_prepared_live_release(prepared,github_report,fetch=fetch_public_text,**kwargs):
    """Run public HTTP QA only after all GitHub target readbacks match."""
    plan,_,_,contents=_release_parts(prepared)
    if not isinstance(github_report,dict) or github_report.get("state")!="GITHUB_WRITES_READBACK_PASS":
        raise ValueError("GITHUB_TARGET_READBACK_PASS_REQUIRED")
    return verify_live_publication(plan,contents,fetch=fetch,**kwargs)
