"""Offline approval-envelope checks. Transport authentication belongs to the receiver."""

from datetime import datetime
import hashlib
import json
import re

from connected_publication_coordinator import NEWS_RECORD_COMPONENTS, RECORD_COMPONENTS
from native_sheets_duplicate_guard import norm_doi


class ApprovalEventBlocked(ValueError):
    pass


def approval_binding(article_id, doi, review_sha256, source_contract, components):
    """Hash the exact identity shown to the user before approval."""
    if not isinstance(article_id, str) or not re.fullmatch(r"RI-[0-9]{3}", article_id):
        raise ApprovalEventBlocked("ARTICLE_ID_REQUIRED")
    if not isinstance(review_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", review_sha256):
        raise ApprovalEventBlocked("REVIEW_SHA_REQUIRED")
    if not isinstance(doi, str) or doi != norm_doi(doi) or not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        raise ApprovalEventBlocked("CANONICAL_DOI_REQUIRED")
    if not isinstance(source_contract, dict):
        raise ApprovalEventBlocked("SOURCE_CONTRACT_REQUIRED")
    kind = source_contract.get("source_kind")
    if kind == "master_news":
        if (set(source_contract) != {"source_kind", "source_master_id", "source_master_content_stage"}
                or not isinstance(source_contract.get("source_master_id"), str)
                or not re.fullmatch(r"RB-[0-9]{3}", source_contract["source_master_id"])
                or source_contract.get("source_master_content_stage") != "Private"):
            raise ApprovalEventBlocked("NEWS_SOURCE_CONTRACT_INVALID")
        expected = NEWS_RECORD_COMPONENTS
    elif kind == "research_watch":
        if set(source_contract) != {"source_kind", "source_watch_doi"} or source_contract["source_watch_doi"] != doi:
            raise ApprovalEventBlocked("WATCH_SOURCE_CONTRACT_INVALID")
        expected = RECORD_COMPONENTS
    else:
        raise ApprovalEventBlocked("SOURCE_KIND_REQUIRED")
    if not isinstance(components, list) or components != list(expected):
        raise ApprovalEventBlocked("SOURCE_COMPONENT_ORDER_MISMATCH")
    identity = {
        "article_id": article_id, "doi": doi, "review_sha256": review_sha256,
        "source_contract": source_contract, "components": components,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_event(event, expected, *, trusted_actor, trusted_approval_ref, now, consumed_event_ids):
    """Validate a receiver-authenticated event without dispatching or granting writes.

    trusted_actor/ref must come from a verified provider event or protected local
    approval surface. These arguments are a boundary contract, not authentication.
    Replay storage and its atomic claim belong to the future receiver.
    """
    fields = {
        "version", "event_id", "action", "article_id", "doi", "review_sha256",
        "source_contract", "components", "binding_sha256", "reviewer", "approval_ref",
        "approved_at", "expires_at",
    }
    if not isinstance(event, dict) or set(event) != fields or event["version"] != 1:
        raise ApprovalEventBlocked("APPROVAL_EVENT_SCHEMA_INVALID")
    if event["action"] != "APPROVE_PUBLICATION":
        raise ApprovalEventBlocked("EXPLICIT_PUBLICATION_ACTION_REQUIRED")
    if not isinstance(event["event_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", event["event_id"]):
        raise ApprovalEventBlocked("EVENT_ID_INVALID")
    if event["event_id"] in consumed_event_ids:
        raise ApprovalEventBlocked("EVENT_ALREADY_CONSUMED")
    if (not isinstance(trusted_actor, str) or not trusted_actor.strip()
            or not isinstance(trusted_approval_ref, str) or not trusted_approval_ref.strip()
            or event["reviewer"] != trusted_actor or event["approval_ref"] != trusted_approval_ref):
        raise ApprovalEventBlocked("AUTHENTICATED_APPROVAL_PROVENANCE_REQUIRED")
    keys = ("article_id", "doi", "review_sha256", "source_contract", "components")
    binding = approval_binding(**{key: event[key] for key in keys})
    expected_binding = approval_binding(**expected)
    if binding != event["binding_sha256"] or binding != expected_binding:
        raise ApprovalEventBlocked("APPROVAL_IDENTITY_CHANGED")
    try:
        start = datetime.fromisoformat(event["approved_at"])
        expiry = datetime.fromisoformat(event["expires_at"])
        if (not start.tzinfo or not expiry.tzinfo or not now.tzinfo
                or start.utcoffset() is None or expiry.utcoffset() is None
                or now.utcoffset() is None or not start <= now < expiry):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise ApprovalEventBlocked("APPROVAL_EXPIRED_OR_TIME_INVALID") from None
    return {"status": "ENVELOPE_VALID_TRANSPORT_ATTESTED_BY_CALLER",
            "binding_sha256": binding, "event_id": event["event_id"],
            "publication_authorized_by_validator": False}
