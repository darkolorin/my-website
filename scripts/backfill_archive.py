#!/usr/bin/env python3
"""Recover cached posts from local main history, without fetching or translating."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CHANNEL = "chillhousetech"
SOURCE = "https://t.me/" + CHANNEL


def git(repo, *args, input_data=None):
    result = subprocess.run(
        ["git", *args], cwd=repo, input=input_data, capture_output=True,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def snapshot(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("channel") != CHANNEL or not isinstance(data.get("posts"), list):
        raise ValueError("expected a ChillHouse feed with a posts array")
    return data


def historical_snapshots(repo, feed_path):
    commits = git(repo, "log", "--date-order", "--format=%H", "main", "--", feed_path).decode().splitlines()
    if not commits:
        return [], 0
    # Batch-reading blobs avoids spawning one process for every scheduled update.
    requests = "".join(f"{commit}:{feed_path}\n" for commit in commits).encode()
    blobs = io.BytesIO(git(repo, "cat-file", "--batch", input_data=requests))
    snapshots = []
    skipped = 0
    for commit in commits:
        header = blobs.readline().decode().split()
        if len(header) == 2 and header[1] == "missing":
            skipped += 1
            continue
        if len(header) != 3 or header[1] != "blob":
            raise ValueError("unexpected git cat-file response")
        raw = blobs.read(int(header[2]))
        if blobs.read(1) != b"\n":
            raise ValueError("truncated git cat-file response")
        try:
            snapshots.append(snapshot(raw))
        except (ValueError, UnicodeDecodeError) as error:
            print(f"Skipping invalid historical feed {commit}: {error}", file=sys.stderr)
            skipped += 1
    return snapshots, skipped


def valid_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def normalize_post(raw):
    if not isinstance(raw, dict):
        return None
    pid = raw.get("id")
    if isinstance(pid, bool) or not str(pid).isascii() or not str(pid).isdigit() or int(pid) < 1:
        return None
    post = dict(raw)
    post["id"] = int(pid)
    post["url"] = post.get("url") or f"{SOURCE}/{pid}"
    post["date_utc"] = post.get("date_utc") if valid_date(post.get("date_utc")) else None
    for key in ("text_ru", "text_en", "title_en", "translation_key"):
        if not isinstance(post.get(key), str):
            post[key] = ""
    if not isinstance(post.get("images"), list):
        post["images"] = []
    return post


def merge_posts(snapshots):
    posts = {}
    recovered_dates = set()
    skipped_posts = 0
    for data in snapshots:
        for raw in data["posts"]:
            older = normalize_post(raw)
            if older is None:
                skipped_posts += 1
                continue
            pid = older["id"]
            if pid not in posts:
                posts[pid] = older
                continue
            preferred = posts[pid]
            if not preferred["date_utc"] and older["date_utc"]:
                preferred["date_utc"] = older["date_utc"]
                recovered_dates.add(pid)
            if not nonempty(preferred["text_ru"]) and nonempty(older["text_ru"]):
                preferred["text_ru"] = older["text_ru"]
            # Never attach an older translation to a different edited original.
            if preferred["text_ru"] == older["text_ru"]:
                for key in ("text_en", "title_en"):
                    if not nonempty(preferred[key]) and nonempty(older[key]):
                        preferred[key] = older[key]
                        if key == "text_en":
                            preferred["translation_key"] = older["translation_key"]
    ordered = [posts[pid] for pid in sorted(posts, reverse=True)]
    for post in ordered:
        # Historical cache keys included CDN URLs; migrate without altering text.
        content = post["text_ru"] + "\n" + (post["date_utc"] or "")
        post["hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ordered, sorted(recovered_dates), skipped_posts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Local repository checkout; reads local main history only.")
    parser.add_argument("--out", type=Path, default=Path("archive.json"), help="Output path, relative to --repo unless absolute.")
    parser.add_argument("--feed", type=Path, default=Path("feed.json"), help="Current authoritative feed, relative to --repo unless absolute.")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        feed_path = args.feed if args.feed.is_absolute() else repo / args.feed
        output = args.out if args.out.is_absolute() else repo / args.out
        relative_feed = feed_path.resolve().relative_to(repo).as_posix()
        current = snapshot(feed_path.read_bytes())
        history, skipped = historical_snapshots(repo, relative_feed)
        posts, recovered_dates, skipped_posts = merge_posts([current, *history])
        if not posts:
            raise ValueError("no valid posts recovered; output was not changed")
        archive = {"channel": CHANNEL, "source": SOURCE, "posts": posts}
        rendered = json.dumps(archive, ensure_ascii=False, indent=2) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, output)
        dated = [post for post in posts if valid_date(post["date_utc"])]
        current_ids = {int(post["id"]) for post in current["posts"] if normalize_post(post) is not None}
        report = {
            "history_ref": "main",
            "history_commit": git(repo, "rev-parse", "main").decode().strip(),
            "valid_snapshots": len(history),
            "skipped_snapshots": skipped,
            "skipped_posts": skipped_posts,
            "current_posts": len(current_ids),
            "posts": len(posts),
            "recovered_posts": len({post["id"] for post in posts} - current_ids),
            "recovered_date_ids": recovered_dates,
            "undated_ids": sorted(post["id"] for post in posts if not post["date_utc"]),
            "oldest_post_date": min(dated, key=lambda p: valid_date(p["date_utc"]))["date_utc"] if dated else None,
            "latest_post_date": max(dated, key=lambda p: valid_date(p["date_utc"]))["date_utc"] if dated else None,
        }
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, UnicodeDecodeError) as error:
        print(f"Archive backfill failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
