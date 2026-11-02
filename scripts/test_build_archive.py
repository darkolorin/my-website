#!/usr/bin/env python3
"""Offline regression tests for the permanent, static Telegram archive."""
import json
from html import unescape
from pathlib import Path
import subprocess
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).with_name('build_archive.py')
BASE = 'https://darkolorin.com'


def post(pid, date='2025-04-02T12:30:00+00:00', text='An existing English opening.\n\nThe rest of the post.'):
    return {'id': pid, 'url': f'https://t.me/chillhousetech/{pid}', 'date_utc': date,
            'hash': str(pid), 'translation_key': 'existing', 'title_en': '',
            'text_en': text, 'text_ru': 'Оригинальный текст.', 'images': []}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.feed = self.root / 'feed.json'
        self.archive = self.root / 'archive.json'
        self.out = self.root / 'site'

    def write_data(self, path, posts, generated='2099-01-01T00:00:00Z'):
        data = {'channel': 'chillhousetech', 'source': 'https://t.me/chillhousetech', 'posts': posts}
        if path == self.feed:
            data['generated_at_utc'] = generated
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def run_builder(self):
        run = subprocess.run([sys.executable, str(SCRIPT), '--feed', str(self.feed),
                              '--archive', str(self.archive), '--output-dir', str(self.out)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def build(self, archived, fresh):
        self.write_data(self.archive, archived)
        self.write_data(self.feed, fresh)
        self.run_builder()

    def test_latest_window_does_not_delete_old_posts(self):
        self.build([post(1)], [post(2)])
        old = (self.out / 'posts/1.html').read_bytes()
        (self.out / 'posts/999.html').write_text('Existing old file', encoding='utf-8')
        self.write_data(self.feed, [post(3)])
        self.run_builder()
        ids = [p['id'] for p in json.loads(self.archive.read_text())['posts']]
        self.assertEqual(set(ids), {1, 2, 3})
        self.assertEqual((self.out / 'posts/1.html').read_bytes(), old)
        self.assertTrue((self.out / 'posts/2.html').exists())
        self.assertEqual((self.out / 'posts/999.html').read_text(), 'Existing old file')

    def test_untranslated_edit_keeps_last_complete_text_group_until_translation_arrives(self):
        original = post(7)
        original.update(title_en='Previous title', hash='old-hash', translation_key='old-model')
        fresh = dict(original, text_en='', title_en='', date_utc=None, text_ru='Новый оригинал.',
                     hash='new-hash', translation_key='none', images=['https://example.com/new.jpg'])
        self.build([original], [fresh])
        saved = json.loads(self.archive.read_text())['posts'][0]
        for key in ['text_ru', 'text_en', 'title_en', 'hash', 'translation_key']:
            self.assertEqual(saved[key], original[key])
        self.assertEqual(saved['date_utc'], original['date_utc'])
        self.assertEqual(saved['images'], fresh['images'])
        translated = dict(fresh, text_en='New translated text.', title_en='', translation_key='new-model')
        self.write_data(self.feed, [translated])
        self.run_builder()
        saved = json.loads(self.archive.read_text())['posts'][0]
        for key in ['text_ru', 'text_en', 'title_en', 'hash', 'translation_key']:
            self.assertEqual(saved[key], translated[key])

    def test_titles_use_existing_first_sentence_but_descriptions_keep_opening_context(self):
        text = 'Weekend thoughts. This is the following context, which belongs in the description and body.'
        self.build([], [post(30, text=text)])
        page = (self.out / 'posts/30.html').read_text()
        self.assertIn('<h1>Weekend thoughts.</h1>', page)
        description = unescape(re.search(r'<meta name="description" content="([^"]*)"', page).group(1))
        self.assertEqual(description, text)
        self.assertEqual(ET.parse(self.out / 'rss.xml').findtext('./channel/item/title'), 'Weekend thoughts.')

    def test_title_excerpt_does_not_include_the_appended_source_link_list(self):
        text = "Well that's\nnot bad\n\nLinks:\nhttps://example.com/original"
        self.build([], [post(33, text=text)])
        page = (self.out / 'posts/33.html').read_text()
        self.assertIn('<h1>Well that&#x27;s not bad</h1>', page)
        self.assertIn('https://example.com/original', page)

    def test_excerpt_fallback_is_at_most_eighty_characters_and_joins_existing_wrapped_lines(self):
        url_text = '"""\nhttps://example.com/' + 'a' * 160 + '\nExisting later context.'
        wrapped = 'An existing\nwrapped opening without a terminator that is deliberately long enough to need an excerpt but no new title.'
        self.build([], [post(31, text=url_text), post(32, text=wrapped)])
        for pid in [31, 32]:
            page = (self.out / f'posts/{pid}.html').read_text()
            heading = unescape(re.search(r'<h1>(.*?)</h1>', page).group(1))
            self.assertLessEqual(len(heading), 80)
            if pid == 32:
                self.assertTrue(heading.endswith('…'))
        self.assertIn('<h1>Existing later context.</h1>', (self.out / 'posts/31.html').read_text())
        self.assertIn('<h1>An existing wrapped opening', (self.out / 'posts/32.html').read_text())

    def test_derived_excerpts_omit_target_urls_and_empty_parentheses_but_body_is_unchanged(self):
        text = 'My name’s Alexey and I made Prisma, (https://en.wikipedia.org/wiki/Prisma_(app)) Capture and more.'
        entry = post(2, text=text)
        self.build([], [entry])
        page = (self.out / 'posts/2.html').read_text()
        heading = unescape(re.search(r'<h1>(.*?)</h1>', page).group(1))
        description = unescape(re.search(r'<meta name="description" content="([^"]*)"', page).group(1))
        self.assertEqual(heading, 'My name’s Alexey and I made Prisma, Capture and more.')
        self.assertEqual(description, heading)
        self.assertIn('>https://en.wikipedia.org/wiki/Prisma_(app)</a>)', page)
        self.assertEqual(json.loads(self.archive.read_text())['posts'][0]['text_en'], text)

    def test_url_only_post_has_neutral_derived_title_and_description(self):
        self.build([], [post(90, text='(https://example.com/a_(b)).')])
        page = (self.out / 'posts/90.html').read_text()
        self.assertIn('<h1>Post #90</h1>', page)
        self.assertIn('<meta name="description" content="Post #90">', page)
        self.assertIn('>https://example.com/a_(b)</a>).', page)

    def test_new_untranslated_post_has_no_invented_english_text(self):
        self.build([], [post(33, text='')])
        page = (self.out / 'posts/33.html').read_text()
        self.assertIn('<h1>Post #33</h1>', page)
        self.assertIn('English translation is not available', page)
        self.assertIn('Оригинальный текст.', page)

    def test_stable_permalink_and_guid_survive_changed_title_and_text(self):
        self.build([], [post(42, text='First existing opening.')])
        old_guid = ET.parse(self.out / 'rss.xml').findtext('./channel/item/guid')
        changed = post(42, text='Changed existing opening.')
        changed['title_en'] = 'A new imported title'
        self.write_data(self.feed, [changed])
        self.run_builder()
        self.assertEqual(ET.parse(self.out / 'rss.xml').findtext('./channel/item/guid'), old_guid)
        self.assertEqual(old_guid, BASE + '/posts/42.html')
        page = (self.out / 'posts/42.html').read_text()
        self.assertIn('Changed existing opening.', page)
        self.assertIn('rel="canonical" href="' + old_guid + '"', page)
        self.assertEqual([p.name for p in (self.out / 'posts').iterdir()], ['42.html'])

    def test_unknown_dates_are_undated_without_fabricated_publication(self):
        self.build([], [post(6, date=None), post(5, date='not-a-date')])
        listing = (self.out / 'essays.html').read_text()
        self.assertIn('<h3>Undated</h3>', listing)
        self.assertNotIn('2099', listing)
        for item in ET.parse(self.out / 'rss.xml').findall('./channel/item'):
            self.assertIsNone(item.find('pubDate'))
        for pid in [5, 6]:
            page = (self.out / f'posts/{pid}.html').read_text()
            self.assertNotIn('<time', page)
            self.assertNotIn('article:published_time', page)
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        self.assertEqual(ET.parse(self.out / 'sitemap.xml').findall('.//s:lastmod', ns), [])

    def test_html_and_unsafe_urls_are_escaped_without_changing_author_text(self):
        text = '"""\nExisting opening <script>alert("x")</script>.\n\nKeep A & B and 3 < 5.\n\n- One item\n- Two items\n\nSee https://example.com/a_(b)?x=1&y=2.\n\nNot a link: javascript:alert(1)'
        entry = post(10, text=text)
        entry['images'] = ['javascript:alert(1)', 'data:text/html,bad', 'https://example.com/image.jpg?x=1&y=2']
        entry['url'] = 'javascript:alert(2)'
        self.build([], [entry])
        page = (self.out / 'posts/10.html').read_text()
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;', page)
        self.assertIn('Keep A &amp; B and 3 &lt; 5.', page)
        self.assertIn('<ul>', page)
        self.assertIn('<li>One item</li>', page)
        self.assertIn('href="https://example.com/a_(b)?x=1&amp;y=2&amp;utm_source=darkolorin.com&amp;utm_medium=referral&amp;utm_campaign=personal_site"', page)
        self.assertNotIn('src="javascript:', page)
        self.assertNotIn('src="data:', page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn('href="https://t.me/chillhousetech/10?utm_source=darkolorin.com&amp;utm_medium=referral&amp;utm_campaign=personal_site"', page)
        self.assertIn('lang="ru"', page)
        self.assertIn('Оригинальный текст.', page)
        self.assertIn('<h1>Existing opening', page)

    def test_rss_contains_all_stored_posts_including_undated_with_stable_guids(self):
        entries = [post(i, date=f'2025-04-{(i % 28) + 1:02}T12:30:00+00:00', text=f'Existing post {i}.') for i in range(1, 53)]
        self.build([], entries + [post(999, date=None)])
        channel = ET.parse(self.out / 'rss.xml').getroot().find('channel')
        items = channel.findall('item')
        self.assertEqual(len(items), 53)
        self.assertEqual(len({item.findtext('guid') for item in items}), 53)
        self.assertTrue(all(item.findtext('guid').startswith(BASE + '/posts/') for item in items))
        self.assertTrue(all(item.findtext('guid') == item.findtext('link') for item in items))
        self.assertEqual(items[0].findtext('guid'), BASE + '/posts/999.html')
        self.assertIsNone(items[0].find('pubDate'))
        self.assertTrue(all(item.findtext('pubDate').endswith('GMT') for item in items[1:]))
        self.assertEqual([int(item.findtext('guid').rsplit('/', 1)[-1][:-5]) for item in items], [999, *range(52, 0, -1)])
        self.assertEqual(channel.find('{http://www.w3.org/2005/Atom}link').get('href'), BASE + '/rss.xml')
        self.assertIn('<p>Existing post', items[1].findtext('description'))
        self.assertNotIn('2099', (self.out / 'rss.xml').read_text())

    def test_empty_caption_media_posts_have_neutral_titles_without_translation_warning(self):
        titles = {'photo': 'Photos', 'video': 'Video', 'document': 'Document',
                  'unsupported': 'Media on Telegram', 'service': 'Post #104', 'poll': 'Poll'}
        records = []
        for pid, (kind, _) in enumerate(titles.items(), 100):
            entry = dict(post(pid, text=''), content_kind=kind, text_ru='')
            if kind == 'photo':
                entry['images'] = ['https://example.com/photo.jpg']
            records.append(entry)
        self.build([], records)
        for entry in records:
            page = (self.out / f'posts/{entry["id"]}.html').read_text()
            self.assertIn(f'<h1>{titles[entry["content_kind"]]}</h1>', page)
            self.assertNotIn('English translation is not available', page)
            if entry['content_kind'] == 'photo':
                self.assertIn('<img src="https://example.com/photo.jpg"', page)
                self.assertNotIn('View these photos on Telegram.', page)
            elif entry['content_kind'] == 'video':
                self.assertIn('View this video on Telegram.', page)
        for item in ET.parse(self.out / 'rss.xml').findall('./channel/item'):
            self.assertNotIn('English translation is not available', item.findtext('description'))

    def test_media_caption_without_translation_is_still_labelled_unavailable(self):
        entry = dict(post(110, text=''), content_kind='video')
        self.build([], [entry])
        page = (self.out / 'posts/110.html').read_text()
        self.assertIn('English translation is not available', page)
        self.assertIn('Оригинальный текст.', page)
        self.assertIn('View this video on Telegram.', page)

    def test_supplied_service_notice_and_poll_text_are_rendered_as_data(self):
        service = dict(post(1, text=''), content_kind='service', text_ru='Канал создан.',
                       media_notice_en='Channel created <on Telegram>.')
        poll = dict(post(2, text='An existing translated question?\n\n- First existing option\n- Second existing option'),
                    content_kind='poll')
        self.build([], [service, poll])
        page = (self.out / 'posts/1.html').read_text()
        self.assertIn('Channel created &lt;on Telegram&gt;.', page)
        self.assertNotIn('English translation is not available', page)
        poll_page = (self.out / 'posts/2.html').read_text()
        self.assertIn('<p>An existing translated question?</p>', poll_page)
        self.assertIn('<li>First existing option</li>', poll_page)
        self.assertIn('<li>Second existing option</li>', poll_page)

    def test_forward_attribution_is_preserved_escaped_and_linked_in_html_and_rss(self):
        entry = dict(post(120), forwarded_from={'name': 'A <channel> & author', 'url': 'https://t.me/sourcechannel/17'})
        self.build([], [entry])
        page = (self.out / 'posts/120.html').read_text()
        self.assertIn('Forwarded from', page)
        self.assertIn('A &lt;channel&gt; &amp; author</a>', page)
        self.assertIn('href="https://t.me/sourcechannel/17?utm_source=darkolorin.com&amp;utm_medium=referral&amp;utm_campaign=personal_site"', page)
        description = ET.parse(self.out / 'rss.xml').findtext('./channel/item/description')
        self.assertIn('Forwarded from', description)
        self.assertIn('A &lt;channel&gt; &amp; author</a>', description)
        self.assertEqual(json.loads(self.archive.read_text())['posts'][0]['text_en'], entry['text_en'])
        entry['forwarded_from']['url'] = 'javascript:alert(1)'
        self.write_data(self.feed, [entry])
        self.run_builder()
        unsafe = (self.out / 'posts/120.html').read_text()
        self.assertNotIn('href="javascript:', unsafe)
        self.assertIn('Forwarded from A &lt;channel&gt; &amp; author', unsafe)

    def test_missing_original_links_are_restored_in_html_and_rss_without_source_changes(self):
        url = 'https://example.com/read_(this)?x=1&y=2#section'
        entry = dict(post(130, text='A preserved English sentence with a linked word missing its target.'),
                     source_links=[{'text': 'оригинальная ссылка', 'url': url}])
        before = json.loads(json.dumps(entry, ensure_ascii=False))
        self.build([], [entry])
        page = (self.out / 'posts/130.html').read_text()
        expected = 'https://example.com/read_(this)?x=1&amp;y=2&amp;utm_source=darkolorin.com&amp;utm_medium=referral&amp;utm_campaign=personal_site#section'
        self.assertIn('Links from the original post:', page)
        self.assertIn(f'href="{expected}"', page)
        self.assertIn(f'>{url.replace("&", "&amp;")}</a>', page)
        description = ET.parse(self.out / 'rss.xml').findtext('./channel/item/description')
        self.assertIn('Links from the original post:', description)
        self.assertIn(f'href="{expected}"', description)
        self.assertEqual(json.loads(self.archive.read_text())['posts'][0], before)

    def test_original_links_already_in_english_are_not_repeated_and_missing_links_are_deduped(self):
        visible = 'https://example.com/a_(b)'
        missing = 'https://example.com/missing'
        entry = dict(post(131, text=f'Read {visible}.'), source_links=[
            {'text': 'existing', 'url': visible + '/'}, {'text': 'existing again', 'url': visible},
            {'text': 'missing', 'url': missing}, {'text': 'missing duplicate', 'url': missing}])
        self.build([], [entry])
        page = (self.out / 'posts/131.html').read_text()
        english = page.split('<details', 1)[0]
        hrefs = [unescape(value) for value in re.findall(r'<a href="([^"]+)"', english)]
        self.assertEqual(sum(href.startswith(visible) for href in hrefs), 2)
        self.assertEqual(sum(href.startswith(visible + '/') for href in hrefs), 1)
        self.assertEqual(sum(href.startswith(missing) for href in hrefs), 1)

    def test_original_link_dedup_normalizes_only_origin_root_slash_not_query_or_fragment(self):
        entry = dict(post(133, text='Read https://example.com?x=1#part.'), source_links=[
            {'url': 'https://example.com/?x=1#part'}])
        self.build([], [entry])
        page = (self.out / 'posts/133.html').read_text()
        self.assertNotIn('Links from the original post:', page)
        entry['source_links'].extend([{'url': 'https://example.com/?x=2#part'},
                                      {'url': 'https://example.com/?x=1#other'}])
        self.write_data(self.feed, [entry])
        self.run_builder()
        page = (self.out / 'posts/133.html').read_text()
        self.assertIn('href="https://example.com/?x=2&amp;', page)
        self.assertIn('#other"', page)

    def test_unsafe_original_links_are_skipped_without_empty_link_section(self):
        entry = dict(post(132), source_links=[{'url': 'javascript:alert(1)'}, {'url': 'data:text/html,bad'},
                                              {'url': 'https://user:pass@example.com/'}, {'url': None}, None])
        self.build([], [entry])
        page = (self.out / 'posts/132.html').read_text()
        self.assertNotIn('Links from the original post:', page)
        self.assertNotIn('href="javascript:', page)
        self.assertNotIn('href="data:', page)

    def test_pages_are_static_and_internal_integration_links_resolve(self):
        self.build([], [post(77, text='An English post without a runtime fetch.')])
        listing = (self.out / 'essays.html').read_text()
        page = (self.out / 'posts/77.html').read_text()
        self.assertIn('href="posts/77.html"', listing)
        self.assertNotIn('fetch(', listing)
        self.assertNotIn('Loading…', listing)
        self.assertIn('The Computer Should Know the Way', listing)
        self.assertIn('href="index.html#projects"', listing)
        self.assertIn('href="rss.xml"', listing)
        self.assertIn('application/rss+xml', listing)
        self.assertIn('src="../analytics.js"', page)
        self.assertIn('href="../privacy.html"', page)
        self.assertIn('data-analytics-settings', page)
        self.assertIn('og:type" content="article"', page)
        self.assertIn('article:published_time', page)
        self.assertIn('<time datetime="2025-04-02T12:30:00+00:00">2025-04-02</time>', page)
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [el.text for el in ET.parse(self.out / 'sitemap.xml').findall('.//s:loc', ns)]
        self.assertIn(BASE + '/posts/77.html', urls)
        self.assertIn(BASE + '/', urls)
        self.assertIn(BASE + '/essays.html', urls)

    def test_rebuilding_unchanged_content_preserves_bytes_and_mtimes(self):
        self.build([], [post(88)])
        files = [self.archive, *self.out.rglob('*')]
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in files if p.is_file()}
        self.write_data(self.feed, [post(88)], generated='2100-02-03T00:00:00Z')
        self.run_builder()
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in files if p.is_file()}
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
