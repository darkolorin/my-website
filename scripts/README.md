## Telegram → static website feed (OpenAI or free/offline translation)

This repo keeps the website **fully static**. A small script scrapes the public Telegram preview page, translates posts to English (OpenAI or offline), extracts images, and writes `feed.json`. The website renders that JSON in `essays.html`.

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
```

Serve the site locally (so `fetch('feed.json')` works):

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/essays.html`.

### Notes

- This uses the public Telegram preview page: `https://t.me/s/<channel>`
- **Default translation mode is `--translator auto`**:
  - If `OPENAI_API_KEY` is set → uses OpenAI (better translation + nicer formatting)
  - Otherwise → uses **Argos Translate** (free/offline)
- You can disable translation with `--translator none`.
  - If you’re on a very new Python (e.g. 3.14) and installs fail, try `python3.12 -m venv .venv` instead.
- Images from Telegram posts are included in `feed.json` (`images: [...]`) and rendered on `essays.html`.

### OpenAI translation / formatting (safe API key handling)

Run locally:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o"   # optional (default)
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


