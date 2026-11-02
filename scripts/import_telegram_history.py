#!/usr/bin/env python3
"""Import a public Telegram snapshot using cached translations and atomic resume."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

try:
    from .update_telegram_feed import OPENAI_DEFAULT_MODEL, OPENAI_PROMPT_VERSION, translate_and_format_ru_to_en_openai
except ImportError:
    from update_telegram_feed import OPENAI_DEFAULT_MODEL, OPENAI_PROMPT_VERSION, translate_and_format_ru_to_en_openai


CHANNEL = "chillhousetech"
SOURCE = "https://t.me/" + CHANNEL


def read_document(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("channel") != CHANNEL or not isinstance(data.get("posts"), list):
        raise ValueError(f"{path}: expected a ChillHouse document with posts")
    seen = set()
    for post in data["posts"]:
        if not isinstance(post, dict) or isinstance(post.get("id"), bool) or not str(post.get("id", "")).isascii() or not str(post.get("id", "")).isdigit() or int(post["id"]) < 1:
            raise ValueError(f"{path}: invalid post ID")
        pid = int(post["id"])
        if pid in seen:
            raise ValueError(f"{path}: duplicate post ID {pid}")
        seen.add(pid)
    return data


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def safe_https(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def prepare_source(post):
    poll = post.get("poll")
    if isinstance(poll, dict):
        question = poll.get("question")
        options = [option.get("text", "") if isinstance(option, dict) else option for option in poll.get("options", [])]
        if not isinstance(question, str) or not question.strip() or not options or any(not isinstance(option, str) or not option.strip() for option in options):
            raise ValueError(f"Post {post['id']}: poll requires a question and options")
        return question + "\n\n" + "\n".join("- " + option for option in options)
    text = post.get("text_ru", "")
    if not isinstance(text, str):
        raise ValueError(f"Post {post['id']}: text_ru must be a string")
    return text


def metadata(post, text):
    media = post.get("media_types") or []
    action = post.get("service_action")
    if action:
        kind = "service"
    elif post.get("poll"):
        kind = "poll"
    elif "document" in media:
        kind = "document"
    elif "video" in media or "round_video" in media:
        kind = "video"
    elif post.get("images"):
        kind = "photo"
    elif not text.strip() or post.get("media_not_supported_in_widget"):
        kind = "unsupported"
    else:
        kind = "text"
    result = {"content_kind": kind}
    notices = {
        "video": "Video available in the original Telegram post.",
        "document": "Document available in the original Telegram post.",
        "unsupported": "This media is unavailable in the public Telegram preview. View the original post on Telegram.",
    }
    if kind in notices:
        result["media_notice_en"] = notices[kind]
    if kind == "service":
        result["media_notice_en"] = {"channel_created": "Channel created on Telegram.", "pinned_message": "A message was pinned on Telegram."}.get(action, "Service message on Telegram.")
    forwarded = post.get("forwarded_from")
    if isinstance(forwarded, dict):
        name = forwarded.get("name") or forwarded.get("text") or ""
        if isinstance(name, str) and name.strip():
            result["forwarded_from"] = {"name": re.sub(r"^Forwarded from\s+", "", name).strip(), "url": safe_https(forwarded.get("url"))}
    for key in ("poll", "source_links", "media_types", "widget_classes", "media_not_supported_in_widget", "document_preview_text", "service_action"):
        if key in post:
            result[key] = post[key]
    return result


def normalized_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


def new_record(post, text, extra):
    pid = int(post["id"])
    date = normalized_date(post.get("date_utc"))
    return {
        "id": pid, "url": f"{SOURCE}/{pid}", "date_utc": date,
        "hash": hashlib.sha256((text + "\n" + (date or "")).encode()).hexdigest(),
        "translation_key": "service-ui:v1" if extra["content_kind"] == "service" else "none:empty_source",
        "text_ru": text, "images": post.get("images") or [],
        "title_en": "", "text_en": "", **extra,
    }


def error_status(error):
    response = getattr(error, "response", None)
    if response is not None:
        return response.status_code
    match = re.search(r"(?:error|HTTP|status)\s*[:=]?\s*(\d{3})\b", str(error), re.I)
    return int(match.group(1)) if match else None


def translate_with_retry(text, model, timeout_s, max_attempts):
    for attempt in range(max_attempts):
        try:
            title, translated = translate_and_format_ru_to_en_openai(text_ru=text, model=model, timeout_s=timeout_s)
            if not isinstance(translated, str) or not translated.strip():
                raise ValueError("Translation returned no English text")
            return title if isinstance(title, str) else "", translated
        except Exception as error:
            status = error_status(error)
            # The shared GPT-5 Responses helper already retries network failures.
            network_retry = not model.startswith("gpt-5") and isinstance(error, (requests.Timeout, requests.ConnectionError))
            transient = status == 429 or (status is not None and 500 <= status <= 599) or network_retry
            if not transient or attempt + 1 >= max_attempts:
                raise
            time.sleep(min(2 ** attempt, 15))


def run_import(snapshot_path, archive_path, checkpoint_path, *, workers=4, model=None, timeout_s=20, max_attempts=3, dry_run=False):
    if not 1 <= workers <= 4 or not 1 <= max_attempts <= 5:
        raise ValueError("workers must be 1–4 and max_attempts must be 1–5")
    snapshot = read_document(snapshot_path)
    archive = read_document(archive_path)
    checkpoint_path = Path(checkpoint_path)
    model = model or OPENAI_DEFAULT_MODEL
    translation_key = f"openai:{model}:{OPENAI_PROMPT_VERSION}"
    checkpoint = {"version": 1, "channel": CHANNEL, "translations": {}}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, dict) or checkpoint.get("version") != 1 or checkpoint.get("channel") != CHANNEL or not isinstance(checkpoint.get("translations"), dict):
            raise ValueError("Invalid translation checkpoint; refusing to discard it")
    records = {int(post["id"]): dict(post) for post in archive["posts"]}
    pending = []
    reused = empty = services = added = 0
    for post in snapshot["posts"]:
        pid = int(post["id"])
        text = prepare_source(post)
        extra = metadata(post, text)
        if pid in records:
            # Preserve every existing value, including original text and cache keys.
            for key, value in extra.items():
                records[pid].setdefault(key, value)
            continue
        added += 1
        record = new_record(post, text, extra)
        records[pid] = record
        if extra["content_kind"] == "service":
            services += 1
            continue
        if not text.strip():
            empty += 1
            continue
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        cached = checkpoint["translations"].get(str(pid), {})
        if isinstance(cached, dict) and cached.get("source_text_sha256") == text_hash and cached.get("translation_key") == translation_key and isinstance(cached.get("text_en"), str) and cached["text_en"].strip():
            record.update(title_en=cached.get("title_en", ""), text_en=cached["text_en"], translation_key=translation_key)
            reused += 1
        else:
            pending.append((pid, text, text_hash))
    report = {
        "status": "dry_run" if dry_run else "complete", "model": model,
        "source_records": len(snapshot["posts"]), "existing_records": len(archive["posts"]),
        "new_records": added, "total_records": len(records), "pending_translations": len(pending),
        "pending_source_characters": sum(len(text) for _, text, _ in pending),
        "checkpoint_reused": reused, "empty_caption_records": empty, "service_records": services,
        "translated": 0, "errors": [],
    }
    if dry_run:
        return report
    if pending and not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is required for pending translations; archive and checkpoint were not changed")
    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(translate_with_retry, text, model, timeout_s, max_attempts): (pid, text_hash) for pid, text, text_hash in pending}
            for future in concurrent.futures.as_completed(futures):
                if future.cancelled():
                    continue
                pid, text_hash = futures[future]
                try:
                    title, translated = future.result()
                except Exception as error:
                    status = error_status(error)
                    # Do not print API response bodies or any credentials.
                    report["errors"].append({"id": pid, "error": type(error).__name__, "http_status": status})
                    if status in (401, 403):
                        for remaining in futures:
                            remaining.cancel()
                    continue
                records[pid].update(title_en=title, text_en=translated, translation_key=translation_key)
                checkpoint["translations"][str(pid)] = {"source_text_sha256": text_hash, "translation_key": translation_key, "title_en": title, "text_en": translated}
                atomic_json(checkpoint_path, checkpoint)
                report["translated"] += 1
                if report["translated"] % 25 == 0:
                    print(f"Checkpoint saved: {report['translated']} new translations, {reused} resumed.", file=sys.stderr, flush=True)
    untranslated = [pid for pid, _, _ in pending if not records[pid]["text_en"].strip()]
    if untranslated:
        report.update(status="partial", untranslated_ids=sorted(untranslated))
        return report
    result = dict(archive)
    result["posts"] = [records[pid] for pid in sorted(records, reverse=True)]
    atomic_json(archive_path, result)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "--snapshot", dest="snapshot", type=Path, default=Path("data/telegram-history.json"))
    parser.add_argument("--archive", type=Path, default=Path("archive.json"))
    parser.add_argument("--checkpoint", type=Path, default=Path("data/telegram-history-translations.json"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_import(args.snapshot, args.archive, args.checkpoint, workers=args.workers, model=args.model, timeout_s=args.timeout, max_attempts=args.max_attempts, dry_run=args.dry_run)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] in ("complete", "dry_run") else 1
    except (OSError, ValueError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
