"""Static-site builder for Cloudflare Pages (free tier) — Python stdlib only.

Assembles dist/ from the portfolio source files so the Pages deployment
contains ONLY the public static website. Server code, terminal app,
provider keys config, audit notes, personal documents and caches are
never copied.

Cloudflare Pages settings (free plan):
  Build command   : python build_static.py
  Output directory: dist
  Root directory  : (repository root)

Local preview of the exact production output:
  python build_static.py
  python -m http.server 8000 --directory dist
"""

from __future__ import annotations

import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

# The complete public portfolio. Nothing else is published.
PAGES = [
    "index.html",
    "experience.html",
    "projects.html",
    "certifications.html",
    "about.html",
    "contact.html",
    "resume.html",
]

ROBOTS_TXT = "User-agent: *\nAllow: /\n"


def build() -> None:
    if os.path.isdir(DIST):
        shutil.rmtree(DIST, ignore_errors=True)
    os.makedirs(DIST)

    for page in PAGES:
        src = os.path.join(ROOT, page)
        if not os.path.isfile(src):
            raise SystemExit(f"missing required page: {page}")
        shutil.copy2(src, os.path.join(DIST, page))

    assets_src = os.path.join(ROOT, "assets")
    assets_dst = os.path.join(DIST, "assets")
    shutil.copytree(assets_src, assets_dst)

    with open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(ROBOTS_TXT)

    base = os.environ.get("CF_PAGES_URL", "").strip()
    if base:
        urls = "\n".join(
            f'  <url><loc>https://{base}/{p if p != "index.html" else ""}</loc></url>'
            for p in PAGES
        )
        sitemap = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n</urlset>\n"
        )
        with open(os.path.join(DIST, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write(sitemap)

    with open(os.path.join(DIST, "404.html"), "w", encoding="utf-8") as f:
        f.write(
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "<title>Not found — Bhojraj Kamdi</title>\n"
            '<link rel="icon" type="image/svg+xml" href="assets/favicon.svg">\n'
            '<link rel="stylesheet" href="assets/styles.css">\n'
            "</head>\n<body>\n"
            '<main class="page-hero"><div class="container">\n'
            '<p class="sec-label">404</p>\n'
            "<h1>This page does not exist.</h1>\n"
            '<p class="lead"><a class="arrow-link" href="index.html">Back to homepage <span class="arrow">→</span></a></p>\n'
            "</div></main>\n</body>\n</html>\n"
        )

    total = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fns in os.walk(DIST)
        for f in fns
    )
    print(f"dist/ built: {total / 1024:.0f} KB total")


if __name__ == "__main__":
    build()
