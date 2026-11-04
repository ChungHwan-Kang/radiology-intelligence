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
