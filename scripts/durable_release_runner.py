#!/usr/bin/env python3
"""Durable fail-closed private journal and exclusive-run gate.

No account tokens or approved article bodies are stored. All paths must be
outside any Git checkout; a crashed process leaves a lock and requires a
separately authorized operator to inspect the ledger before clearing it.
The journal does NOT create publication approval or grant provider scopes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from approved_publication_runtime import _release_parts
from authorized_github_dispatch import execution_authorization_value
from connected_publication_coordinator import run_approved_connected_release

GENESIS="0"*64


class JournalBlocked(ValueError):
    pass


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _inside_git(path):
    target=path.resolve()
    return any((parent/".git").exists() for parent in (target,*target.parents))


class PrivateReleaseJournal:
    """One exact article/hash = one chain-verified release ledger and lock."""
    def __init__(self, directory, article_id, approved_sha256):
        directory=Path(directory).resolve()
        if _inside_git(directory):
            raise JournalBlocked("PRIVATE_JOURNAL_INSIDE_GIT_REPOSITORY")
        if not isinstance(article_id,str) or len(article_id)!=6 or not article_id.startswith("RI-") or not article_id[3:].isdigit():
            raise JournalBlocked("INVALID_JOURNAL_ARTICLE_ID")
        if not isinstance(approved_sha256,str) or len(approved_sha256)!=64 or any(c not in "0123456789abcdef" for c in approved_sha256):
            raise JournalBlocked("INVALID_APPROVED_HASH")
        self.directory=directory
        self.article_id=article_id
        self.approved_sha256=approved_sha256
        self.path=directory/(article_id+"_"+approved_sha256[:16]+".jsonl")
        self.lock=directory/(article_id+".lock")
        self.fd=None
        self.preexisting=False

    def __enter__(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if _inside_git(self.directory):
            raise JournalBlocked("PRIVATE_JOURNAL_INSIDE_GIT_REPOSITORY")
        try:
            self.fd=os.open(self.lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(self.fd,"w") as f:
                self.fd=None
                f.write(self.approved_sha256+"\n")
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError as exc:
            raise JournalBlocked("EXCLUSIVE_RELEASE_LOCK_EXISTS_MANUAL_REVIEW") from exc
        if self.path.is_symlink():
            raise JournalBlocked("SYMLINK_RELEASE_JOURNAL_DENIED")
        self.preexisting=self.path.exists()
        if self.preexisting:
            self.entries() # verify chain and exact identity before allowing recovery
        else:
            self.append("INITIALIZED",{"article_id":self.article_id,
                                       "approved_sha256":self.approved_sha256})
        return self

    def __exit__(self, exc_type, exc, tb):
        # Normal exit releases lock. A process crash leaves the lock in place,
        # preventing automatic unsafe retry.
        self.lock.unlink(missing_ok=True)
        return False

    def entries(self):
        if not self.path.exists(): return []
        found=[]
        previous=GENESIS
        with self.path.open("r",encoding="utf-8") as fh:
            for line in fh:
                obj=json.loads(line)
                fields=obj.get("fields")
                if (obj.get("previous_sha256")!=previous
                    or not isinstance(fields,dict)
                    or fields.get("article_id")!=self.article_id
                    or fields.get("approved_sha256")!=self.approved_sha256):
                    raise JournalBlocked("JOURNAL_IDENTITY_OR_CHAIN_MISMATCH")
                digest=hashlib.sha256((previous+_canonical(fields)).encode()).hexdigest()
                if obj.get("sha256")!=digest:
                    raise JournalBlocked("JOURNAL_TAMPER_DETECTED")
                previous=digest
                found.append(obj)
        return found

    def append(self,event,report):
        if not self.lock.exists():
            raise JournalBlocked("JOURNAL_EXCLUSIVE_LOCK_REQUIRED")
        if not isinstance(report,dict) or not isinstance(event,str):
            raise JournalBlocked("INVALID_JOURNAL_EVENT")
        entries=self.entries()
        previous=entries[-1]["sha256"] if entries else GENESIS
        fields={"article_id":self.article_id,"approved_sha256":self.approved_sha256,
                "event":event,"report":report}
        digest=hashlib.sha256((previous+_canonical(fields)).encode()).hexdigest()
        entry={"previous_sha256":previous,"fields":fields,"sha256":digest}
        with self.path.open("a",encoding="utf-8") as fh:
            fh.write(_canonical(entry)+"\n")
            fh.flush()
            os.fsync(fh.fileno())
        return digest


def run_durably(prepared, github_adapter, authorization, provider_adapter,
                private_journal_dir, *, fetch=None, recover=False):
    """Never auto-retry an already-started transaction without recover=True."""
    plan,_,_,_=_release_parts(prepared)
    if authorization != execution_authorization_value(plan):
        raise JournalBlocked("ARTICLE_SPECIFIC_HASH_AUTHORIZATION_REQUIRED")
    journal=PrivateReleaseJournal(private_journal_dir,plan["article_id"],plan["approved_sha256"])
    with journal:
        history=journal.entries()
        if journal.preexisting:
            if not recover:
                return {"status":"EXPLICIT_RECOVERY_REQUIRED",
                        "journal":str(journal.path),
                        "publication_complete":False}
            if any(x["fields"]["event"]=="RESULT" and
                   x["fields"]["report"].get("status")=="ADAPTER_ATTESTED_WRITEBACK_READBACK_PASS"
                   for x in history):
                return {"status":"ALREADY_COMPLETED_MANUAL_VERIFY",
                        "journal":str(journal.path),
                        "publication_complete":False}
        # A private file lock is required before claiming a sole-writer
        # attempt. This cannot guarantee exclusion of unrelated publishers.
        provider_adapter.exclusive=True
        try:
            journal.append("ATTEMPT",{"recover":bool(recover),
                                     "external_write_enabled":getattr(provider_adapter,"write_enabled",False)})
            kw={"recover":recover}
            if fetch is not None: kw["fetch"]=fetch
            result=run_approved_connected_release(
                prepared,github_adapter,authorization,provider_adapter,**kw)
            journal.append("RESULT",result)
            return {**result,"journal":str(journal.path),
                    "durable_result_saved":True}
        finally:
            provider_adapter.exclusive=False
