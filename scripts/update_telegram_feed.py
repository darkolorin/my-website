#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

try:
    import argostranslate.package
    import argostranslate.translate
except Exception:
    argostranslate = None  # type: ignore


CHANNEL_RE = re.compile(r"^[a-zA-Z0-9_]{5,}$")


@dataclass(frozen=True)
class TgPost:
    channel: str
    message_id: int
    url: str
    date_utc: Optional[str]
    text_ru: str

    @property
    def key(self) -> str:
        return f"{self.channel}/{self.message_id}"

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.text_ru.encode("utf-8"))
        h.update(b"\n")
        h.update((self.date_utc or "").encode("utf-8"))
        return h.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a static JSON feed from a public Telegram channel.")
    p.add_argument("--channel", default="chillhousetech", help="Telegram channel username (without @).")
    p.add_argument("--limit", type=int, default=25, help="How many newest posts to include.")
    p.add_argument(
        "--out",
        default="feed.json",
        help="Output JSON path (default: feed.json).",
    )
    p.add_argument("--max-pages", type=int, default=6, help="Max pagination requests to Telegram preview pages.")
    p.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds.")
    p.add_argument("--user-agent", default="Mozilla/5.0 (compatible; feed-bot/1.0)", help="HTTP User-Agent header.")
    p.add_argument(
        "--translator",
        choices=["argos", "none"],
        default="argos",
        help="Translation backend. 'argos' is free/offline. 'none' disables translation.",
    )
    return p.parse_args(argv)


def http_get(url: str, timeout_s: int, user_agent: str) -> str:
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": user_agent})
    r.raise_for_status()
    return r.text


def extract_message_id_and_url(channel: str, el) -> Optional[Tuple[int, str]]:
    # Telegram preview uses data-post="channel/123"
    data_post = el.get("data-post") if hasattr(el, "get") else None
    if data_post and isinstance(data_post, str) and data_post.startswith(channel + "/"):
        try:
            msg_id = int(data_post.split("/", 1)[1])
            return msg_id, f"https://t.me/{channel}/{msg_id}"
        except Exception:
            return None

    # Fallback: find date link with href ".../123"
    a = el.select_one("a.tgme_widget_message_date")
    if a and a.has_attr("href"):
        href = a["href"]
        m = re.search(rf"https?://t\.me/{re.escape(channel)}/(\d+)", href)
        if m:
            msg_id = int(m.group(1))
            return msg_id, href
    return None


def extract_date_utc(el) -> Optional[str]:
    time_el = el.select_one("time")
    if time_el and time_el.has_attr("datetime"):
        dt = str(time_el["datetime"]).strip()
        return dt or None
    return None


def extract_text_ru(el) -> str:
    text_el = el.select_one(".tgme_widget_message_text")
    if not text_el:
        return ""
    # Preserve line breaks from <br> etc.
    txt = text_el.get_text("\n")
    return (txt or "").strip()


def parse_preview_html(channel: str, html: str) -> List[TgPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: List[TgPost] = []
    for msg in soup.select(".tgme_widget_message"):
        id_and_url = extract_message_id_and_url(channel, msg)
        if not id_and_url:
            continue
        msg_id, url = id_and_url
        text_ru = extract_text_ru(msg)
        # Skip totally empty posts (e.g., sticker-only) to keep the feed readable
        if not text_ru:
            continue
        posts.append(
            TgPost(
                channel=channel,
                message_id=msg_id,
                url=url,
                date_utc=extract_date_utc(msg),
                text_ru=text_ru,
            )
        )
    return posts


def fetch_latest_posts(channel: str, limit: int, max_pages: int, timeout_s: int, user_agent: str) -> List[TgPost]:
    seen: set[str] = set()
    collected: List[TgPost] = []
    before: Optional[int] = None

    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        html = http_get(url, timeout_s=timeout_s, user_agent=user_agent)
        page_posts = parse_preview_html(channel, html)
        if not page_posts:
            break

        new_in_page = 0
        for p in page_posts:
            if p.key in seen:
                continue
            seen.add(p.key)
            collected.append(p)
            new_in_page += 1

        # Pagination: request older posts next
        oldest_id = min(p.message_id for p in page_posts)
        if before is not None and oldest_id >= before:
            break
        before = oldest_id

        if new_in_page == 0:
            break
        if len(collected) >= limit:
            break

    # Keep newest first
    collected.sort(key=lambda p: p.message_id, reverse=True)
    return collected[:limit]


def load_existing_feed(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ensure_argos_ru_en_installed() -> None:
    installed = argostranslate.translate.get_installed_languages()
    has_ru = any(l.code == "ru" for l in installed)
    has_en = any(l.code == "en" for l in installed)
    if has_ru and has_en:
        return

    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    pkg = next((p for p in available if p.from_code == "ru" and p.to_code == "en"), None)
    if not pkg:
        raise RuntimeError("Could not find Argos translation package ru->en.")
    download_path = pkg.download()
    argostranslate.package.install_from_path(download_path)


def translate_ru_to_en_argos(text_ru: str) -> str:
    if not text_ru.strip():
        return ""

    ensure_argos_ru_en_installed()

    # Chunk by paragraphs to avoid extremely long sequences
    parts = re.split(r"\n{2,}", text_ru.strip())
    out_parts: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        out_parts.append(argostranslate.translate.translate(part, "ru", "en"))
    return "\n\n".join(out_parts).strip()


def build_feed(
    *,
    channel: str,
    posts: List[TgPost],
    existing_feed: Dict[str, Any],
    translator: str,
) -> Dict[str, Any]:
    existing_posts = existing_feed.get("posts") if isinstance(existing_feed.get("posts"), list) else []
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    for p in existing_posts:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if isinstance(pid, int):
            existing_by_id[str(pid)] = p
        elif isinstance(pid, str):
            existing_by_id[pid] = p

    out_posts: List[Dict[str, Any]] = []
    for p in posts:
        existing = existing_by_id.get(str(p.message_id), {})
        existing_hash = existing.get("hash") if isinstance(existing, dict) else None
        existing_text_en = existing.get("text_en") if isinstance(existing, dict) else None
        reuse_translation = (
            isinstance(existing_hash, str)
            and existing_hash == p.content_hash
            and isinstance(existing_text_en, str)
            and existing_text_en.strip() != ""
        )

        text_en = ""
        if translator == "none":
            text_en = ""
        elif reuse_translation:
            text_en = existing_text_en
        else:
            text_en = translate_ru_to_en_argos(p.text_ru)

        out_posts.append(
            {
                "id": p.message_id,
                "url": p.url,
                "date_utc": p.date_utc,
                "hash": p.content_hash,
                "text_ru": p.text_ru,
                "text_en": text_en,
            }
        )

    return {
        "generated_at_utc": utc_now_iso(),
        "source": f"https://t.me/{channel}",
        "channel": channel,
        "posts": out_posts,
    }


def write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    channel = args.channel.strip().lstrip("@")
    if not CHANNEL_RE.match(channel):
        print(f"Invalid channel: {channel!r}", file=sys.stderr)
        return 2

    if args.translator == "argos" and "argostranslate" not in sys.modules:
        print("Argos Translate is not available. Did you install scripts/requirements.txt?", file=sys.stderr)
        return 2

    existing = load_existing_feed(args.out)

    posts = fetch_latest_posts(
        channel=channel,
        limit=max(1, args.limit),
        max_pages=max(1, args.max_pages),
        timeout_s=max(5, args.timeout),
        user_agent=args.user_agent,
    )

    feed = build_feed(channel=channel, posts=posts, existing_feed=existing, translator=args.translator)
    write_json(args.out, feed)
    print(f"Wrote {len(posts)} posts to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


