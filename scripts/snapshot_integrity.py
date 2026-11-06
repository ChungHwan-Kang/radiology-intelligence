"""Fail-closed validation of a two-tab caller-supplied Sheets snapshot.

This confirms transport integrity against a supplied envelope. It is NOT
authentication of the Google account, the producer, or completeness of its read.
"""
import hashlib
import json

RANGES = {"Master_Index": "A1:Z1026", "MRI_Research_Watch": "A1:S1000"}


def digest(rows):
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate(values):
    if not isinstance(values, dict):
        raise ValueError("INVALID_SNAPSHOT")
    envelope = values.get("_snapshot_envelope")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("tabs"), dict):
        raise ValueError("MISSING_SNAPSHOT_ENVELOPE")
    if values.get("_snapshot_complete") is not True:
        raise ValueError("INCOMPLETE_SNAPSHOT")
    for name, expected_range in RANGES.items():
        entry = envelope["tabs"].get(name)
        rows = values.get(name)
        if not isinstance(entry, dict) or not isinstance(rows, list) or not rows:
            raise ValueError("MISSING_SNAPSHOT_TAB:" + name)
        if entry.get("range") != expected_range:
            raise ValueError("INVALID_SNAPSHOT_RANGE:" + name)
        if not all(isinstance(r, list) and all(
                isinstance(v, (str, int, float, bool, type(None))) for v in r)
                for r in rows):
            raise ValueError("INVALID_SNAPSHOT_ROWS:" + name)
        if not rows[0] or not all(isinstance(v, str) for v in rows[0]):
            raise ValueError("INVALID_SNAPSHOT_HEADER:" + name)
        if type(entry.get("rows")) is not int or entry["rows"] != len(rows):
            raise ValueError("SNAPSHOT_ROW_COUNT_MISMATCH:" + name)
        expected_hash = entry.get("sha256")
        if (not isinstance(expected_hash, str) or len(expected_hash) != 64 or
                expected_hash != digest(rows)):
            raise ValueError("SNAPSHOT_SHA256_MISMATCH:" + name)
    return envelope
