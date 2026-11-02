# Initial archive recovery

The initial `archive.json` was recovered from the current `feed.json` and the local `main` history at `1b6ac4caed7caa0c2c4ba734b0e824628b359a2e`. No remote fetch, translation API call, image download, commit, or publication was performed by this backfill.

```bash
python3 scripts/backfill_archive.py --repo . --out archive.json --feed feed.json
python3 -m unittest discover -s scripts -p 'test_backfill_archive.py' -v
```

Paths supplied to `--feed` and `--out` are relative to `--repo` unless absolute. The script reads only the selected feed path in local `main` history; it does not read generated archive artifacts as history inputs.

## Recovered source

- 1,163 valid historical feed snapshots; none skipped.
- 158 unique posts, IDs 1174 through 1348 with gaps, sorted by numeric ID descending.
- All 158 posts have cached English translations. The current feed contributes 25 posts; history recovers another 133.
- Earliest known publication: 2025-11-18T16:16:06+00:00.
- Latest known publication: 2026-11-01T20:23:12+00:00.
- All 25 current records retain their original RU text, English text, image references, and date fields exactly.

The oldest stored feed snapshot is commit `6f6c18ecaf6b0d4cfb3dc70a981d7498daadc24b` from 2026-01-06; that snapshot includes older posts. This recovery is the site's available history, not a claim to contain the entire Telegram channel.

## Dates and content precedence

Current feed records take precedence over historical records. Older snapshots can fill empty text fields; an older English translation or title is reused only when its RU original matches. Known dates are retained. A missing date can be recovered only from a valid timezone-aware timestamp for the same channel and numeric post ID.

IDs **1214, 1222, 1231, 1247, 1249, and 1338** have no publication timestamp in any historical version. They remain `date_utc: null`; no dates were synthesized from scrape times, Git commits, or neighboring posts. Their RSS entries should omit `pubDate`.

Historical cache hashes were recomputed from the preserved RU text and date using the current generator's algorithm, excluding rotating image URLs. This changes cache metadata without changing translations or originals.

Malformed historical JSON is skipped and reported; an invalid current feed fails before writing output. Output contains only the canonical `channel`, `source`, and `posts` root keys, without build timestamps, and is deterministic for the same inputs.

## Remaining source limits

Older snapshots discarded descriptive Telegram link destinations. Those missing hrefs cannot be recovered from Git alone. Images remain references to Telegram CDN URLs, which are not permanent media copies; no images were downloaded during this local recovery.

## Image reference refresh

Before publication, expired Telegram CDN references were refreshed from public previews for 33 older posts (38 image URLs). All 51 current image references returned HTTP 200. Original text, translations, dates and cache hashes were unchanged; image files remain on Telegram rather than being stored in the repository.
