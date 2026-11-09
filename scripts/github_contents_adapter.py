#!/usr/bin/env python3
"""GitHub Contents API adapter for RI approval-locked publication.

Real HTTPS transport is available, but writing is DISABLED by default.
Never use this class to authorize an article: call the approval/hash gate
and check the exact RI article-specific consent before enabling writes.
A GitHub contents PUT is conditional per-file, NOT an atomic five-file commit.
An ambiguous response must be reconciled remotely; never blindly retry.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubContentsError(RuntimeError):
    pass


class GitHubContentsAdapter:
    def __init__(self, repo, branch, transport, *, live_write_enabled=False):
        if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("INVALID_REPOSITORY")
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or ".." in branch:
            raise ValueError("INVALID_BRANCH")
        if not callable(transport):
            raise ValueError("TRANSPORT_REQUIRED")
        self.repo=repo
        self.branch=branch
        self.transport=transport
        self.live_write_enabled=live_write_enabled is True

    def _url(self,path):
        if not isinstance(path,str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*",path):
            raise ValueError("INVALID_GITHUB_PATH")
        if any(part in (".","..") for part in path.split("/")):
            raise ValueError("INVALID_GITHUB_PATH")
        return ("https://api.github.com/repos/"+self.repo+"/contents/"+
                "/".join(quote(x,safe="") for x in path.split("/")))

    def _load(self,path,*,allow_missing=False):
        url=self._url(path)+"?ref="+quote(self.branch,safe="")
        status,obj=self.transport("GET",url,None)
        if status==404 and allow_missing:
            return None
        if status!=200 or not isinstance(obj,dict):
            raise GitHubContentsError("GITHUB_READ_FAILED:"+str(status))
        if obj.get("type")!="file":
            raise GitHubContentsError("GITHUB_PATH_NOT_FILE")
        sha=obj.get("sha")
        if not isinstance(sha,str) or not re.fullmatch("[0-9a-f]{40}",sha):
            raise GitHubContentsError("INVALID_GITHUB_BLOB_SHA")
        return obj

    def read(self,path):
        obj=self._load(path,allow_missing=True)
        return obj["sha"] if obj else None

    def read_content(self,path):
        obj=self._load(path)
        if obj.get("encoding")!="base64" or not isinstance(obj.get("content"),str):
            raise GitHubContentsError("GITHUB_CONTENT_NOT_BASE64")
        try:
            raw=base64.b64decode(obj["content"],validate=False)
            return raw.decode("utf-8")
        except (ValueError,UnicodeError) as exc:
            raise GitHubContentsError("INVALID_GITHUB_TEXT_CONTENT") from exc

    def write(self,path,content,expected_sha):
        if not self.live_write_enabled:
            raise GitHubContentsError("GITHUB_WRITES_DISABLED")
        if not isinstance(content,str):
            raise ValueError("CONTENT_MUST_BE_TEXT")
        if expected_sha is not None and (not isinstance(expected_sha,str) or
                                          not re.fullmatch("[0-9a-f]{40}",expected_sha)):
            raise ValueError("INVALID_EXPECTED_SHA")
        # One more read limits TOCTOU. The PUT's sha is the actual GitHub
        # compare-and-swap precondition for existing files.
        if self.read(path)!=expected_sha:
            raise GitHubContentsError("REMOTE_CHANGED_BEFORE_WRITE")
        obj={"message":"RI approved publication update: "+path,
             "branch":self.branch,
             "content":base64.b64encode(content.encode("utf-8")).decode("ascii")}
        if expected_sha is not None:
            obj["sha"]=expected_sha
        status,reply=self.transport("PUT",self._url(path),obj)
        if status not in (200,201) or not isinstance(reply,dict):
            raise GitHubContentsError("GITHUB_CONDITIONAL_WRITE_FAILED:"+str(status))
        blob=(reply.get("content") or {}).get("sha")
        if not isinstance(blob,str) or not re.fullmatch("[0-9a-f]{40}",blob):
            raise GitHubContentsError("GITHUB_WRITE_RECEIPT_INVALID")
        return blob


def build_authenticated_transport(token):
    """Construct narrowly scoped transport, without persisting any token."""
    if not isinstance(token,str) or not token.strip():
        raise ValueError("GITHUB_TOKEN_REQUIRED")
    def request(method,url,payload):
        if not url.startswith("https://api.github.com/repos/"):
            raise ValueError("UNAPPROVED_GITHUB_API_URL")
        body=None if payload is None else json.dumps(payload).encode("utf-8")
        req=Request(url,data=body,method=method,headers={
            "Accept":"application/vnd.github+json",
            "Authorization":"Bearer "+token,
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"RI-approved-dispatch"})
        try:
            with urlopen(req,timeout=20) as response:
                return response.status,json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Never echo response bodies or authorization header.
            return exc.code,{}
    return request
