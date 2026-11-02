import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("backfill_archive.py")


class BackfillArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Archive test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True,
            capture_output=True, text=True,
        ).stdout

    def post(self, pid, *, text_en="Cached English", text_ru="Исходный текст", date="2026-01-01T12:00:00+00:00"):
        return {
            "id": pid,
            "url": f"https://t.me/chillhousetech/{pid}",
            "date_utc": date,
            "hash": "historical-hash",
            "translation_key": "openai:test:version",
            "text_ru": text_ru,
            "images": [],
            "title_en": "",
            "text_en": text_en,
        }

    def write_feed(self, posts):
        (self.repo / "feed.json").write_text(json.dumps({
            "channel": "chillhousetech",
            "source": "https://t.me/chillhousetech",
            "posts": posts,
        }, ensure_ascii=False), encoding="utf-8")

    def commit_feed(self, posts):
        self.write_feed(posts)
        self.git("add", "feed.json")
        self.git("commit", "-m", "Feed snapshot")

    def run_backfill(self):
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--repo", str(self.repo),
            "--out", "archive.json", "--feed", "feed.json",
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = json.loads((self.repo / "archive.json").read_text(encoding="utf-8"))
        return archive, json.loads(result.stdout)

    def test_keeps_all_unique_posts_and_current_feed_overrides_history(self):
        self.commit_feed([self.post(2), self.post(1)])
        self.commit_feed([self.post(3), self.post(2, text_en="Newer cached version")])
        self.write_feed([self.post(3, text_en="Current correction", text_ru="Текущий оригинал")])

        archive, report = self.run_backfill()

        self.assertEqual([p["id"] for p in archive["posts"]], [3, 2, 1])
        self.assertEqual(archive["posts"][0]["text_en"], "Current correction")
        self.assertEqual(archive["posts"][0]["text_ru"], "Текущий оригинал")
        self.assertEqual(archive["posts"][1]["text_en"], "Newer cached version")
        self.assertEqual(report["posts"], 3)
        self.assertEqual(report["recovered_posts"], 2)

    def test_recovers_only_proven_valid_date_for_same_post(self):
        known_date = "2025-12-02T10:11:12+00:00"
        self.commit_feed([self.post(1, date=known_date), self.post(2, date="invalid")])
        self.write_feed([self.post(2, date=None), self.post(1, date=None)])

        archive, report = self.run_backfill()
        posts = {p["id"]: p for p in archive["posts"]}

        self.assertEqual(posts[1]["date_utc"], known_date)
        self.assertIsNone(posts[2]["date_utc"])
        self.assertEqual(report["recovered_date_ids"], [1])
        self.assertEqual(report["undated_ids"], [2])

    def test_fills_empty_translation_only_when_original_text_matches(self):
        old = self.post(1)
        old["title_en"] = "Existing title"
        self.commit_feed([self.post(2), old])
        self.write_feed([
            self.post(2, text_en="", text_ru="Другой исходный текст"),
            self.post(1, text_en=""),
        ])

        archive, _ = self.run_backfill()
        posts = {p["id"]: p for p in archive["posts"]}

        self.assertEqual(posts[1]["text_en"], "Cached English")
        self.assertEqual(posts[1]["title_en"], "Existing title")
        self.assertEqual(posts[2]["text_ru"], "Другой исходный текст")
        self.assertEqual(posts[2]["text_en"], "")

    def test_skips_invalid_historical_json_without_losing_older_posts(self):
        self.commit_feed([self.post(1)])
        (self.repo / "feed.json").write_text("{broken", encoding="utf-8")
        self.git("add", "feed.json")
        self.git("commit", "-m", "Broken historical snapshot")
        self.write_feed([self.post(2)])

        archive, report = self.run_backfill()

        self.assertEqual([p["id"] for p in archive["posts"]], [2, 1])
        self.assertEqual(report["skipped_snapshots"], 1)

    def test_output_is_deterministic_without_build_timestamps(self):
        self.commit_feed([self.post(1)])
        self.run_backfill()
        first = (self.repo / "archive.json").read_bytes()

        self.run_backfill()

        self.assertEqual((self.repo / "archive.json").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
