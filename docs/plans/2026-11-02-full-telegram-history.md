# Full Telegram History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Translate all known public ChillHouse history with the existing translator, retain the permanent archive, and expose every stored post in static HTML and RSS.

**Architecture:** Import a captured public-preview snapshot into the existing archive. Preserve existing source/English pairs and the cached post missing from current public previews; translate only missing records with the same model and editorial prompt. Run the import on the feature branch through GitHub Actions using the existing repository secret, checkpoint results, then review and publish the completed archive.

**Tech Stack:** Python standard library, existing requests/BeautifulSoup importer and OpenAI translation function, static HTML/RSS, GitHub Actions/Pages.

## Agreed design

- Known inventory: 1,191 publicly visible message IDs plus cached post 1205, totaling 1,192 known records. Do not claim deleted or hidden messages were recovered.
- Include captions, captionless photos, polls, documents, video references, and service messages. Preserve real source dates; missing dates remain undated.
- Poll text includes the question and options, with no changing vote counts presented as permanent results. Unavailable media gets an honest neutral reference to Telegram.
- Keep current English translations and author text intact. Preserve source links and forwarding attribution. Do not invent descriptions or transcripts.
- Retain the latest-window `feed.json` for the regular importer; grow `archive.json` permanently. Every stored record appears in `essays.html`, its stable `posts/<id>.html`, RSS, and sitemap.
- GA4 keeps its existing compact consent request. External anchor attribution remains static HTML, with existing campaigns and sensitive/signed/download URLs preserved.

## Task 1: Resumable history importer

**Files:** create `scripts/import_telegram_history.py`, `scripts/test_import_telegram_history.py`, `data/telegram-history.json`.

1. Add failing tests for preserving existing translations, poll extraction, media-only records, date preservation, resume, and partial translation failures.
2. Normalize the captured inventory into a reproducible public source snapshot without transient UI counters.
3. Reuse `translate_and_format_ru_to_en_openai` and the existing prompt/model. Bound concurrency, retry transient failures, save successful records atomically, and fail when required translations remain unfinished.
4. Verify dry-run makes no API calls and a resumed run does not repeat successful work.
5. Run `python3 -m unittest discover -s scripts -p 'test_import_telegram_history.py' -v`.

## Task 2: Complete RSS and honest media rendering

**Files:** modify `scripts/build_archive.py`, `scripts/test_build_archive.py`.

1. Add failing tests showing more than 50 RSS items, stable GUIDs, captionless media, polls, and safe forwarding attribution.
2. Remove the RSS window limit. Use neutral media titles and notices when there is no authored caption, without claiming a missing translation.
3. Preserve all existing text, URL, escaping, date, and attribution rules.
4. Run `python3 -m unittest discover -s scripts -p 'test_build_archive.py' -v`.

## Task 3: Branch-scoped translation execution

**Files:** modify `.github/workflows/update-telegram-feed.yml`, mirrored `scripts/update-telegram-feed.workflow.yml`, `scripts/README.md`.

1. Add an explicit manual history-import input; scheduled runs retain their current latest-feed behavior.
2. Check out and commit to the run's branch. Historical translation executes only on the feature branch until review/merge.
3. Save a resumable archive checkpoint even if a translation fails. Keep the key confined to the existing Actions secret environment.
4. Run all Python and analytics tests, inspect the complete diff, and push the feature branch.
5. Dispatch the history import, monitor completion, and retrieve the resulting branch commit.

## Task 4: Review and publication

1. Verify all 1,192 known IDs are retained once, cached translations are unchanged, every nonempty new source has an English result, and dates are never fabricated.
2. Rebuild twice to verify deterministic output; parse RSS/sitemap and inspect representative text, poll, photo, document, and undated pages.
3. Check mobile widths 320/390/430 and a desktop viewport in the browser, preserving the plain HTML style.
4. Obtain independent code review, open/merge the PR, wait for Pages deployment, and verify the live archive/RSS/sample pages and GA consent behavior.
