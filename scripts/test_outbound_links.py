#!/usr/bin/env python3
"""Offline checks for static outbound campaign attribution."""
import importlib.util
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qsl, urlsplit
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
HELPER = SCRIPT_DIR / 'outbound_links.py'
module = None
if HELPER.exists():
    spec = importlib.util.spec_from_file_location('outbound_links', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class Parsed(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.anchors = []
        self.visible = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.anchors.append(dict(attrs))
    def handle_data(self, text):
        self.visible.append(text)


class OutboundAttributionTests(unittest.TestCase):
    def attributed(self, url):
        self.assertIsNotNone(module, 'the shared attribution helper must exist')
        return module.attribute_url(url)

    def html(self, text):
        self.assertIsNotNone(module, 'the shared attribution helper must exist')
        return module.attribute_html(text)

    def test_query_bytes_and_fragment_are_preserved_and_campaign_appended_once(self):
        original = 'https://example.com/path?x=a%2fb&blank=&x=two#section-2'
        expected = 'https://example.com/path?x=a%2fb&blank=&x=two&utm_source=darkolorin.com&utm_medium=referral&utm_campaign=personal_site#section-2'
        tagged = self.attributed(original)
        self.assertEqual(tagged, expected)
        self.assertEqual(self.attributed(tagged), tagged)
        self.assertEqual(sum(k == 'utm_source' for k, _ in parse_qsl(urlsplit(tagged).query)), 1)

    def test_existing_campaign_parameters_are_never_overwritten_or_mixed(self):
        for original in ['https://example.com/?utm_source=telegram#part',
                         'https://example.com/?x=1&utm_campaign=old&utm_medium=post',
                         'https://example.com/?UTM_SOURCE=legacy',
                         'https://example.com/?utm_source=']:
            with self.subTest(original=original):
                self.assertEqual(self.attributed(original), original)

    def test_internal_and_non_http_links_are_untouched(self):
        for original in ['essays.html', '../privacy.html', '#projects', 'rss.xml',
                         'https://darkolorin.com/posts/42.html', 'http://www.darkolorin.com/',
                         'https://sub.darkolorin.com/', 'mailto:hello@example.com',
                         'tel:+123', 'javascript:alert(1)', 'data:text/html,bad',
                         '//example.com/path']:
            with self.subTest(original=original):
                self.assertEqual(self.attributed(original), original)

    def test_signed_auth_and_obvious_download_links_remain_untouched(self):
        for original in ['https://files.example.com/a?X-Amz-Signature=abc',
                         'https://files.example.com/a?sig=abc#part',
                         'https://example.com/?token=private',
                         'https://example.com/?signature=abc',
                         'https://example.com/?hmac=abc&expires=123',
                         'https://example.com/?authkey=private',
                         'https://example.com/?jwt=private',
                         'https://example.com/?auth_token=private',
                         'https://example.com/?client_secret=private',
                         'https://example.com/?Key-Pair-Id=private&Policy=encoded',
                         'https://example.com/?credential=private&nonce=abc',
                         'https://example.com/?x-ms-signature=abc',
                         'https://example.com/file.dmg?version=3',
                         'https://example.com/paper.pdf',
                         'https://github.com/org/repo/releases/download/v1/app.zip',
                         'https://arxiv.org/pdf/2401.12345',
                         'https://example.com/download?file=example',
                         'https://user:pass@example.com/private']:
            with self.subTest(original=original):
                self.assertEqual(self.attributed(original), original)

    def test_only_anchor_hrefs_change_while_visible_labels_metadata_and_assets_stay(self):
        original = '''<!doctype html><html><head><link rel="canonical" href="https://darkolorin.com/">
<meta property="og:url" content="https://example.com/metadata">
<script src="https://example.com/script.js"></script></head><body>
<a href="https://example.com/page?x=1&amp;y=2#part" target="_blank" rel="nofollow noopener noreferrer ugc">https://example.com/page?x=1&amp;y=2#part</a>
<img src="https://example.com/image.jpg"><a href="essays.html">Essays</a>
<a href="mailto:hello@example.com">Email</a></body></html>'''
        changed = self.html(original)
        self.assertEqual(Parsed(original).visible, Parsed(changed).visible)
        external = Parsed(changed).anchors[0]
        self.assertEqual(external['href'], 'https://example.com/page?x=1&y=2&utm_source=darkolorin.com&utm_medium=referral&utm_campaign=personal_site#part')
        self.assertEqual(external['rel'].split(), ['nofollow', 'noopener', 'ugc'])
        self.assertIn('<img src="https://example.com/image.jpg">', changed)
        self.assertIn('<script src="https://example.com/script.js"></script>', changed)
        self.assertIn('<meta property="og:url" content="https://example.com/metadata">', changed)
        self.assertIn('rel="canonical" href="https://darkolorin.com/"', changed)
        self.assertEqual(self.html(changed), changed)

    def test_download_attribute_is_respected_and_noopener_retained_for_referrer_fallback(self):
        original = '<a href="https://example.com/binary?id=1" download rel="noopener noreferrer">Get file</a>'
        result = Parsed(self.html(original)).anchors[0]
        self.assertEqual(result['href'], 'https://example.com/binary?id=1')
        self.assertEqual(result['rel'], 'noopener')
        target = Parsed(self.html('<a target="_blank" href="https://example.com/">Example</a>')).anchors[0]
        self.assertIn('noopener', target['rel'].split())

    def test_attribute_names_inside_quoted_title_or_data_are_not_rewritten(self):
        original = '''<a title="Literal href='https://other.example/' rel='noreferrer'" data-note="href='keep'" href="https://example.com/" target="_blank" rel="noopener noreferrer">Example</a>'''
        before = Parsed(original).anchors[0]
        after = Parsed(self.html(original)).anchors[0]
        self.assertEqual(after['title'], before['title'])
        self.assertEqual(after['data-note'], before['data-note'])
        self.assertIn('utm_source=darkolorin.com', after['href'])
        self.assertEqual(after['rel'], 'noopener')

    def test_anchors_with_duplicate_attributes_are_left_entirely_unchanged(self):
        examples = [
            "<a href='https://example.com/private?token=secret' href='https://other.example/'>Example</a>",
            '<a href="https://example.com/" rel="noopener" rel="noreferrer">Example</a>',
            '<a href="https://example.com/" target="_self" TARGET="_blank">Example</a>',
            '<a href="https://example.com/" download download="file">Example</a>',
        ]
        for original in examples:
            with self.subTest(original=original):
                self.assertEqual(self.html(original), original)

    def test_builder_tags_rendered_links_and_rss_without_rewriting_source_text_or_permalinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = 'Read https://example.com/article?x=1#chapter and keep this exact visible text.'
            item = {'id': 42, 'url': 'https://t.me/chillhousetech/42', 'date_utc': '2025-01-01T12:00:00Z',
                    'text_en': text, 'text_ru': 'Исходный текст.', 'images': ['https://example.com/image.jpg']}
            data = {'channel': 'chillhousetech', 'source': 'https://t.me/chillhousetech', 'posts': [item]}
            feed = root / 'feed.json'
            archive = root / 'archive.json'
            source = json.dumps(data, ensure_ascii=False)
            feed.write_text(source)
            archive.write_text(source)
            before = feed.read_bytes()
            run = subprocess.run([sys.executable, str(SCRIPT_DIR / 'build_archive.py'), '--feed', str(feed),
                                  '--archive', str(archive), '--output-dir', str(root / 'site')], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(feed.read_bytes(), before)
            self.assertEqual(json.loads(archive.read_text())['posts'][0]['text_en'], text)
            page = (root / 'site/posts/42.html').read_text()
            self.assertIn('Read https://example.com/article?x=1#chapter', ''.join(Parsed(page).visible))
            normal = next(a['href'] for a in Parsed(page).anchors if a.get('href', '').startswith('https://example.com/article'))
            self.assertIn('utm_source=darkolorin.com', normal)
            self.assertNotIn('noreferrer', page)
            channel = ET.parse(root / 'site/rss.xml').find('channel')
            self.assertEqual(channel.findtext('item/guid'), 'https://darkolorin.com/posts/42.html')
            self.assertEqual(channel.findtext('item/link'), 'https://darkolorin.com/posts/42.html')
            description = channel.findtext('item/description')
            hrefs = [a['href'] for a in Parsed(description).anchors]
            self.assertTrue(all('utm_source=darkolorin.com' in href for href in hrefs))
            self.assertIn('<img src="https://example.com/image.jpg"', description)
            self.assertNotIn('utm_', (root / 'site/sitemap.xml').read_text())


if __name__ == '__main__':
    unittest.main()
