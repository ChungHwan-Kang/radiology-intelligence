# RI connected release — development integration runbook (2026-11-15)

Status: **DEVELOPMENT BRANCH / READ-ONLY CI VERIFIED / NOT PRODUCTION-INSTALLED**.
No new RI article ID, publication, credentials, scheduler, or branch merge was
authorized by this development task. Do not enable a GitHub Actions write token
or add an unattended publisher by interpreting these tests as production approval.

## Existing components and verified boundary

- `scripts/private_editorial_gate.py`: human-checked evidence JSON to private
  `noindex` review HTML, then explicit article-ID + hash-specific approval.
- `scripts/connected_release_preflight.py`: live native Sheets duplicate guard
  and five GitHub SHA leases, **read-only**, for an *already approved* article.
- `scripts/approved_publication_runtime.py`: conditional GitHub five-file write
  or reconciled resume; separately verifies public five-URL HTTP and hashes.
- `scripts/connected_publication_coordinator.py` (this branch): refuses an
  unapproved release or a provider conflict, runs the above GitHub and live
  gates in order, and then calls provider-specific
  `assert_ready(components)`, `read(component, article_id)` and
  `create(component, record, expected_absent=True)`.
- `tests/test_connected_publication_coordinator.py`: offline synthetic-only
  fixtures, covering no approval, no-ID P-SMART research candidate, provider
  conflict, uncertain GitHub writes, live-URL outage, post-commit transport
  failure and read-before-create recovery. A mocked adapter is **not** evidence
  of real Google/Notion write access.
- `.github/workflows/ri-publication-integrity.yml` remains read-only with
  `permissions: contents: read`; in this development branch its path filter
  includes the new integration code and tests.

## Exact release identity (not a credential)

Provider payload includes `article_id`, `doi`, `slug`,
`published_url`, `approved_private_sha256`, `published_html_sha256`,
and `component`. Each provider adapter must attest the *persisted remote*
record after readback, not merely an API success response. The review SHA
and actual human approval event must be independently persisted before the
first GitHub write. The deterministic approval phrase alone is insufficient.

## Canonical target mapping (requires real authenticated adapters)

| Coordinator component | Existing resource | Required adapter semantics |
| --- | --- | --- |
| `sheets_master` | Spreadsheet `1ZcyBs9Bpk7QURErOx5RVrucc-GcL9BlGyPmeR168YgM`, `Master_Index`, tab ID `2040869943` | Read current ID and DOI uniqueness across complete table; map approved article fields to existing A:Z schema, never create a new sheet or duplicate an ID. Only mark Published after release gates. Read back the actual row and provider revision. |
| `sheets_watch` | Same spreadsheet, `MRI_Research_Watch`, tab ID `778410221` | Locate DOI-matching candidate and verify identity; update `Existing Master ID`, research and publication status according to current schema. Do not invent a watch row or overwrite an unrelated DOI. Read back the matched row. |
| `drive_published_copy` | Existing RI Published folder `1JUcX0CFQQ_58yfR_V421ZPCWKGlUBmC7` | Store only the approved public text and metadata, not private research notes or credentials. Use ID + review hash identity, avoid duplicate copies on recovery, read back content and file ID. |
| `current_handoff` | Document `1_aM43wzoe_TjJDnKQ3Bjyp-6h1vz5bu-B6im4kyLQDQ` | Append one article-specific release receipt, verify revision and exact ID/hash marker. Do not delete historical records or mark completion while other targets are partial. |
| `notion` | Project page `3ef7d7d3-2971-8174-ba40-e64573f6931f` | Append a bounded article-specific release entry, preserve other project fields, verify the saved content and marker. Do not duplicate on retry. |

**Important:** The new coordinator's generic `record` is the expected
release-identity contract. It is **not** itself a valid Google Sheets row,
Google Docs write, or Notion update payload. The five adapters must implement
these schema translations and provider-native readbacks before production use.
A Google Sheets append does not inherently provide an atomic global
uniqueness constraint; duplicate prevention needs a sole-writer policy or
separate transactional lock verified against the provider.

## Controlled execution (ONLY after article-specific authorization)

1. Prepare private source-verified review; user confirms the exact article
   identity and approved SHA. The current P-SMART draft does **not** pass this.
2. Resolve the real credential-bearing runner *without creating new OAuth*;
   preflight all target read/write permissions and current ID/DOI rows.
3. Run approved GitHub conditional dispatch with immutable approved content,
   verifying all five file readbacks. If the write outcome is uncertain, invoke
   `recover=True` only after SHA/content reconciliation.
4. Validate public article, homepage, category, RSS, sitemap content and HTTP
   responses before any external status is set to Published.
5. Write/readback the five existing external records with the approved adapter.
   If a provider times out after committing, persist the PARTIAL report; rerun
   via read-before-create and only write untouched targets. Never remove or
   roll back a published post blindly.
6. Continue editorial queue selection only after all external targets are
   confirmed and a durable release journal has been stored privately. Queue
   selection is not a new article ID or implicit publication authorization.

## Acceptance and remaining real blockers

- PASS: branch-hosted Python tests, existing 34 published site-source
  integrity checks; no production side effects.
- PARTIAL: GitHub writes and reconciliation **logic**. Their actual
  authenticated execution needs one specifically approved live article.
- BLOCKED: the authenticated writeback adapters for actual canonical
  Sheets/Drive/Docs/Notion resources; durable provider transaction lock and
  production recovery run; connected daily task-to-runner handoff.
- BLOCKED: end-to-end automatic transition to next candidate from the
  07:10 MRI Research Watch task; no new scheduled job or OAuth authorized.

P-SMART DOI `10.1186/s13244-026-02459-2` is **private, no RI ID**.
Its source QA note remains at
`https://docs.google.com/document/d/1zgyxlxv_3jb_5tsrwvGPZKJInTrbGoiMacRw6FChzNY/edit`.
Do not place its nonpublic body in this public GitHub repository.

## 2026-11-15 follow-on: native provider adapters and private durable journal

Development implementation:
- `scripts/native_provider_writeback.py`: real HTTP endpoint mappings for
  native Google Sheets, Drive upload/media, Docs and Notion block API. Accepts
  **existing runtime-supplied** bearer tokens via `NativeHTTP`; it does not
  perform OAuth, download credentials, install a runner or enable writes by
  default. It verifies the canonical spreadsheet tab IDs and headers, exact
  unique article ID/DOI, unique matching Watch DOI row, and exact approved
  article+HTML identity. It stores the release receipt in native Google Sheets
  **cell notes**, Google Drive file description/appProperties, a bounded Google
  Docs appended paragraph and a Notion paragraph. Existing approved articles
  and tab structures are not changed by this development code.
- `scripts/durable_release_runner.py`: private-only, hash-chained JSONL ledger,
  exclusive local article-ID lock and explicit `recover=True` after interrupted
  attempts. No secrets, private article body or draft content in journal. The
  local lock is not a cross-machine/ChatGPT-task transaction lock and cannot
  exclude unrelated writers to the canonical Google Sheet.
- `tests/test_native_provider_writeback.py` and
  `tests/test_durable_release_runner.py`: synthetic-only native endpoint,
  no-ID/no-approval, duplicate DOI, permissions, content/hash mismatch,
  idempotence, timeout and explicit recovery checks. No real external writes.

**Critical integration contract**: the actual `NativeProviderAdapter` must be
constructed in a trustworthy *already-authorized* runner from approved
article.json metadata and its precisely hash-locked public HTML, not scraped
from a live article. It needs the existing Google/Notion access tokens with
write scopes at runtime. A ChatGPT connector session is not equivalent to a
token automatically available to Python or GitHub Actions. The execution
runner must bind the receipt to the actual article approval event.

**Hard safety gates**: `write_enabled=False` by default; no sole-writer lease
means blocked; `run_durably` only proceeds with exact ID/hash approval token,
creates a private journal outside Git and must be invoked by the approved
operator. A stale article lock must be manually investigated. A Github post
partial commit is reconciled by existing SHA lease logic; a Google/Notion
partial commit is re-read before any new create. All remote modifications
are intentionally DISALLOWED while PR #3 remains a draft.

**Read-only connected account observations**:
- Canonical Google Sheets: `Master_Index` 2040869943 / A:Z, and
  `MRI_Research_Watch` 778410221 / A:S, verified with the connected
  account (this is NOT runtime OAuth proof).
- Google Drive `01_Blog` folder ID `1JUcX0CFQQ_58yfR_V421ZPCWKGlUBmC7`
  confirmed as a folder; handoff Doc and P-SMART private Doc verified as
  their own original files in distinct existing folders. No moves/copies.
- Existing MRI Research Watch automation ID
  `6a97a28a55988191875acaea93733ad7` confirmed enabled with
  Asia/Seoul 07:10 daily recurrence. Its saved prompt already includes
  approval handoff and continuous next-candidate selection. No duplicated
  or modified schedule. However direct handoff from the task sandbox to this
  Python runtime and real credential-bearing provider adapter is **NOT VERIFIED**.

**Operational acceptance** remains PARTIAL until: (1) existing credential
transfer pathway and scoped write capability are inspected/approved,
(2) the sole-writer cross-client constraint and durable journal lifecycle
are confirmed in the actual runner, (3) a private end-to-end attempt is
observed with provider readbacks, (4) main-branch merge is approved, and
(5) a separate explicitly approved real article is safely published and
verified. No current P-SMART RI ID, approved HTML hash or publication consent.
Hosted tests are a code regression signal, not proof of provider acceptance.

Latest run: https://github.com/ChungHwan-Kang/radiology-intelligence/actions/runs/43705627943
(214 tests OK, existing 34 Published source integrity checks PASS, on
development branch; re-check after subsequent commits).

## 2026-11-15 release-gate correction and real connected read-only preflight

During production-readiness review, one unsafe state label was identified and
corrected on the development branch. The provider adapter's original
`assert_ready` returned `ALL_TARGETS_READ_WRITE_READY` after **GET only**,
although `actual_write_scopes_verified=False`. The coordinator previously
accepted the status without checking the false flag, so an explicitly approved
article could advance to GitHub while external provider write permission was
unknown. The corrected adapter reports
`READ_ONLY_PREFLIGHT_PASS_WRITE_SCOPE_UNVERIFIED`; the coordinator requires
explicitly proven `actual_write_scopes_verified=True` and
`caller_single_writer_lease_attested=True` before attempting ANY GitHub write.
This is a fail-closed safety fix, **not** proof that write scopes exist. Synthetic
positive tests use explicit simulated attestations, and cannot promote the
real adapter to operational write-readiness.

Provider-native connected Sheets READ-ONLY results from the active ChatGPT
connection on 2026-11-15:
- Canonical spreadsheet ID and tab IDs confirmed, `Master_Index` A:Z,
  `MRI_Research_Watch` A:S.
- P-SMART DOI `10.1186/s13244-026-02459-2`: exactly one matching Watch
  candidate at row 59, candidate YES / priority HIGH, no Master link, status
  Indexed; zero matching Master_Index DOI records across A1:Z1026.
- These results establish DOI presence/absence at the moment of the connected
  read, NOT an authorized, transactionally leased provider write or a new RI ID.

Existing KCH AI Office execution environment reference: Notion checkpoint
`KCH AI Office — Approval Deployment Readiness NO-GO 2026-11-11`,
https://app.notion.com/p/4157d7d329718197a187cc7829d8e635 . It records
read-only Codex audit evidence of missing draft-runtime dependencies,
`work_reference` issuance, `signed_actions` forwarding, backup baseline,
fixed host disconnected and no live provider E2E. This is a **KCH AI Office**
readiness result, not a measurement of RI's GitHub service itself. Until an
independent current local inspection disproves it, do NOT assume that local
KCH execution/credential transfer is ready. No shared runner integration or
local Windows file access has been demonstrated in this ChatGPT session.

The existing MRI Research Watch task remains enabled at 07:10 Asia/Seoul and
its prompt already defines approval gating and next-candidate continuation.
No task changes are necessary. Its invocation of the private Python dispatcher
or KCH AI Office is unverified; a ChatGPT task's connector authorization cannot
be exported as OAuth bearer tokens to the Python process by assumption.

**Acceptance boundary:** code-only CI PASS; native provider GET metadata PASS via
ChatGPT connectors; provider write-scope attestation BLOCKED; KCH host deployment
NO-GO per existing checkpoint; actual production transaction, writeback and
recovery NOT TESTED. Keep Draft PR #3 unmerged pending distinct user approval.
