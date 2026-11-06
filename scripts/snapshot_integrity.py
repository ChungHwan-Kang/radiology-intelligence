"""Validate integrity of a bounded two-tab input snapshot."""
import hashlib
import json
def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode()).hexdigest()
def validate(values):
    envelope=values.get("_snapshot_envelope")
    if not isinstance(envelope,dict): raise ValueError("MISSING_SNAPSHOT_ENVELOPE")
    for name,expected in (("Master_Index","A1:Z1000"),("MRI_Research_Watch","A1:S1000")):
        t=envelope.get("tabs",{}).get(name,{})
        rows=values.get(name)
        if t.get("range")!=expected or not isinstance(rows,list):
            raise ValueError("INVALID_SNAPSHOT_RANGE")
        if t.get("rows")!=len(rows) or t.get("sha256")!=digest(rows):
            raise ValueError("SNAPSHOT_HASH_OR_COUNT_MISMATCH")
    return envelope
