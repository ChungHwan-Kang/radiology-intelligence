#!/usr/bin/env python3
"""Read-only HTTP QA for one approval-locked Radiology Intelligence release."""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

from publication_site_composer import BASE
from publication_transaction import TARGETS


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_public_text(url):
    request=Request(url,headers={"User-Agent":"RI-publication-readback/1.0"})
    with urlopen(request,timeout=20) as response:
        return response.status,response.read().decode("utf-8")


def verify_live_publication(plan,contents,fetch=fetch_public_text,base_url=BASE):
    """Verify all five public targets without mutating any external system."""
    if not isinstance(plan,dict):
        raise ValueError("APPROVED_PUBLISH_PLAN_REQUIRED")
    paths=plan.get("required_targets")
    expected=[item.format(slug=plan.get("slug")) for item in TARGETS]
    if plan.get("status")!="READY_FOR_AUTHORIZED_DISPATCH" or paths!=expected:
        raise ValueError("APPROVED_PUBLISH_PLAN_REQUIRED")
    if not isinstance(contents,dict) or set(contents)!=set(paths):
        raise ValueError("INCOMPLETE_RELEASE_PAYLOAD")
    if not isinstance(base_url,str) or not base_url.startswith("https://") or not base_url.endswith("/"):
        raise ValueError("INVALID_PUBLIC_BASE_URL")
    urls={path:base_url+path for path in paths}
    checks=[]
    for path in paths:
        url=urls[path]
        try:
            status,body=fetch(url)
        except Exception as exc:
            return {"status":"LIVE_HTTP_NETWORK_ERROR","failed_path":path,
                    "error_type":type(exc).__name__,"checks":checks,
                    "live_http_verified":False,"publication_complete":False}
        if status!=200:
            return {"status":"LIVE_HTTP_STATUS_ERROR","failed_path":path,
                    "http_status":status,"checks":checks,
                    "live_http_verified":False,"publication_complete":False}
        if not isinstance(body,str) or _digest(body)!=_digest(contents[path]):
            return {"status":"LIVE_CONTENT_VALIDATION_FAILED","failed_path":path,
                    "reason":"DEPLOYED_CONTENT_HASH_MISMATCH","checks":checks,
                    "live_http_verified":False,"publication_complete":False}
        try:
            if path in ("feed.xml","sitemap.xml"):
                ET.fromstring(body)
        except ET.ParseError:
            return {"status":"LIVE_CONTENT_VALIDATION_FAILED","failed_path":path,
                    "reason":"DEPLOYED_XML_INVALID","checks":checks,
                    "live_http_verified":False,"publication_complete":False}
        checks.append({"path":path,"url":url,"http_status":status,
                       "sha256":_digest(body)})
    return {"status":"LIVE_PUBLICATION_QA_PASS","article_id":plan["article_id"],
            "checks":checks,"live_http_verified":True,
            "github_targets_verified":True,"publication_complete":False,
            "external_system_sync":"NOT_VERIFIED"}
