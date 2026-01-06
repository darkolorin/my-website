## Telegram → static website feed (free/offline translation)

This repo keeps the website **fully static**. A small script scrapes the public Telegram preview page, translates posts to English offline, and writes `feed.json`. The website renders that JSON in `essays.html`.

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
- Translation backend is **Argos Translate** (free/offline). You can disable translation with `--translator none`.
  - If you’re on a very new Python (e.g. 3.14) and installs fail, try `python3.12 -m venv .venv` instead.

### Enable auto-updates on GitHub

Create a workflow file at `.github/workflows/update-telegram-feed.yml` and paste the contents of:

- `scripts/update-telegram-feed.workflow.yml`


