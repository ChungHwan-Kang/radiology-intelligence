#!/usr/bin/env python3
"""Guard a caller-provided snapshot against a separately recorded Sheets read baseline.

This detects truncated or unexpectedly changed exports. Baselines are operator-
verified observations, NOT cryptographic proof of Google account provenance.
No Google API/OAuth and no writes to original Sheets.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from snapshot_integrity import RANGES, validate

ALLOWED = ("Master_Index", "MRI_Research_Watch")


def verify_against_baseline(values, baseline):
    validate(values)
    if not isinstance(baseline, dict) or not isinstance(baseline.get("tabs"), dict):
        raise ValueError("MISSING_OBSERVED_BASELINE")
    if not isinstance(baseline.get("spreadsheet_id"), str) or not baseline["spreadsheet_id"]:
        raise ValueError("MISSING_BASELINE_SPREADSHEET_ID")
    report = {}
    for tab in ALLOWED:
        b = baseline["tabs"].get(tab)
        if not isinstance(b, dict):
            raise ValueError("MISSING_BASELINE_TAB:" + tab)
        minimum = b.get("observed_rows")
        if type(minimum) is not int or minimum < 1:
            raise ValueError("INVALID_BASELINE_COUNT:" + tab)
        observed_range = b.get("provider_range")
        if not isinstance(observed_range, str) or not observed_range.startswith(tab + "!"):
            raise ValueError("INVALID_BASELINE_RANGE:" + tab)
        if observed_range != tab + "!" + RANGES[tab]:
            raise ValueError("BASELINE_SNAPSHOT_RANGE_MISMATCH:" + tab)
        rows = values[tab]
        if len(rows) < minimum:
            raise ValueError("SNAPSHOT_BELOW_OBSERVED_BASELINE:" + tab)
        expected_headers = b.get("headers")
        if expected_headers is not None and rows[0] != expected_headers:
            raise ValueError("BASELINE_HEADER_CHANGED:" + tab)
        report[tab] = {"actual_rows": len(rows),
                       "baseline_minimum_rows": minimum,
                       "matches_headers": expected_headers is None or rows[0] == expected_headers}
    return {"state": "BASELINE_CHECK_PASS", "tabs": report,
            "google_account_authenticated_by_this_check": False,
            "complete_provider_read_proven_by_this_check": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--values-json", type=Path, required=True)
    p.add_argument("--baseline-json", type=Path, required=True)
    args = p.parse_args()
    try:
        values = json.loads(args.values_json.read_text(encoding="utf-8-sig"))
        baseline = json.loads(args.baseline_json.read_text(encoding="utf-8-sig"))
        print(json.dumps(verify_against_baseline(values, baseline), ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
