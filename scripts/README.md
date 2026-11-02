## Telegram → static website feed (OpenAI or free/offline translation)

This repo keeps the website **fully static**. The Telegram importer writes the latest 25 posts and cached English translations to `feed.json`. A separate, offline renderer merges those posts into `archive.json` and generates ordinary HTML article pages, the Essays index, RSS, and the sitemap.

### Local run

Create a virtualenv (recommended on macOS/Homebrew Python) and install deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements.txt
```

Generate `feed.json`:

```bash
python3 scripts/update_telegram_feed.py --channel chillhousetech --limit 25 --out feed.json
python3 scripts/build_archive.py --feed feed.json --archive archive.json --output-dir .
```

Serve the generated site locally:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/essays.html`.

### Permanent archive and RSS

To render the already cached content locally, without scraping or translation requests:

```bash
python3 scripts/build_archive.py --feed feed.json --archive archive.json --output-dir .
```

- `archive.json` retains earlier posts when they leave the latest-25 window. Fresh records update the same post ID.
- `essays.html` is a static index; `posts/<id>.html` are permanent article pages. Both remain readable without JavaScript.
- `rss.xml` contains all archived posts with stable article URLs/GUIDs. Only genuine source dates are emitted as publication dates.
- `sitemap.xml` includes permanent article pages. Titles use the existing opening text rather than newly generated editorial headlines.
- Derived headings/descriptions omit URL targets for readability. Saved author text stays unchanged; recovered source links missing from an older cached translation appear in a separate links list in HTML and RSS.
- Images retain their original Telegram CDN URLs; permanence currently applies to the saved text, links, and article addresses.

The first 158 posts were recovered from existing `feed.json` revisions in this repository, preserving cached translations. To repeat that original one-time recovery:

```bash
python3 scripts/backfill_archive.py --repo . --feed feed.json --out archive.json
```

The subsequent full-history import uses `data/telegram-history.json`, captured from 65 public-preview pages down to message ID 1. It contains 1,191 publicly visible records from February 2023 onward; the archive also retains cached post 1205, which is no longer available in public previews. This is the known accessible history, not a guarantee that deleted or hidden posts can be recovered.

Inspect the import without making translation requests:

```bash
python3 scripts/import_telegram_history.py --input data/telegram-history.json --archive archive.json --dry-run
```

The manual **Update Telegram feed** workflow has an `import_history` option. Run it on the feature branch to use the existing repository API secret, import missing translations with the same editorial prompt/model, and rebuild all static output. Successful translations are checkpointed in `data/telegram-history-translations.json`; a failed run saves that checkpoint on its branch so a rerun can resume. The archive is replaced only after every required new translation succeeds. Completed checkpoints are removed after saving the archive.

Polls preserve their questions and options; changing vote totals are excluded. Captionless media uses neutral references to the Telegram original rather than invented captions. Forwarding attribution is retained. Missing dates stay unknown. Scheduled runs continue to import the latest 25 posts every six hours and retain the older archive; the regular parser also accepts new polls and media-only messages.

For normal updates use the importer and renderer commands above. Do not edit generated article pages directly: edit their saved source record and regenerate instead.

Regression checks:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
node --test tests/analytics.test.cjs
```

### Outbound link attribution

The renderer adds `utm_source=darkolorin.com`, `utm_medium=referral`, and `utm_campaign=personal_site` to normal external HTTP(S) anchor destinations. This works in the static HTML, without JavaScript. Destinations that support campaign attribution can use those labels; some platforms ignore them.

Existing campaign parameters are left intact rather than mixed with a new campaign. Signed/authenticated URLs, direct downloads, internal links, and non-HTTP links are excluded. Only rendered anchor attributes change: visible link labels, saved post text, image URLs, canonical URLs, and RSS article GUIDs remain unchanged. External anchors retain `noopener` and omit `noreferrer`, allowing the browser's default origin referrer as a fallback.

After adding external links to the manually maintained homepage or privacy page, apply the same rules with:

```bash
python3 scripts/outbound_links.py index.html privacy.html
```

The command and archive renderer are idempotent; repeated runs do not append duplicate parameters.

### Notes

- This uses the public Telegram preview page: `https://t.me/s/<channel>`
- **Default translation mode is `--translator auto`**:
  - If `OPENAI_API_KEY` is set → uses OpenAI (better translation + nicer formatting)
  - Otherwise → uses **Argos Translate** (free/offline)
- You can disable translation with `--translator none`.
  - If you’re on a very new Python (e.g. 3.14) and installs fail, try `python3.12 -m venv .venv` instead.
- Images from Telegram posts are included in `feed.json` (`images: [...]`) and rendered on their article pages.
- The translation cache hashes post text and date, excluding rotating Telegram image URLs; image metadata can refresh without repeating paid text translation.
- HTTP(S) destinations on descriptive Telegram links are retained in the extracted text so they can be translated and displayed as links on the website.
- If the Telegram preview contains no recognizable posts, generation fails and leaves the existing output untouched.

Run the feed regression checks without network calls or translation API usage:

```bash
python3 -m unittest discover -s scripts -p 'test_update_telegram_feed.py' -v
```

### OpenAI translation / formatting (safe API key handling)

Run locally:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-5.2"   # optional (default)
python3 scripts/update_telegram_feed.py --translator openai
```

Important: **the API key is only used by the generator (worker)**. It is never embedded into the website or `feed.json`.

### Enable auto-updates on GitHub

Create a workflow file at `.github/workflows/update-telegram-feed.yml` and paste the contents of:

- `scripts/update-telegram-feed.workflow.yml`

If you want OpenAI translation in GitHub Actions:

- Add a repo secret: `OPENAI_API_KEY`
- Optionally add: `OPENAI_MODEL`
- Keep the workflow using `--translator auto` (recommended) or set `--translator openai`


