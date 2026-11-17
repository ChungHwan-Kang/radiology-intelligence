"""Manual Windows entry point for the existing RI release modules."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from authorized_github_dispatch import execution_authorization_value
from connected_release_preflight import prepare_release_with_provider_reads
from durable_release_runner import run_durably
from github_contents_adapter import GitHubContentsAdapter
from native_provider_writeback import (
    DRIVE_FOLDER, HANDOFF_DOC, NOTION_PAGE, SHEET_ID, NativeHTTP, NativeProviderAdapter,
)
from native_sheets_reader import NativeSheetsReader
from publication_transaction import plan_publish, render_approved_public_html
from windows_ri_credentials import CredentialError, enroll_google, enroll_notion, provider_token


REPO = "ChungHwan-Kang/radiology-intelligence"
CONTENTS = f"https://api.github.com/repos/{REPO}/contents/"
DATA = Path(r"D:\Development\LocalData\Radiology_Intelligence")
TOKEN_NAMES = ("RI_GOOGLE_ACCESS_TOKEN", "RI_NOTION_TOKEN")
PRIVATE_DOI = "10.1186/s13244-026-02459-2"


def github_api(method, endpoint, payload=None):
    args = ["gh", "api", "--hostname", "github.com", "--include", "--method", method, endpoint]
    body = None
    if payload is not None:
        args.extend(("--input", "-"))
        body = json.dumps(payload).encode("utf-8")
    excluded = {*TOKEN_NAMES, "GH_TOKEN", "GITHUB_TOKEN", "GH_DEBUG"}
    env = {name: value for name, value in os.environ.items() if name not in excluded}
    response = subprocess.run(args, input=body, capture_output=True, timeout=45, env=env)
    headers, _, raw = response.stdout.replace(b"\r\n", b"\n").partition(b"\n\n")
    match = re.match(rb"HTTP/\S+ ([0-9]{3})", headers)
    if match is None:
        raise RuntimeError("GITHUB_CLI_HTTP_OUTCOME_UNKNOWN")
    status = int(match[1])
    if status >= 400:
        return status, {}
    if response.returncode:
        raise RuntimeError("GITHUB_CLI_HTTP_OUTCOME_UNKNOWN")
    return status, json.loads(raw)


def contents_via_gh(method, url, payload):
    if not url.startswith(CONTENTS) or method not in {"GET", "PUT"}:
        raise ValueError("UNEXPECTED_GITHUB_CONTENTS_REQUEST")
    return github_api(method, url, payload)


def sheets_via_native_http(http, url):
    origin = "https://sheets.googleapis.com"
    if not url.startswith(origin + "/v4/spreadsheets/"):
        raise ValueError("NON_GOOGLE_SHEETS_URL")
    return 200, http.call("google", "GET", "/sheets" + url[len(origin):])


def private_file(path):
    resolved = path.resolve(strict=True)
    base = DATA.resolve(strict=True)
    if not resolved.is_relative_to(base) or any(
        (p / ".git").exists() for p in (resolved.parent, *resolved.parent.parents)
    ):
        raise ValueError("RI_PRIVATE_PATH_REQUIRED")
    return resolved


def read_inputs(args):
    article_dir = DATA / args.article_id
    for filename in ("status.json", "article.json", "review.html"):
        path = article_dir / filename
        if private_file(path) != path.absolute():
            raise ValueError("RI_STAGING_LINK_DENIED")
    plan = plan_publish(DATA, args.article_id)
    source_bytes = (article_dir / "article.json").read_bytes()
    state = json.loads((article_dir / "status.json").read_bytes())
    if (state.get("approval_sha256") != plan["approved_sha256"]
            or state.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest()):
        raise ValueError("APPROVED_SOURCE_CHANGED")
    if plan["doi"] == PRIVATE_DOI:
        raise ValueError("PRIVATE_RESEARCH_CANDIDATE")
    receipt = json.loads(private_file(args.receipt).read_bytes())
    if (
        receipt.get("authorization") != execution_authorization_value(plan)
        or receipt.get("article_id") != plan["article_id"]
        or receipt.get("approved_sha256") != plan["approved_sha256"]
        or not str(receipt.get("approval_ref") or "").strip()
    ):
        raise ValueError("ARTICLE_APPROVAL_EVENT_REQUIRED")
    writer = receipt.get("single_writer") or {}
    if (
        writer.get("article_id") != plan["article_id"]
        or writer.get("approved_sha256") != plan["approved_sha256"]
        or not str(writer.get("evidence_ref") or "").strip()
        or writer.get("other_writers_excluded") is not True
    ):
        raise ValueError("EXTERNAL_SINGLE_WRITER_EVIDENCE_REQUIRED")
    attestation = receipt.get("write_scope_attestation") or {}
    if attestation.get("approved_sha256") != plan["approved_sha256"]:
        raise ValueError("ARTICLE_BOUND_PROVIDER_WRITE_EVIDENCE_REQUIRED")
    source_contract=receipt.get("source_contract")
    if not isinstance(source_contract,dict) or source_contract.get("source_kind") not in (
            "research_watch","master_news"):
        raise ValueError("EXPLICIT_SOURCE_CONTRACT_REQUIRED")
    return plan, receipt, article_dir, json.loads(source_bytes)


def run_release(args):
    plan, receipt, article_dir, source = read_inputs(args)
    status, pr = github_api("GET", f"repos/{REPO}/pulls/3")
    if status != 200 or pr.get("draft") is not False or pr.get("merged") is not True:
        raise ValueError("RI_PR_NOT_APPROVED_FOR_PRODUCTION")
    google, notion = (
        provider_token(service, os.environ.get(name))
        for service, name in zip(("google", "notion"), TOKEN_NAMES)
    )
    github = GitHubContentsAdapter(REPO, "main", contents_via_gh, live_write_enabled=True)
    http = NativeHTTP(google, notion)
    published_at = receipt["published_at"]
    snapshot = article_dir / ("release-" + plan["approved_sha256"] + ".json")
    if args.recover:
        if private_file(snapshot) != snapshot.absolute():
            raise ValueError("RI_STAGING_LINK_DENIED")
        data = snapshot.read_bytes()
        if hashlib.sha256(data).hexdigest() != args.recover:
            raise ValueError("ORIGINAL_PREFLIGHT_SHA_MISMATCH")
        saved = json.loads(data)
        if saved["published_at"] != published_at or saved["prepared"]["plan"] != plan:
            raise ValueError("ORIGINAL_RELEASE_IDENTITY_MISMATCH")
        prepared = saved["prepared"]
    else:
        if snapshot.exists():
            raise ValueError("ORIGINAL_PREFLIGHT_EXISTS_USE_EXPLICIT_RECOVERY")
        sheets = NativeSheetsReader(lambda url: sheets_via_native_http(http, url))
        prepared = prepare_release_with_provider_reads(
            DATA, args.article_id, published_at, github, sheets,
            receipt["source_contract"]
        )
        if prepared["plan"] != plan:
            raise ValueError("APPROVED_PLAN_CHANGED_DURING_PREFLIGHT")
    if prepared.get("source_contract")!=receipt["source_contract"]:
        raise ValueError("APPROVED_SOURCE_CONTRACT_CHANGED")
    if tuple(receipt["write_scope_attestation"].get("components",()))!=tuple(
            prepared.get("record_components",())):
        raise ValueError("APPROVED_PROVIDER_COMPONENTS_CHANGED")
    rendered = prepared["bundle"]["rendered"]
    if rendered != render_approved_public_html(DATA, args.article_id, published_at[:10]):
        raise ValueError("APPROVED_PUBLIC_RENDER_MISMATCH")
    source_url = source["source_verification"]["source_url"]
    metadata = {
        "article_id": plan["article_id"], "doi": plan["doi"], "slug": plan["slug"],
        "published_url": plan["url"], "published_date": rendered["published_date"],
        "title": source["title"], "summary": source["summary"],
        "source": urlsplit(source_url).netloc, "source_url": source_url,
        "why_it_matters": source["takeaway"],
    }
    provider = NativeProviderAdapter(
        http, metadata, rendered["html"], write_enabled=True,
        exclusive_writer_attested=True, write_scope_attestation=receipt["write_scope_attestation"],
        source_contract=prepared["source_contract"],
        record_components=prepared["record_components"],
    )
    # Retain the rendered publication payload and original SHA expectations only.
    # Reacquiring them after a partial write could destroy the recovery baseline.
    if not args.recover:
        data = json.dumps({"published_at": published_at, "prepared": prepared}).encode("utf-8")
        with snapshot.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        print("RECOVERY_SHA256", hashlib.sha256(data).hexdigest(), flush=True)
    result = run_durably(
        prepared, github, receipt["authorization"], provider, DATA / "journal",
        recover=bool(args.recover),
    )
    print(result["status"])
    return 0 if result["status"] == "ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS" else 1


def check_connections():
    github = GitHubContentsAdapter(REPO, "main", contents_via_gh)
    if not github.read("feed.xml"):
        raise ValueError("GITHUB_PUBLICATION_TARGET_NOT_FOUND")
    print("GITHUB_CONTENTS_READ PASS")
    tokens = []
    for service, name in zip(("google", "notion"), TOKEN_NAMES):
        try:
            tokens.append(provider_token(service, os.environ.get(name)))
        except CredentialError as error:
            print(f"{service.upper()}_AUTH BLOCKED", error)
    if len(tokens) != len(TOKEN_NAMES):
        return 1

    http = NativeHTTP(*tokens)
    targets = (
        ("SHEETS", "google", f"/sheets/v4/spreadsheets/{SHEET_ID}?fields=spreadsheetId",
         "spreadsheetId", SHEET_ID),
        ("DRIVE", "google", f"/drive/v3/files/{DRIVE_FOLDER}?fields=id",
         "id", DRIVE_FOLDER),
        ("DOCS", "google", f"/docs/v1/documents/{HANDOFF_DOC}?fields=documentId",
         "documentId", HANDOFF_DOC),
        ("NOTION", "notion", f"/v1/pages/{NOTION_PAGE}", "id", NOTION_PAGE),
    )
    ready = True
    for label, service, path, field, expected in targets:
        try:
            result = http.call(service, "GET", path)
        except (ValueError, OSError) as error:
            match = re.fullmatch(r"(?:GOOGLE|NOTION)_HTTP_(\d{3})", str(error))
            code = {
                "401": "CREDENTIAL_REAUTHORIZATION_REQUIRED",
                "403": "TARGET_ACCESS_DENIED",
                "404": "TARGET_UNAVAILABLE_OR_NOT_SHARED",
            }.get(match[1] if match else None, "READ_FAILED")
            print(f"{label}_READ BLOCKED", code)
            ready = False
            continue
        actual = result.get(field)
        if service == "notion" and isinstance(actual, str) and len(actual) == 32:
            expected = expected.replace("-", "")
        if actual != expected:
            print(f"{label}_READ BLOCKED CANONICAL_TARGET_MISMATCH")
            ready = False
            continue
        print(f"{label}_READ PASS")
    print("PROVIDER_WRITE_PERMISSIONS NOT_VERIFIED")
    return 0 if ready else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Read-only authentication and target checks")
    enroll = commands.add_parser("auth-enroll", help="Explicitly enroll existing provider credentials in Windows")
    method = enroll.add_mutually_exclusive_group(required=True)
    method.add_argument("--google-client", type=Path, help="Existing RI Desktop OAuth client JSON")
    method.add_argument("--notion", action="store_true", help="Enroll the existing Notion RI internal connection")
    release = commands.add_parser("release", help="Run a separately authorized manual release")
    release.add_argument("article_id")
    release.add_argument("--receipt", type=Path, required=True, help="External approval and evidence JSON")
    release.add_argument("--recover", metavar="SHA256", help="Original RECOVERY_SHA256")
    args = parser.parse_args()
    try:
        if args.command == "check":
            return check_connections()
        if args.command == "auth-enroll":
            if args.google_client:
                enroll_google(args.google_client)
            else:
                enroll_notion()
            return 0
        if not re.fullmatch(r"RI-[0-9]{3}", args.article_id):
            raise ValueError("INVALID_ARTICLE_ID")
        return run_release(args)
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Provider responses or local paths can be private. Print only symbolic errors.
        code = str(error)
        print("BLOCKED", code if re.fullmatch(r"[A-Z0-9_]+", code) else type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
