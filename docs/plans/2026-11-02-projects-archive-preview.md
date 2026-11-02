# Projects and permanent essays archive

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Projects, permanent article pages, and RSS while retaining the existing plain HTML style.

**Architecture:** Keep the existing Telegram importer and cached English translations. Recover posts already present in repository history into archive.json; merge future latest feeds without deleting older records. A standard-library Python renderer writes static essays.html, posts/<id>.html, rss.xml, and sitemap.xml. No browser rendering dependency or new frontend framework.

**Tech Stack:** HTML, existing optional analytics JavaScript, Python standard library, RSS 2.0.

---

1. Add Mirai with the supplied Models, runtime and infrastructure links, plus RSS discovery/navigation to index.html.
2. Write backfill regression tests, then recover the latest saved content for every historical ID. Preserve current-feed overrides and genuine dates; retain undated posts without invented dates.
3. Write archive/RSS regression tests before implementing the static renderer. Verify retention, stable URLs/GUIDs, missing dates, safe text/URL handling, and all internal links.
4. Prepare workflow changes so future imports also update the permanent archive, generated pages, RSS, and sitemap.
5. Adjust analytics privacy links for nested article paths and add a regression test. Keep the localhost analytics guard.
6. Generate the local preview, verify RSS/XML, text preservation, metadata and internal links, then review the rendered homepage, archive and representative articles at desktop and mobile widths. Fix layout defects, then publish the approved version and verify live HTML, article pages and RSS.

## Acceptance

- Projects contains Mirai with the supplied linked description and ordinary text links.
- Every recovered post has a stable HTML page and is reachable without JavaScript.
- A subsequent latest25 update does not remove old posts.
- RSS parses as RSS 2.0 and item GUIDs remain stable after title/text edits.
- Publication dates are source dates; missing dates remain missing.
- Text, links and images fit narrow mobile widths without horizontal overflow.
- Verify publication separately from local tests, including the live homepage, archive, sample posts, RSS and mobile layout.
