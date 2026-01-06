#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
import time
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
OPENAI_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-5.2"
OPENAI_PROMPT_VERSION = "pro_editorial_translator_v1"

OPENAI_SYSTEM_PROMPT = """You are a professional editorial translator.

Your task is to translate posts from Russian to English while STRICTLY preserving:
- the author’s original tone of voice
- informal or semi-informal style
- slang, jargon, irony, sarcasm, and cynicism
- short or abrupt sentence structure
- rhetorical questions
- intentional roughness or blunt phrasing

This is NOT a localization task.
This is NOT a rewrite or polishing task."""

OPENAI_USER_PROMPT_TEMPLATE = '''Translate the following post from Russian to English.
Preserve the author’s style, tone, and jargon exactly as described.

Post:
"""
{POST_TEXT}
"""

Rules:
- Do NOT explain anything.
- Do NOT add context.
- Do NOT simplify ideas.
- Do NOT make the text more polite, neutral, or corporate.
- Do NOT remove ambiguity or emotional sharpness.
- Do NOT normalize profanity or edgy phrasing unless it is impossible to translate directly.

If the author sounds opinionated, skeptical, ironic, tired, sarcastic, or provocative — preserve it.
If the text jumps between technical language and casual speech — preserve it.
If sentences are fragmented or abrupt — preserve it.

Translate meaning-for-meaning, not word-for-word, but always favor STYLE over linguistic correctness.

Output ONLY the translated text.'''


@dataclass(frozen=True)
class TgPost:
    channel: str
    message_id: int
    url: str
    date_utc: Optional[str]
    text_ru: str
    images: List[str]

    @property
    def key(self) -> str:
        return f"{self.channel}/{self.message_id}"

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.text_ru.encode("utf-8"))
        h.update(b"\n")
        h.update((self.date_utc or "").encode("utf-8"))
        if self.images:
            h.update(b"\n")
            for u in self.images:
                h.update(str(u).encode("utf-8"))
                h.update(b"\n")
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
        choices=["auto", "openai", "argos", "none"],
        default="auto",
        help="Translation backend. 'auto' uses OpenAI if OPENAI_API_KEY is set, else Argos. 'argos' is free/offline. 'none' disables translation.",
    )
    p.add_argument("--openai-model", default=OPENAI_DEFAULT_MODEL, help="OpenAI model (default: env OPENAI_MODEL or gpt-4o-mini).")
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


def _extract_bg_image_url(style: str) -> Optional[str]:
    # style like: background-image:url('https://...'); or url("...") or url(...)
    m = re.search(r"background-image\s*:\s*url\(([^)]+)\)", style or "")
    if not m:
        return None
    raw = m.group(1).strip().strip("'").strip('"').strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return None


def extract_image_urls(el) -> List[str]:
    urls: List[str] = []

    # Photos & video previews are often background-image on <a>
    for a in el.select("a.tgme_widget_message_photo_wrap, a.tgme_widget_message_video_player"):
        style = a.get("style") if hasattr(a, "get") else None
        if isinstance(style, str):
            u = _extract_bg_image_url(style)
            if u:
                urls.append(u)

    # Fallback: any <img src="..."> inside the message
    for img in el.select("img"):
        # Avoid grabbing the channel avatar (repeated on every post)
        if img.find_parent(class_="tgme_widget_message_user") is not None:
            continue
        if img.find_parent(class_="tgme_widget_message_user_photo") is not None:
            continue
        src = img.get("src") if hasattr(img, "get") else None
        if isinstance(src, str) and (src.startswith("http://") or src.startswith("https://")):
            urls.append(src)

    # Dedupe while preserving order
    out: List[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def parse_preview_html(channel: str, html: str) -> List[TgPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: List[TgPost] = []
    for msg in soup.select(".tgme_widget_message"):
        id_and_url = extract_message_id_and_url(channel, msg)
        if not id_and_url:
            continue
        msg_id, url = id_and_url
        text_ru = extract_text_ru(msg)
        images = extract_image_urls(msg)
        # Skip totally empty posts (e.g., sticker-only) to keep the feed readable
        if not text_ru and not images:
            continue
        posts.append(
            TgPost(
                channel=channel,
                message_id=msg_id,
                url=url,
                date_utc=extract_date_utc(msg),
                text_ru=text_ru,
                images=images,
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


def openai_chat_completion(
    *,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout_s: int,
    response_format: Optional[Dict[str, str]] = None,
) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    if response_format:
        payload["response_format"] = response_format
    openai_timeout = max(180, timeout_s)
    r = requests.post(url, headers=headers, json=payload, timeout=openai_timeout)
    if not r.ok:
        raise RuntimeError(f"OpenAI chat.completions error {r.status_code}: {r.text}")
    data = r.json()
    return str(data["choices"][0]["message"]["content"])


def openai_responses_text(*, api_key: str, model: str, system: str, user: str, timeout_s: int) -> str:
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        # Recommended shape for newest models: user input + separate instructions.
        "instructions": system,
        "input": user,
    }
    openai_timeout = max(180, timeout_s)
    # Retry a couple of times on read timeouts / transient network issues.
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=openai_timeout)
            break
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    else:
        if last_err:
            raise last_err
        raise RuntimeError("OpenAI request failed (unknown error).")

    if not r.ok:
        raise RuntimeError(f"OpenAI responses error {r.status_code}: {r.text}")
    data = r.json()

    # Some responses include a convenience field.
    out_text = data.get("output_text")
    if isinstance(out_text, str) and out_text.strip():
        return out_text.strip()

    # Otherwise, stitch together all output_text parts.
    parts: List[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for c in item.get("content", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") in ("output_text", "text"):
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
    return "\n".join(parts).strip()


def openai_text(*, api_key: str, model: str, system: str, user: str, timeout_s: int) -> str:
    """
    Uses Responses API for gpt-5* models (and falls back to chat.completions for older models).
    """
    if model.startswith("gpt-5"):
        return openai_responses_text(api_key=api_key, model=model, system=system, user=user, timeout_s=timeout_s)
    return openai_chat_completion(
        api_key=api_key,
        model=model,
        timeout_s=timeout_s,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )


def translate_and_format_ru_to_en_openai(*, text_ru: str, model: str, timeout_s: int) -> Tuple[str, str]:
    """Returns (title_en, text_en). title_en is intentionally left blank for this prompt."""
    if not text_ru.strip():
        return "", ""

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    system = OPENAI_SYSTEM_PROMPT
    user = OPENAI_USER_PROMPT_TEMPLATE.replace("{POST_TEXT}", text_ru)
    content = openai_text(api_key=api_key, model=model, system=system, user=user, timeout_s=timeout_s)

    # Output is expected to be ONLY the translated text.
    return "", content.strip()


def build_feed(
    *,
    channel: str,
    posts: List[TgPost],
    existing_feed: Dict[str, Any],
    translator: str,
    openai_model: str,
    timeout_s: int,
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

    translator_effective = translator
    if translator == "auto":
        translator_effective = "openai" if os.environ.get("OPENAI_API_KEY", "").strip() else "argos"

    translation_key = translator_effective
    if translator_effective == "openai":
        translation_key = f"openai:{openai_model}:{OPENAI_PROMPT_VERSION}"

    out_posts: List[Dict[str, Any]] = []
    for p in posts:
        existing = existing_by_id.get(str(p.message_id), {})
        existing_hash = existing.get("hash") if isinstance(existing, dict) else None
        existing_text_en = existing.get("text_en") if isinstance(existing, dict) else None
        existing_title_en = existing.get("title_en") if isinstance(existing, dict) else None
        existing_translation_key = existing.get("translation_key") if isinstance(existing, dict) else None
        reuse_translation = (
            isinstance(existing_hash, str)
            and existing_hash == p.content_hash
            and isinstance(existing_text_en, str)
            and existing_text_en.strip() != ""
            and isinstance(existing_translation_key, str)
            and existing_translation_key == translation_key
        )
        reuse_title = (
            isinstance(existing_hash, str)
            and existing_hash == p.content_hash
            and isinstance(existing_title_en, str)
            and existing_title_en.strip() != ""
        )

        text_en = ""
        title_en = ""
        if translator_effective == "none":
            text_en = ""
            title_en = ""
        elif reuse_translation:
            text_en = existing_text_en
            if reuse_title:
                title_en = existing_title_en
        else:
            if translator_effective == "openai":
                title_en, text_en = translate_and_format_ru_to_en_openai(
                    text_ru=p.text_ru,
                    model=openai_model,
                    timeout_s=timeout_s,
                )
            else:
                text_en = translate_ru_to_en_argos(p.text_ru)

        out_posts.append(
            {
                "id": p.message_id,
                "url": p.url,
                "date_utc": p.date_utc,
                "hash": p.content_hash,
                "translation_key": translation_key,
                "text_ru": p.text_ru,
                "images": p.images,
                "title_en": title_en,
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

    translator_effective = args.translator
    if args.translator == "auto":
        translator_effective = "openai" if os.environ.get("OPENAI_API_KEY", "").strip() else "argos"

    if translator_effective == "openai" and not os.environ.get("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY is not set (required for --translator openai).", file=sys.stderr)
        return 2

    if translator_effective == "argos" and "argostranslate" not in sys.modules:
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

    feed = build_feed(
        channel=channel,
        posts=posts,
        existing_feed=existing,
        translator=str(args.translator),
        openai_model=str(args.openai_model),
        timeout_s=max(5, args.timeout),
    )
    write_json(args.out, feed)
    print(f"Wrote {len(posts)} posts to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


