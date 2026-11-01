import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
