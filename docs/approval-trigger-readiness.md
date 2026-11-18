# Approval-trigger readiness

## Verified boundary on 2026-11-18

Main PR #5 supplies the existing publisher, live QA and four/five-target
provider transactions. This branch depends on Draft PR #7 for the Windows
Credential Manager implementation. PR #7 is still unmerged and real credential
enrollment is pending local policy and Google Audience checks.

The Windows inventory found no RI-named scheduled task. The current login is
interactive, outside a domain, with DisableDomainCreds=0. These observations
establish neither institutional permission nor continuous machine availability.
No RI approval receiver, service or background worker has been installed.
Current check returns GitHub read PASS and both provider credentials unenrolled.

The existing 07:20 news and 07:40 Watch jobs write the canonical Sheet. Latest
Current_Handoff and Session Checkpoint report their 2026-11-18 rows verified.
Timing separation and a local article lock cannot exclude these writers.

## Approval receiver contract

The pure approval_event_contract validator binds the exact ID, canonical DOI,
review SHA, source contract and ordered four/five components. It also checks
explicit publication action, actor/reference supplied by a trusted receiver,
time window and a caller-provided consumed-event set. It performs no I/O.

Before any production receiver calls it, the user must choose an existing
authenticated private approval source. The receiver must independently verify
the reviewer and immutable source revision. Caller-supplied identities and
matching hashes alone cannot prove a human approval. Public issues, chat
phrases, candidate selection and PR merges are insufficient provenance.

The receiver must atomically reserve the event and release identity before
dispatch, serialize all articles, preserve the exact accepted event and original
prepared payload privately, and reject replay or identity changes. This branch
does not implement that receiver or durable consumed-event store.

## Proposed Windows operation

After separate operational approval, one foreground worker under the existing
Windows user can read an existing authenticated private queue. This avoids a new
server and reservation, but runs only while that worker and PC are available.
An immediate push from a ChatGPT scheduled task to arbitrary Windows Python
has not been demonstrated. Codex's current shell can invoke Python, which proves
interactive execution only.

The queue must retain pending approvals while the PC is offline. On reconnect,
the worker checks expiry and exact identity again. An expired unstarted event
requires renewed consent. For an already-started release, policy must explicitly
permit identity-preserving recovery under the original approval.

The existing windows_ri_release.run_release and run_durably remain the only
publication path. Do not rebuild the original five-file payload after a partial
write. Retain its snapshot digest, reconcile remote objects and use the existing
explicit recovery flag. A crash leaves the local lock and requires investigation.
Network timeout can follow a committed write, so retry uses provider reads.
Completed-run replay returns ALREADY_COMPLETED_MANUAL_VERIFY and must not become
a second publication.

An external writer lease must cover both discovery jobs and other clients.
Every writer must respect that lease or be demonstrably excluded throughout the
transaction. Its owner, source, expiry, renewal and loss behavior need evidence.
No such cross-client protocol is currently installed. Loss blocks new writes;
partial publication is reconciled when exclusivity is restored.

## Candidate continuation

Only after persisted provider readbacks may candidate evaluation run. Reuse
editorial_queue and the existing 07:40 two-source editorial reconciliation.
The local queue helper currently focuses on research Watch inputs. It is not
equivalent to the live combined news/research editorial job. No authenticated
completion-to-07:40 invocation or acknowledgment exists yet.

Candidate selection never assigns a new RI ID or approves the next publication.
A next-candidate failure must retain the completed release and retry only that
continuation. It must not replay the publisher.

## Validation and remaining gates

Synthetic contract tests cover both source component sets, tampered identity,
wrong action, missing provenance, replay, expiry and changed source stage.
Existing synthetic publisher/recovery tests remain reusable. Offline queue
delivery, cross-client lease and real provider acceptance are unverified.

Required operational decisions are the private approval source, authorized
foreground worker lifecycle, cross-writer lease participation and exact
recovery delegation. New server, task, scope or merged code requires separate
approval. No actual article approval or event receipt was created.
