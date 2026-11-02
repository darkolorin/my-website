#!/usr/bin/env python3
"""Add campaign attribution to rendered external anchor URLs, without JavaScript."""
import argparse
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit

CAMPAIGN_QUERY = 'utm_source=darkolorin.com&utm_medium=referral&utm_campaign=personal_site'
AUTH_KEYS = {'signature', 'sig', 'hmac', 'token', 'access_token', 'auth', 'authkey', 'jwt',
             'auth_token', 'authorization', 'api_key', 'apikey', 'client_secret',
             'key-pair-id', 'credential', 'expires', 'nonce', 'policy'}
DOWNLOAD_SUFFIX = re.compile(r'\.(?:zip|tar|gz|bz2|xz|7z|dmg|pkg|exe|msi|pdf|epub|whl)$', re.I)
ATTRIBUTE_RE = re.compile(r'''(?P<name>[^\s=<>/'"]+)(?:\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+)))?''')


def is_external_url(url):
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
        return bool(parts.scheme.lower() in {'http', 'https'} and host and
                    host != 'darkolorin.com' and not host.endswith('.darkolorin.com') and
                    not parts.username and not parts.password)
    except ValueError:
        return False


def attribute_url(url):
    """Keep existing campaigns, signed URLs, downloads, and local links intact."""
    if not is_external_url(url):
        return url
    parts = urlsplit(url)
    keys = {key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if any(key.startswith('utm_') for key in keys):
        return url
    if keys & AUTH_KEYS or any(key.startswith(('x-amz-', 'x-goog-', 'x-ms-')) for key in keys):
        return url
    path = unquote(parts.path).lower()
    if DOWNLOAD_SUFFIX.search(path) or re.search(r'/(?:download|pdf)(?:/|$)', path) or '/resolve/' in path:
        return url
    base, fragment_marker, fragment = url.partition('#')
    separator = '?' if '?' not in base else '' if base.endswith(('?', '&')) else '&'
    return base + separator + CAMPAIGN_QUERY + fragment_marker + fragment


def find_attribute(tag, name):
    start = re.match(r'<\s*[^\s/>]+', tag)
    for match in ATTRIBUTE_RE.finditer(tag, start.end() if start else 0):
        if match.group('name').lower() == name.lower():
            return match
    return None


def replace_attribute(tag, name, value):
    match = find_attribute(tag, name)
    encoded = escape(value, quote=True)
    if match:
        group = next((group for group in ['double', 'single', 'bare'] if match.group(group) is not None), None)
        if group:
            return tag[:match.start(group)] + encoded + tag[match.end(group):]
        return tag[:match.start()] + f'{name}="{encoded}"' + tag[match.end():]
    close = tag.rfind('/>') if tag.endswith('/>') else tag.rfind('>')
    return tag[:close] + f' {name}="{encoded}"' + tag[close:]


class AnchorAttribution(HTMLParser):
    """Patch only start-tag attributes; preserve all author text and other markup."""
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.offsets = [0, *[match.end() for match in re.finditer('\n', text)]]
        self.patches = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'a':
            return
        names = [name.lower() for name, _ in attrs]
        if len(set(names)) != len(names):
            return  # Browsers and dict() disagree about which duplicate attribute wins.
        attributes = dict(attrs)
        href = attributes.get('href')
        if not is_external_url(href):
            return
        original = self.get_starttag_text()
        changed = original
        tagged = href if 'download' in attributes else attribute_url(href)
        if tagged != href:
            changed = replace_attribute(changed, 'href', tagged)
        rel = (attributes.get('rel') or '').split()
        cleaned = [part for part in rel if part.lower() != 'noreferrer']
        if (attributes.get('target') or '').lower() == '_blank' or cleaned != rel:
            if not any(part.lower() == 'noopener' for part in cleaned):
                cleaned.append('noopener')
        if cleaned != rel:
            changed = replace_attribute(changed, 'rel', ' '.join(cleaned))
        if changed != original:
            line, column = self.getpos()
            start = self.offsets[line - 1] + column
            self.patches.append((start, start + len(original), changed))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def attribute_html(text):
    parser = AnchorAttribution(text)
    parser.feed(text)
    parser.close()
    for start, end, replacement in reversed(parser.patches):
        text = text[:start] + replacement + text[end:]
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path, help='Static HTML files to update in place')
    args = parser.parse_args(argv)
    changed = 0
    for path in args.files:
        before = path.read_text(encoding='utf-8')
        after = attribute_html(before)
        if after != before:
            path.write_text(after, encoding='utf-8')
            changed += 1
    print(f'Updated {changed} HTML files.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
