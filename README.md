# Radiology Intelligence

영상의학의 연구, AI, 환자안전, 운영, 교육, 정책 변화를 근거 중심으로 해설하는 공개 사이트입니다.

**Live site:** https://chunghwan-kang.github.io/radiology-intelligence/

## Design baseline
- v0.4 approved on 2026-09-30
- Korean-first content
- Toss Tech-inspired light neutral palette and blue accent
- Minimal decoration, high Korean readability
- Published content only; no placeholder articles
- Mobile navigation and reading QA refined on 2026-10-04

## Site structure
- `index.html` — 홈 / 최신 해설
- `categories.html` — 7개 주제별 보기
- `about.html` — 소개·편집 원칙
- `styles.css` — 공통 스타일
- `posts/ri-001-mri-thermal-injury.html` — MRI 열손상의 공통 원인과 예방
- `posts/rb-059-mri-repeat.html` — MRI 반복 촬영과 운영 부담
- `posts/rb-037-inpatient-mri-safety.html` — 입원환자 MRI 위험도 기반 안전관리
- `posts/rb-064-rsna-ai-certificate.html` — 영상의학 AI 교육과 임상 활용 역량
- `sitemap.xml` — 검색엔진 사이트맵
- `robots.txt` — 크롤링 정책
- `feed.xml` — RSS 2.0 피드
- `404.html` — 오류 페이지
- `.nojekyll` — Jekyll 처리 비활성화

## Categories
1. MRI 검사와 기술
2. MRI 안전
3. 품질과 운영
4. AI와 디지털
5. 교육과 역량
6. 연구와 근거
7. 정책과 전문직

한 글은 여러 주제에 동시에 포함될 수 있습니다.

## Discovery & sharing baseline
- Canonical URL
- Open Graph title/description/url/type
- Twitter summary metadata
- Schema.org JSON-LD
- sitemap.xml
- robots.txt
- RSS feed auto-discovery
- Applied on 2026-10-04

Category taxonomy finalized on 2026-10-05.
- RI SVG favicon/app mark added
- 1200×630 branded OG source artwork added as `assets/og-source.svg`
- Raster PNG/JPEG export should be used for `og:image` before social-preview rollout because major social scrapers do not consistently support SVG OG images.

## Editorial workflow
Master Index → Deep Dive → Content Review → Public-ready → Published → Society-shared

Public-ready 검토가 끝난 콘텐츠만 공개 사이트에 게시합니다.

RI-001 published on 2026-10-05. RI-002 (3T dielectric artifact) remains Public-ready.
