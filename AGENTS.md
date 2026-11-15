# Radiology Intelligence development rules

These rules apply to the whole repository.

## Environment and workflow

- Use the existing checkout. Do not create a worktree unless the user explicitly asks for one.
- Use Python 3.12 and the Python standard library. Do not add services, OAuth flows, databases, models, or dependencies without an explicit requirement.
- Inspect `git status`, the current branch, and the current HEAD before editing. Preserve unrelated user changes.
- Before running tests that create temporary files, resolve the candidate directory and inspect it and every parent for a `.git` file or directory. Never weaken the repository's private-output guards. In the current cloud snapshot `/var/tmp` and `/tmp` are blocked; `/dev/shm` is the validated test-only fallback.
- Run the complete unit-test suite and the publication integrity gate after relevant changes.

## Publication and private data

- Never publish, merge to `main`, deploy, or write to public GitHub content without explicit article-specific user approval.
- Never commit private drafts, source notes, connected-sheet exports, patient data, approval artifacts, credentials, tokens, or readback transcripts. Keep private staging outside every Git ancestor.
- Treat Google Sheets, Drive, Notion, and GitHub publication writes as external mutations requiring explicit user authorization. Read access does not authorize writes.
- Preserve existing Published articles unless the user explicitly authorizes a correction. New publication work must remain fail-closed and bind approval to the exact reviewed content hash.
- Do not claim external synchronization, hosted CI success, Windows deployment, or live publication without direct readback evidence.

## Site integrity

- `scripts/verify_publication.py` is read-only. By default it must discover every HTML file in `posts/` carrying `article:published_time`, including newly added Published articles.
- Published articles must retain their canonical URL, publication metadata, JSON-LD BlogPosting data, indexability, editorial sections, site stylesheet/RSS links, and references from the home page, category page, RSS feed, and sitemap.
- Changes to publication tooling must include focused regression tests and keep the full suite passing.
