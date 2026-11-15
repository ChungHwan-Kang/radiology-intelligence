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
