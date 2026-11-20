#!/usr/bin/env python3
"""Manual Windows commands for an approved, decoupled Radiology Intelligence release.

Unlike windows_ri_release.py this path publishes the validated GitHub site
first, then synchronizes providers in a separate command. Nothing is scheduled,
and this does not enroll a credential or merge a PR.

The site command requires the existing Google token for live native Sheet
duplicate rechecks and existing gh CLI authentication. The sync command also
requires a real independently evidenced Notion/provider writer scope.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from authorized_github_dispatch import execution_authorization_value
from connected_release_preflight import prepare_release_with_provider_reads
from github_contents_adapter import GitHubContentsAdapter
from native_provider_writeback import (
    NativeHTTP, NativeProviderAdapter,
)
from native_sheets_duplicate_guard import build_native_duplicate_guard
from native_sheets_reader import NativeSheetsReader
from publication_transaction import plan_publish, render_approved_public_html
from site_first_release import release_site, sync_records, SITE_DONE, SYNC_DONE
from windows_ri_release import (
    DATA, REPO, TOKEN_NAMES, PRIVATE_DOI, github_api,
    contents_via_gh, private_file, sheets_via_native_http,
)


def _get_approval(article_id, receipt_path, *, require_sync=False):
    plan = plan_publish(DATA, article_id)
    if plan["doi"] == PRIVATE_DOI:
        raise ValueError("PRIVATE_RESEARCH_CANDIDATE")
    article_dir = DATA / article_id
    source_bytes = private_file(article_dir / "article.json").read_bytes()
    status = json.loads(private_file(article_dir / "status.json").read_text(encoding="utf-8"))
    if (status.get("approval_sha256") != plan["approved_sha256"]
            or status.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest()):
        raise ValueError("APPROVED_ARTICLE_SOURCE_CHANGED")
    receipt = json.loads(private_file(receipt_path).read_text(encoding="utf-8"))
    if (receipt.get("article_id") != article_id
            or receipt.get("approved_sha256") != plan["approved_sha256"]
            or receipt.get("authorization") != execution_authorization_value(plan)
            or not isinstance(receipt.get("approval_ref"), str)
            or not receipt["approval_ref"].strip()):
        raise ValueError("ARTICLE_SPECIFIC_APPROVAL_RECEIPT_REQUIRED")
    date = datetime.fromisoformat(receipt["published_at"])
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("TIMEZONE_AWARE_PUBLICATION_DATE_REQUIRED")
    contract = receipt.get("source_contract")
    if not isinstance(contract, dict) or contract.get("source_kind") not in (
            "research_watch", "master_news"):
        raise ValueError("SOURCE_CONTRACT_REQUIRED")
    if require_sync:
        writer = receipt.get("single_writer") or {}
        scope = receipt.get("write_scope_attestation") or {}
        if (writer.get("article_id") != article_id
                or writer.get("approved_sha256") != plan["approved_sha256"]
                or writer.get("other_writers_excluded") is not True
                or not str(writer.get("evidence_ref") or "").strip()
                or scope.get("approved_sha256") != plan["approved_sha256"]):
            raise ValueError("INDEPENDENT_PROVIDER_WRITER_EVIDENCE_REQUIRED")
    return plan, receipt, json.loads(source_bytes)


def _site_snapshot(plan, receipt, github, sheets, *, recover_sha):
    path = DATA / plan["article_id"] / ("site-first-" + plan["approved_sha256"] + ".json")
    if recover_sha:
        raw = private_file(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != recover_sha:
            raise ValueError("ORIGINAL_SITE_PREFLIGHT_SHA_MISMATCH")
        saved = json.loads(raw)
        if saved.get("published_at") != receipt["published_at"]:
            raise ValueError("ORIGINAL_PUBLISHED_DATE_CHANGED")
        prepared = saved["prepared"]
    else:
        if path.exists():
            raise ValueError("SITE_SNAPSHOT_EXISTS_EXPLICIT_RECOVERY_REQUIRED")
        prepared = prepare_release_with_provider_reads(
            DATA, plan["article_id"], receipt["published_at"],
            github, sheets, receipt["source_contract"])
        if prepared["plan"] != plan:
            raise ValueError("APPROVED_PLAN_CHANGED_DURING_PREFLIGHT")
        raw = json.dumps(
            {"published_at": receipt["published_at"], "prepared": prepared},
            ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        with path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        print("ORIGINAL_SITE_PREFLIGHT_SHA256", hashlib.sha256(raw).hexdigest(), flush=True)
    if (prepared["plan"] != plan
            or prepared["source_contract"] != receipt["source_contract"]
            or prepared["bundle"]["rendered"] != render_approved_public_html(
                DATA, plan["article_id"], receipt["published_at"][:10])):
        raise ValueError("APPROVED_SITE_SNAPSHOT_IDENTITY_CHANGED")
    return prepared


def _fresh_reader_guard(sheets, prepared):
    def guard():
        current = sheets.read()  # actual authenticated fresh native Sheet fetch
        plan = prepared["plan"]
        return build_native_duplicate_guard(
            current["values"]["Master_Index"],
            current["values"]["MRI_Research_Watch"],
            plan["article_id"], plan["doi"],
            spreadsheet_id=current["spreadsheet_id"],
            read_ranges=current["read_ranges"],
            source_contract=prepared["source_contract"])
    return guard


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    pub = subs.add_parser("release-site")
    pub.add_argument("article_id")
    pub.add_argument("--receipt", required=True, type=Path)
    pub.add_argument("--recover", metavar="ORIGINAL_SITE_PREFLIGHT_SHA256")
    sync = subs.add_parser("sync-records")
    sync.add_argument("article_id")
    sync.add_argument("--receipt", required=True, type=Path)
    sync.add_argument("--site-snapshot-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"RI-[0-9]{3}", args.article_id):
            raise ValueError("INVALID_ARTICLE_ID")
        plan, receipt, source = _get_approval(
            args.article_id, args.receipt, require_sync=args.command == "sync-records")
        status, pr = github_api("GET", f"repos/{REPO}/pulls/3")
        if status != 200 or pr.get("merged") is not True or pr.get("draft") is not False:
            raise ValueError("APPROVED_SITE_COORDINATOR_NOT_ON_MAIN")
        github = GitHubContentsAdapter(
            REPO, "main", contents_via_gh, live_write_enabled=args.command == "release-site")
        google = os.environ.get(TOKEN_NAMES[0])
        if not google:
            raise ValueError("LOCAL_GOOGLE_TOKEN_REQUIRED")
        notion = os.environ.get(TOKEN_NAMES[1]) if args.command == "sync-records" else None
        if args.command == "sync-records" and not notion:
            raise ValueError("LOCAL_NOTION_TOKEN_REQUIRED")
        # Only an explicitly injected existing token is used by this MAIN-based
        # branch; PR #7 Credential Manager handling is not copied or merged.
        http = NativeHTTP(google, notion or "NOT_USED_FOR_SITE_ONLY")
        sheets = NativeSheetsReader(lambda url: sheets_via_native_http(http, url))
        prepared = _site_snapshot(
            plan, receipt, github, sheets,
            recover_sha=(args.recover if args.command == "release-site"
                         else args.site_snapshot_sha256))
        if args.command == "release-site":
            result = release_site(
                prepared, github, receipt["authorization"], DATA / "journal",
                fresh_duplicate_check=_fresh_reader_guard(sheets, prepared),
                recover=bool(args.recover))
            print(result["status"])
            return 0 if result["status"] in (SITE_DONE, "ALREADY_PUBLISHED_SYNC_PENDING") else 1
        rendered = prepared["bundle"]["rendered"]
        metadata = {
            "article_id": plan["article_id"], "doi": plan["doi"],
            "slug": plan["slug"], "published_url": plan["url"],
            "published_date": rendered["published_date"],
            "title": source["title"], "summary": source["summary"],
            "source": urlsplit(source["source_verification"]["source_url"]).netloc,
            "source_url": source["source_verification"]["source_url"],
            "why_it_matters": source["takeaway"],
        }
        provider = NativeProviderAdapter(
            http, metadata, rendered["html"], write_enabled=True,
            exclusive_writer_attested=True,
            write_scope_attestation=receipt["write_scope_attestation"],
            source_contract=prepared["source_contract"],
            record_components=prepared["record_components"])
        result = sync_records(
            prepared, github, receipt["authorization"], provider, DATA / "journal")
        print(result["status"])
        return 0 if result["status"] in (SYNC_DONE, "SYNC_ALREADY_DONE") else 1
    except (KeyError, OSError, ValueError, RuntimeError, TypeError) as error:
        code = str(error)
        print("BLOCKED", code if re.fullmatch(r"[A-Z0-9_]+", code) else type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
