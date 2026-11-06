# Radiology Intelligence — private editorial gate v2.0

Status: **code installed in existing GitHub repo; local KCH AI Office integration NOT installed or verified**.

This is a **local, offline, fail-closed preview generator** for a source-checked article JSON.
It has no DOI retrieval, Google account, GitHub API, Notion API, publication permission,
user credentials or scheduler. Do not treat it as an autonomous fact checker.

## Integrate without adding another timer or OAuth

Keep the existing ChatGPT MRI Research Watch at 07:10 KST.
If the existing `D:\\KCH-AI-Office` local workflow has a manual/approved execution point,
use its **existing** job to export one evidence-checked JSON into an external private
staging directory. Run the script there under its existing read-only execution identity.

**Never store source drafts, review HTML, patient data, or Google tokens in this PUBLIC repo.**
Use an access-controlled path outside the git checkout, such as
`D:\\KCH-AI-Office-private\\radiology-intelligence` ONLY if authorized and provisioned.
The code rejects a staging path under any `.git` ancestor.

Preparation command:

```powershell
python scripts/private_editorial_gate.py prepare --input "C:\\PRIVATE\\RI-031.json" --private-dir "C:\\PRIVATE\\RI-staging"
```

Expected output: `RI-031/status.json` and (only when ready) `RI-031/review.html`.
`status.json` is the machine-readable outcome.

## Input contract (synthetic TEST data, not a real source)

```json
{
  "id": "RI-999",
  "slug": "ri-999-fixture.html",
  "title": "가상 검사",
  "subtitle": "실제 출판용 원고 아님",
  "categories": ["MRI 검사와 기술", "연구와 근거"],
  "summary": "가상의 QA 시험용 문장",
  "sections": [
    {"heading": "가상 방법", "text": "실제 환자나 임상근거가 아닙니다."},
    {"heading": "가상 한계", "text": "실제 발행을 금지합니다."}
  ],
  "takeaway": "이 예시는 안전장치 시험 전용입니다.",
  "references": ["TEST doi:10.1000/fictional-test"],
  "claims": [
    {"claim": "test only", "primary_source_location": "synthetic fixture", "verified": true}
  ],
  "source_verification": {
    "original_methods_results": true,
    "quantitative_claims": true,
    "supplement": "NOT_APPLICABLE",
    "source_url": "https://example.org/synthetic-fixture"
  }
}
```

The declarations above must come from **actual human/agent source checks** and
reference the original paper's exact Methods/Results, not just an abstract.
The script validates the declaration's **presence, not its scientific truth**.

### States

- `SOURCE_BLOCKED`: Methods/Results, statistics or supplement status not verified.
- `QA_BLOCKED`: Missing metadata, sources, claims, structure or invalid ID.
- `APPROVAL_PENDING`: private review HTML ready with `noindex,nofollow` and QA metadata.
- `APPROVED_FOR_PUBLISH`: explicit article-specific approval token + matching SHA
  recorded. **Still no public writes.** An approved, separately implemented
  publisher must recheck authorization, original records and current GitHub SHAs.

For an explicit approval already provided **for that precise reviewed hash**:

```powershell
python scripts/private_editorial_gate.py approve --article-id RI-031 --private-dir "C:\\PRIVATE\\RI-staging" --sha256 "<the value from RI-031/status.json>" --explicit APPROVE_FOR_PUBLICATION
```

This CLI token is a deterministic technical safeguard and **not an authentication system**.
Do NOT use it to auto-approve articles or substitute a real approval event. Never
pass approval credentials via unattended scheduled jobs.

## Acceptance / regression test

```powershell
python -m unittest discover -s tests -p "test_private_editorial_gate.py" -v
```

Tests cover six scenarios: blocked original source, nonpublic preview, missing explicit
approval, modified preview hash, recorded-only approval, private storage inside git.
The existing `ri-publication-integrity.yml` CI also runs these tests.

**Not yet demonstrated:** actual GitHub Actions run status, connected local KCH Office
collector execution, automatic citation checking, automatically sending an HTML preview
to user, approved post-to-GitHub transaction, and multi-system rollback. These remain
explicitly PENDING until verified with run logs and readbacks.

## Safeguards

- No new scheduled task or OAuth.
- No writes to live posts/index/categories/RSS/sitemap from this module.
- No automatic approval; no preapproval public publishing.
- Current RI-031 remains `SOURCE_REVIEW_PARTIAL / QA_PENDING` until original source
  Methods/Results/figures/supplements are checked.
- Existing published RI-025—RI-030 are not rewritten without correction authorization.


## 2026-11-06: two-tab candidate queue, fail-closed fallback

Added `scripts/editorial_queue.py` and `tests/test_editorial_queue.py` to this existing repository. The queue takes **read-only CSV snapshots** of the existing `Master_Index` (with actual `Content Stage` column) and `MRI_Research_Watch` tabs. It DOES NOT create or modify any spreadsheet tab or article ID. `source_states.json` must come from an explicitly reviewed primary paper; these are verification declarations, **not autonomous literature fact-checking**.

Example command (all paths private; no scheduled task created):

```powershell
python scripts/editorial_queue.py --master "C:\\PRIVATE\\Master_Index.csv" --watch "C:\\PRIVATE\\MRI_Research_Watch.csv" --active "C:\\PRIVATE\\active.json" --sources "C:\\PRIVATE\\source_states.json" --output "C:\\PRIVATE\\queue_decision.json"
```

Example active file: `{"article_id":"RI-031","state":"SOURCE_BLOCKED","doi":"10.1002/jmri.70589"}`.
Example verified availability: `{"10.1186/s13244-026-02459-2":"SOURCE_VERIFIED"}` only if original paper actually checked.

With a blocked RI-031, the returned decision `RESEARCH_ALTERNATE` permits **private primary-source research** into P-SMART, but `no_new_ri_id=true` and `public_write_permitted=false`. Under any non-blocked active state the outcome is `RESUME_ACTIVE`. Source blocks or lack of candidates never authorize publication.

Unit-test command: `python -m unittest discover -s tests -p "test_*.py" -v`. This now covers eight gate tests plus eight queue tests. Local isolated Python reproduction of this logic passed 16/16 on 2026-11-06, but the GitHub-hosted CI execution logs were not accessible; remote CI should remain UNVERIFIED until its actual run is checked.

**Integration boundary:** a ChatGPT task with Google Drive/Sheets access can read and decide, but the Python CLI cannot access private connected Sheets or Google Docs by itself. A separate authorized export/runner step must produce the private CSV and evidence JSON for this CLI. Neither the task nor this public repository may falsely claim local Windows execution. Keep completed public RI-025–RI-030 unchanged and article-specific approval mandatory.


## 2026-11-06 bounded end-to-end integration and reproducible evidence

Files added/updated in this EXISTING public code repository (no preapproval article source):
- `scripts/sheets_bridge.py`: accepts existing connected Sheet value arrays, checks actual `Master_Index` / `MRI_Research_Watch` headers, outputs local private CSV + hash manifest. **It does not authenticate to Google**.
- `scripts/editorial_pipeline.py`: offline orchestration of CSV bridge -> candidate queue -> active RI-031 source-blocked fallback -> no-ID private research preview / source-verified article QA -> machine-readable run manifest. No publisher.
- `scripts/research_preview.py`: noindex research-only HTML, explicitly no RI ID / no approval. P-SMART private fallback research-only.
- `scripts/publication_transaction.py`: approved HTML and DOI/ID duplication preflight plus required multi-system write/readback checklist, **NOT an implemented write dispatcher**.
- `tests/test_*.py`: source/HTML approval gate, source JSON hash lock, queue, Sheets bridge, research-only preview and publishing preflight regression suites. Local integrated mirror ran 35 tests with PASS; hosted GitHub Actions result is still UNKNOWN.

Latest local bounded data trial used previously read connected Sheets published records RI-025–RI-030 and recent Watch rows including RI-031 (active source-blocked) and P-SMART. The sampled input is not a complete automatically exported 229-row Master / 61-row Watch snapshot. Result: `RESEARCH_ALTERNATE` P-SMART, no RI ID, private `noindex` preview and stage log, no approval or public writes. Source checks for P-SMART relied on the existing Drive research note, not a new full-text publisher verification in that particular local run.

**Do not mark finished:** authorized Google connector -> full private input export, actual installed KCH AI Office Windows invocation, scheduled autonomous final draft and delivery, original-source and terminology independent QA, GitHub Actions hosted job PASS readback, and **postapproval transaction dispatcher with GitHub + two Sheets tabs + Drive + RSS + sitemap + live URL readbacks**. No claim of Windows deployment or cloud-native automation is authorized by this code-only check.

The current proof package and runnable tests exist as local/private session artifacts. Do not upload it to the public repo when it contains connected-sheet snippets or research drafts. Keep public GitHub code-only, RI-031 SOURCE_BLOCKED and RI-025–RI-030 Published.
