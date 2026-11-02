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
- `rss.xml` contains the latest 50 posts with stable article URLs/GUIDs. Only genuine source dates are emitted as publication dates.
- `sitemap.xml` includes permanent article pages. Titles use the existing opening text rather than newly generated editorial headlines.
- Images retain their original Telegram CDN URLs; permanence currently applies to the saved text, links, and article addresses.

The initial archive was recovered from existing `feed.json` revisions in this repository, preserving cached translations. It is the recoverable history of this website, not a complete export of the Telegram channel. To repeat that one-time recovery:

```bash
python3 scripts/backfill_archive.py --repo . --feed feed.json --out archive.json
```

For normal updates use the importer and renderer commands above. Do not edit generated article pages directly: edit their saved source record and regenerate instead.

Regression checks:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
node --test tests/analytics.test.cjs
```

### Notes

- This uses the public Telegram preview page: `https://t.me/s/<channel>`
- **Default translation mode is `--translator auto`**:
  - If `OPENAI_API_KEY` is set → uses OpenAI (better translation + nicer formatting)
  - Otherwise → uses **Argos Translate** (free/offline)
- You can disable translation with `--translator none`.
  - If you’re on a very new Python (e.g. 3.14) and installs fail, try `python3.12 -m venv .venv` instead.
- Images from Telegram posts are included in `feed.json` (`images: [...]`) and rendered on `essays.html`.
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
export OPENAI_MODEL="gpt-5"   # optional (default)
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


