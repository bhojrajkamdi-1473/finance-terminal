# Bhojraj Kamdi — Finance Portfolio

Personal finance portfolio: PGDM-Finance '27, audit & accounts internship,
equity research, nine documented projects, NISM certifications.

- **Stack:** pure static HTML + CSS + vanilla JS. No framework, no build
  step beyond file copying, no database, no backend, no API keys.
- **Live site:** Cloudflare Pages (free plan), auto-deployed from GitHub.
- **Documents:** project reports, resume and certificates live on verified
  external Google Drive / LinkedIn / Coursera URLs (see
  `data/link-inventory.json`, git-ignored). Nothing is fabricated.

## Project structure

```text
index.html            Homepage (identity, highlights, tools, experience,
                      projects, approach, library, credentials, about,
                      industry, evidence index, contact)
experience.html       Full experience record
projects.html         Full project archive (9 projects)
certifications.html   Credentials by type
about.html            Background + education
contact.html          Contact details + direction
resume.html           Resume page
assets/               styles.css, main.js, favicon, profile + industry photos
build_static.py       Assembles dist/ for Cloudflare Pages (stdlib only)
```

## Local development

```text
python server.py --port 8000
```

Open http://localhost:8000/index.html (the portfolio pages + `/terminal/`
finance app served by the local Python server).

To preview the exact production output:

```text
python build_static.py
python -m http.server 8000 --directory dist
```

Then open http://localhost:8000/index.html.

## Portfolio links

All public report / resume / certificate / contact destinations are audited
in `data/link-inventory.json` (local-only, git-ignored). Source of truth
for Drive document IDs is `data/portfolio-data.json` (local-only,
git-ignored). Page CTAs use the verified URLs directly as static anchors.

## Deployment (free)

- **Source:** GitHub (`master` branch)
- **Hosting:** Cloudflare Pages, free plan — no paid Workers, storage,
  databases, or analytics.
- **Build command:** `python build_static.py`
- **Output directory:** `dist`
- **Root directory:** repository root

Workflow for every future update:

```text
1. Edit website
2. python build_static.py + smoke test dist locally
3. git add <files>
4. git commit -m "..."
5. git push
6. Cloudflare Pages detects the push, rebuilds, and deploys automatically
7. Open the production URL and smoke test live
```

No FTP, no manual uploads, no paid deployment service. To use a custom
domain later, attach it in the Cloudflare Pages dashboard — no code or
architecture change is needed.
