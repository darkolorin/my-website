import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

import update_telegram_feed as feed


class ExtractTextTests(unittest.TestCase):
    def extract(self, html):
        message = BeautifulSoup(
            '<div class="tgme_widget_message_text">' + html + '</div>',
            "html.parser",
        )
        return feed.extract_text_ru(message)

    def test_keeps_destination_of_nested_anchor(self):
        text = self.extract(
            'Read <a href="https://trymirai.com/?source=blog&amp;medium=post">'
            '<strong>Mirai</strong> guide</a>.'
        )

        self.assertIn("Mirai guide", text)
        self.assertIn("https://trymirai.com/?source=blog&medium=post", text)

    def test_decodes_double_escaped_query_separators(self):
        text = self.extract(
            '<a href="https://intents.trymirai.com/?utm_source=chillhouse'
            '&amp;amp;utm_medium=post&amp;amp;utm_campaign=tg_my">Link</a>'
        )

        url = text.removeprefix("Link (").removesuffix(")")
        self.assertEqual(parse_qs(urlsplit(url).query), {
            "utm_source": ["chillhouse"],
            "utm_medium": ["post"],
            "utm_campaign": ["tg_my"],
        })
        self.assertNotIn("&amp;", text)

    def test_does_not_duplicate_visible_absolute_url(self):
        url = "https://trymirai.com/"
        text = self.extract('<a href="' + url + '">' + url + '</a>')

        self.assertEqual(text, url)

    def test_schemeless_url_label_becomes_one_clickable_url(self):
        text = self.extract(
            '<a href="https://www.trymirai.com/">www.trymirai.com/</a>'
        )

        self.assertEqual(text, "https://www.trymirai.com/")

    def test_does_not_duplicate_url_label_without_trailing_slash(self):
        text = self.extract(
            '<a href="https://trymirai.com/">https://trymirai.com</a>'
        )

        self.assertEqual(text, "https://trymirai.com")

    def test_ignores_non_http_destinations(self):
        for url in ("javascript:alert(1)", "data:text/html,test", "//example.com", "https:///missing-host"):
            with self.subTest(url=url):
                self.assertEqual(self.extract('<a href="' + url + '">Read</a>'), "Read")


class EmptyPreviewTests(unittest.TestCase):
    def test_empty_preview_fails_without_overwriting_existing_feed(self):
        old_feed = '{"posts": [{"id": 123, "text_en": "Existing post"}]}\n'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feed.json"
            output.write_text(old_feed, encoding="utf-8")
            error = io.StringIO()
            with patch.object(feed, "http_get", return_value="<html><body>Unavailable</body></html>"), \
                    contextlib.redirect_stderr(error), contextlib.redirect_stdout(io.StringIO()):
                result = feed.main(["--out", str(output), "--translator", "none"])

            self.assertNotEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), old_feed)
            self.assertFalse(Path(str(output) + ".tmp").exists())
            self.assertIn("No posts", error.getvalue())


class TranslationCacheTests(unittest.TestCase):
    def setUp(self):
        self.post = feed.TgPost(
            channel="chillhousetech",
            message_id=123,
            url="https://t.me/chillhousetech/123",
            date_utc="2026-11-01T20:00:00Z",
            text_ru="Привет, мир!",
            images=["https://cdn.example.com/original.jpg"],
        )

    def build(self, post, existing):
        return feed.build_feed(
            channel="chillhousetech",
            posts=[post],
            existing_feed=existing,
            translator="openai",
            openai_model="test-model",
            timeout_s=20,
        )

    def cached_feed(self):
        with patch.object(feed, "translate_and_format_ru_to_en_openai", return_value=("Cached title", "Cached English")):
            return self.build(self.post, {})

    def test_rotating_image_url_keeps_cached_translation(self):
        cached = self.cached_feed()
        rotated = replace(self.post, images=["https://cdn.example.com/rotated.jpg"])

        with patch.object(feed, "translate_and_format_ru_to_en_openai", side_effect=AssertionError("Unexpected translation request")):
            result = self.build(rotated, cached)

        self.assertEqual(result["posts"][0]["text_en"], "Cached English")
        self.assertEqual(result["posts"][0]["title_en"], "Cached title")
        self.assertEqual(result["posts"][0]["images"], rotated.images)

    def test_changed_text_invalidates_cached_translation(self):
        cached = self.cached_feed()
        changed = replace(self.post, text_ru="Обновленный текст.")

        with patch.object(feed, "translate_and_format_ru_to_en_openai", return_value=("New title", "New English")) as translate:
            result = self.build(changed, cached)

        translate.assert_called_once_with(text_ru=changed.text_ru, model="test-model", timeout_s=20)
        self.assertEqual(result["posts"][0]["text_en"], "New English")
        self.assertEqual(result["posts"][0]["title_en"], "New title")


if __name__ == "__main__":
    unittest.main()
