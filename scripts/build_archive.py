#!/usr/bin/env python3
"""Build the permanent HTML archive and RSS locally, using only existing feed data."""
import argparse
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

try:
    from .outbound_links import attribute_html
except ImportError:
    from outbound_links import attribute_html

BASE_URL = 'https://darkolorin.com'
OG_IMAGE = BASE_URL + '/assets/og-card.png'
OG_IMAGE_ALT = 'Alexey Moiseenkov, darkolorin.com'
ATOM_NS = 'http://www.w3.org/2005/Atom'
SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'
MEDIA_TITLES = {'photo': 'Photos', 'video': 'Video', 'document': 'Document',
                'poll': 'Poll', 'unsupported': 'Media on Telegram'}
URL_RE = re.compile(r'''\b((?:https?://|www\.)[^\s<>"']+|(?:t\.me|github\.com|x\.com|twitter\.com)/[^\s<>"']+)''', re.I)
STYLE = '''        body {
            max-width: 860px;
            margin: 24px auto;
            padding: 0 16px;
            line-height: 1.55;
            overflow-wrap: anywhere;
        }
        img { display: block; margin: 12px 0; max-width: 100%; height: auto; }
        hr { margin: 24px 0; }
        details { margin-top: 12px; }'''


def publication_date(value):
    """Only use real, timezone-aware source timestamps, never build time."""
    if not isinstance(value, str) or 'T' not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def post_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[1-9]\d*', value):
        return int(value)
    return None


def merge_posts(archived, fresh):
    merged = {}
    for record in [*archived, *fresh]:
        if not isinstance(record, dict) or post_id(record.get('id')) is None:
            continue
        pid = post_id(record['id'])
        previous = merged.get(pid, {})
        update = {**previous, **record, 'id': pid}
        has_translation = isinstance(record.get('text_en'), str) and bool(record['text_en'].strip())
        previous_translation = isinstance(previous.get('text_en'), str) and bool(previous['text_en'].strip())
        if previous_translation and not has_translation:
            # Keep a source and its cached translation together until the edit is translated.
            for key in ['text_ru', 'text_en', 'title_en', 'translation_key', 'hash']:
                if key in previous:
                    update[key] = previous[key]
                else:
                    update.pop(key, None)
        elif has_translation:
            for key in ['title_en', 'translation_key', 'hash']:
                if key not in record:
                    update.pop(key, None)
        if publication_date(record.get('date_utc')) is None:
            update['date_utc'] = previous.get('date_utc') if publication_date(previous.get('date_utc')) else None
        merged[pid] = update
    return [merged[pid] for pid in sorted(merged, reverse=True)]


def safe_url(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ['http', 'https'] and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def split_url_suffix(raw):
    url, suffix = raw, ''
    while url and url[-1] in '.,;:!?…':
        suffix = url[-1] + suffix
        url = url[:-1]
    for opener, closer in [('(', ')'), ('[', ']'), ('{', '}')]:
        while url.endswith(closer) and url.count(closer) > url.count(opener):
            suffix = closer + suffix
            url = url[:-1]
    return url, suffix


def linkify(text):
    result = []
    end = 0
    for match in URL_RE.finditer(text):
        result.append(escape(text[end:match.start()]))
        url, suffix = split_url_suffix(match.group(0))
        href = url if re.match(r'^https?://', url, re.I) else 'https://' + url
        if safe_url(href):
            result.append(f'<a href="{escape(href)}" rel="noopener noreferrer">{escape(url)}</a>')
        else:
            result.append(escape(url))
        result.append(escape(suffix))
        end = match.end()
    result.append(escape(text[end:]))
    return ''.join(result)


def render_text(value):
    text = value if isinstance(value, str) else ''
    blocks = []
    for block in re.split(r'\n\s*\n', text):
        if not block.strip():
            continue
        lines = block.strip().splitlines()
        if all(re.match(r'^\s*[-*•]\s+', line) for line in lines):
            items = [f'<li>{linkify(re.sub(r"^\s*[-*•]\s+", "", line))}</li>' for line in lines]
            blocks.append('<ul>\n' + '\n'.join(items) + '\n</ul>')
        else:
            blocks.append('<p>' + '<br>\n'.join(linkify(line) for line in lines) + '</p>')
    return '\n'.join(blocks)


def excerpt(post, limit=80, *, sentence=True):
    lines = [line for line in str(post.get('text_en') or '').splitlines()
             if line.strip() not in ['"""', "'''", '```']]
    opening = '\n'.join(lines).strip()
    if sentence:
        opening = re.split(r'\n\s*\n', opening, maxsplit=1)[0]
    has_urls = bool(URL_RE.search(opening))
    opening = URL_RE.sub(lambda match: split_url_suffix(match.group(0))[1], opening)
    opening = re.sub(r'\(\s*\)', '', opening)
    line = ' '.join(opening.split())
    line = re.sub(r'\s+([,.;:!?])', r'\1', line)
    if has_urls:
        line = line.lstrip('.,;:!?… ')
    if not line.strip('.,;:!?…()[]{}\'" -—–'):
        return MEDIA_TITLES.get(post.get('content_kind'), f"Post #{post['id']}")
    if sentence:
        terminator = re.search(r'[.!?](?=\s|$)', line)
        if terminator and terminator.end() <= limit:
            return line[:terminator.end()]
    if len(line) > limit:
        prefix = line[:limit - 1]
        boundary = prefix.rfind(' ')
        cut = prefix[:boundary] if boundary >= limit // 2 else prefix
        return cut.rstrip('.,;:') + '…'
    return line


def sorted_posts(posts):
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(posts, key=lambda p: (publication_date(p.get('date_utc')) or earliest, p['id']), reverse=True)


def post_path(post):
    return f"posts/{post['id']}.html"


def original_url(post, channel):
    return safe_url(post.get('url')) or f"https://t.me/{channel}/{post['id']}"


def image_html(post):
    images = post.get('images') if isinstance(post.get('images'), list) else []
    return '\n'.join(f'<img src="{escape(url)}" alt="" loading="lazy">' for value in images if (url := safe_url(value)))


def forwarded_html(post):
    forwarded = post.get('forwarded_from')
    if isinstance(forwarded, str):
        name, url = forwarded.strip(), None
    elif isinstance(forwarded, dict):
        name = forwarded.get('name') if isinstance(forwarded.get('name'), str) else ''
        url = safe_url(forwarded.get('url'))
    else:
        return ''
    if not name and not url:
        return ''
    label = escape(name or 'original source')
    if url:
        label = f'<a href="{escape(url)}">{label}</a>'
    return f'<p>Forwarded from {label}.</p>'


def media_notice_html(post, has_images):
    kind = post.get('content_kind')
    notices = {'video': 'View this video on Telegram.',
               'document': 'View this document on Telegram.',
               'unsupported': 'View this media on Telegram.',
               'service': 'Service message on Telegram.'}
    notice = notices.get(kind, '')
    if kind == 'photo' and not has_images:
        notice = 'View these photos on Telegram.'
    if kind == 'poll' and not str(post.get('text_en') or '').strip() and not str(post.get('text_ru') or '').strip():
        notice = 'View this poll on Telegram.'
    if not notice:
        return ''
    supplied = post.get('media_notice_en')
    return render_text(supplied if isinstance(supplied, str) and supplied.strip() else notice)


def original_link_key(url):
    parts = urlsplit(url)
    if parts.path == '/':
        slash = url.find('://') + 3 + len(parts.netloc)
        return url[:slash] + url[slash + 1:]
    return url


class EnglishAnchorTargets(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.targets = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for key, value in attrs:
                if key == 'href' and value:
                    self.targets.add(original_link_key(value))


def original_links_html(post, english):
    sources = post.get('source_links')
    if not isinstance(sources, list):
        return ''
    seen = EnglishAnchorTargets(english).targets
    items = []
    for source in sources:
        url = safe_url(source.get('url')) if isinstance(source, dict) else None
        if not url or original_link_key(url) in seen:
            continue
        seen.add(original_link_key(url))
        items.append(f'<li><a href="{escape(url)}" rel="noopener">{escape(url)}</a></li>')
    if not items:
        return ''
    return '<p>Links from the original post:</p>\n<ul>\n' + '\n'.join(items) + '\n</ul>'


def english_body_html(post):
    images = image_html(post)
    english = render_text(post.get('text_en'))
    if not english:
        has_original = isinstance(post.get('text_ru'), str) and bool(post['text_ru'].strip())
        media_only = post.get('content_kind') in {*MEDIA_TITLES, 'service'} and not has_original
        service_notice = post.get('content_kind') == 'service' and isinstance(post.get('media_notice_en'), str) and bool(post['media_notice_en'].strip())
        if not media_only and not service_notice:
            english = '<p>English translation is not available for this post.</p>'
    parts = [forwarded_html(post), images, english, original_links_html(post, english), media_notice_html(post, bool(images))]
    return '\n'.join(part for part in parts if part)


def page_head(title, description, path, *, article=False, image=None, published=None, prefix='', social_title=None, social_description=None):
    canonical = BASE_URL + '/' + path
    social_title = social_title or title
    social_description = social_description or description
    image_url = image or OG_IMAGE
    fallback_image_meta = '' if image else f'''    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:image:alt" content="{OG_IMAGE_ALT}">
'''
    twitter_image_alt = '' if image else f'    <meta name="twitter:image:alt" content="{OG_IMAGE_ALT}">\n'
    published_meta = f'    <meta property="article:published_time" content="{escape(published.isoformat())}">\n' if published else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(description)}">
    <link rel="canonical" href="{escape(canonical)}">
    <link rel="alternate" type="application/rss+xml" title="ChillHouse (English)" href="{prefix}rss.xml">
    <meta property="og:title" content="{escape(social_title)}">
    <meta property="og:description" content="{escape(social_description)}">
    <meta property="og:image" content="{escape(image_url)}">
{fallback_image_meta}    <meta property="og:url" content="{escape(canonical)}">
    <meta property="og:type" content="{'article' if article else 'website'}">
{published_meta}    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{escape(social_title)}">
    <meta name="twitter:description" content="{escape(social_description)}">
    <meta name="twitter:image" content="{escape(image_url)}">
{twitter_image_alt}    <meta name="twitter:site" content="@darkolorin">
    <meta name="twitter:creator" content="@darkolorin">
    <style>
{STYLE}
    </style>
    <script defer src="{prefix}analytics.js"></script>
</head>
<body>
'''


def navigation(prefix=''):
    essays = f'        <a href="{prefix}essays.html">Essays</a> |\n' if prefix else ''
    return f'''    <nav>
        <a href="{prefix}index.html">Home</a> |
        <a href="{prefix}index.html#projects">Projects</a> |
{essays}        <a href="{prefix}rss.xml">RSS</a> |
        <a href="https://t.me/chillhousetech" rel="noopener noreferrer">Telegram (RU)</a>
        <hr>
    </nav>
'''


def footer(prefix=''):
    return f'''    <footer>
        <p>&copy; 199X - 2026 Alexey Moiseenkov.</p>
        <p>
            <a href="{prefix}privacy.html">Privacy</a>
            <button type="button" data-analytics-settings hidden>Analytics settings</button>
        </p>
    </footer>
</body>
</html>
'''


def render_index(posts):
    result = [page_head('ChillHouse (English) - Essays',
                       "Selected writing by Alexey Moiseenkov and English translations of posts from his ChillHouse Telegram channel.",
                       'essays.html', social_title='ChillHouse (English) - Essays by Alexey Moiseenkov',
                       social_description='Selected writing and English translations from ChillHouse: thoughts on AI, technology, and on-device intelligence.')]
    result.append('''    <header>
        <h1>ChillHouse (English)</h1>
        <p>Auto-translated posts from <a href="https://t.me/chillhousetech" target="_blank" rel="noopener noreferrer">my Telegram channel</a>.</p>
        <hr>
    </header>
''')
    result.append(navigation())
    result.append('''    <main>
        <section id="writing">
            <h2>Selected writing</h2>
            <p>
                <a href="https://trymirai.com/blog/the-computer-should-know-the-way">The Computer Should Know the Way</a><br>
                My essay on intent, local assistants, and why computers should work out the steps for us.
            </p>
            <hr>
        </section>
        <section id="archive">
            <h2>Archive</h2>
''')
    result.append(f'            <p>{len(posts)} posts. <a href="rss.xml">Subscribe via RSS</a>.</p>\n')
    group = None
    for post in sorted_posts(posts):
        date = publication_date(post.get('date_utc'))
        year = str(date.year) if date else 'Undated'
        if year != group:
            if group is not None:
                result.append('            </ul>\n')
            result.append(f'            <h3>{year}</h3>\n            <ul>\n')
            group = year
        label = f'<time datetime="{escape(date.isoformat())}">{date.date().isoformat()}</time> ' if date else ''
        result.append(f'                <li>{label}<a href="{post_path(post)}">{escape(excerpt(post))}</a></li>\n')
    if group is not None:
        result.append('            </ul>\n')
    result.append('        </section>\n        <hr>\n    </main>\n')
    result.append(footer())
    return attribute_html(''.join(result))


def render_post(post, channel):
    title = excerpt(post)
    date = publication_date(post.get('date_utc'))
    images = post.get('images') if isinstance(post.get('images'), list) else []
    first_image = next((url for item in images if (url := safe_url(item))), None)
    result = [page_head(title + ' - ChillHouse', excerpt(post, 180, sentence=False), post_path(post),
                        article=True, image=first_image, published=date, prefix='../')]
    result.append(f'    <header>\n        <h1>{escape(title)}</h1>\n')
    meta = f'<time datetime="{escape(date.isoformat())}">{date.date().isoformat()}</time> · ' if date else ''
    result.append(f'        <p>{meta}<a href="{escape(original_url(post, channel))}">Original on Telegram</a></p>\n        <hr>\n    </header>\n')
    result.append(navigation('../'))
    result.append('    <main>\n        <article>\n')
    result.append(english_body_html(post))
    if isinstance(post.get('text_ru'), str) and post['text_ru'].strip():
        result.append('\n<details lang="ru">\n<summary lang="en">Original (RU)</summary>\n')
        result.append(render_text(post['text_ru']))
        result.append('\n</details>')
    result.append('\n        </article>\n        <hr>\n    </main>\n')
    result.append(footer('../'))
    return attribute_html(''.join(result))


def xml_text(root):
    ET.indent(root, space='    ')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True).decode('utf-8') + '\n'


def render_rss(posts, channel):
    ET.register_namespace('atom', ATOM_NS)
    rss = ET.Element('rss', version='2.0')
    feed = ET.SubElement(rss, 'channel')
    for tag, text in [('title', 'ChillHouse (English) - Alexey Moiseenkov'), ('link', BASE_URL + '/essays.html'),
                      ('description', 'English translations of posts from ChillHouse.'), ('language', 'en')]:
        ET.SubElement(feed, tag).text = text
    ET.SubElement(feed, '{' + ATOM_NS + '}link', href=BASE_URL + '/rss.xml', rel='self', type='application/rss+xml')
    # Telegram message IDs preserve source order even when a historical timestamp is missing.
    for post in sorted(posts, key=lambda post: post['id'], reverse=True):
        item = ET.SubElement(feed, 'item')
        permalink = BASE_URL + '/' + post_path(post)
        ET.SubElement(item, 'title').text = excerpt(post)
        ET.SubElement(item, 'link').text = permalink
        ET.SubElement(item, 'guid', isPermaLink='true').text = permalink
        date = publication_date(post.get('date_utc'))
        if date:
            ET.SubElement(item, 'pubDate').text = format_datetime(date, usegmt=True)
        body = english_body_html(post)
        body += f'\n<p><a href="{escape(original_url(post, channel))}">Original on Telegram</a></p>'
        ET.SubElement(item, 'description').text = attribute_html(body)
    return xml_text(rss)


def render_sitemap(posts):
    ET.register_namespace('', SITEMAP_NS)
    root = ET.Element('{' + SITEMAP_NS + '}urlset')
    for path in ['', 'essays.html', *[post_path(post) for post in sorted_posts(posts)]]:
        entry = ET.SubElement(root, '{' + SITEMAP_NS + '}url')
        ET.SubElement(entry, '{' + SITEMAP_NS + '}loc').text = BASE_URL + '/' + path
    # Publication time is not a reliable last-modified time; omit lastmod.
    return xml_text(root)


def write_if_changed(path, content):
    data = content.encode('utf-8')
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)
    return True


def load_data(path, missing=False):
    if missing and not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('posts'), list):
        raise ValueError(f'{path}: expected an object containing a posts array')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, default=Path('feed.json'))
    parser.add_argument('--archive', type=Path, default=Path('archive.json'))
    parser.add_argument('--output-dir', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    try:
        feed = load_data(args.feed)
        archive = load_data(args.archive, missing=True)
        channel = archive.get('channel') or feed.get('channel') or 'chillhousetech'
        if not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9_]{5,}', channel):
            raise ValueError('Invalid Telegram channel')
        if feed.get('channel', channel) != channel:
            raise ValueError('Feed and archive channels differ')
        posts = merge_posts(archive.get('posts', []), feed['posts'])
        if not posts:
            raise ValueError('No valid posts; existing generated output was not changed')
        data = {'channel': channel, 'source': f'https://t.me/{channel}', 'posts': posts}
        changed = int(write_if_changed(args.archive, json.dumps(data, ensure_ascii=False, indent=2) + '\n'))
        changed += int(write_if_changed(args.output_dir / 'essays.html', render_index(posts)))
        for post in posts:
            changed += int(write_if_changed(args.output_dir / post_path(post), render_post(post, channel)))
        changed += int(write_if_changed(args.output_dir / 'rss.xml', render_rss(posts, channel)))
        changed += int(write_if_changed(args.output_dir / 'sitemap.xml', render_sitemap(posts)))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    dated = sum(publication_date(post.get('date_utc')) is not None for post in posts)
    print(f'Built {len(posts)} permanent posts ({dated} dated, {len(posts) - dated} undated); {changed} files changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
