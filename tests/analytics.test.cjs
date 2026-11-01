const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const scriptPath = path.join(__dirname, '..', 'analytics.js');
const source = fs.existsSync(scriptPath) ? fs.readFileSync(scriptPath, 'utf8') : '';
const id = 'G-TEST123456';

function browser(options = {}) {
    const elements = [];
    const deletedCookies = [];
    const listeners = {};
    const stored = new Map(options.consent ? [['darkolorin.analytics', options.consent]] : []);
    function element(tag) {
        const el = { tagName: tag.toUpperCase(), children: [], hidden: false, attributes: {}, listeners: {},
            appendChild(child) { this.children.push(child); return child; },
            setAttribute(name, value) { this.attributes[name] = value; },
            addEventListener(type, fn) { this.listeners[type] = fn; },
            click() { this.listeners.click?.({ defaultPrevented: false, button: 0, target: this }); },
        };
        elements.push(el);
        return el;
    }
    const settings = element('button');
    settings.hidden = true;
    const body = element('body');
    const head = element('head');
    const footer = element('footer');
    const document = {
        body, head, title: 'Alexey Moiseenkov', referrer: options.referrer || 'https://news.example/post?email=secret#private',
        querySelectorAll(selector) { return selector === '[data-analytics-settings]' ? [settings] : []; },
        querySelector(selector) { return selector === 'footer' ? footer : null; },
        createElement: element,
        addEventListener(type, fn) { listeners[type] = fn; },
        get cookie() { return '_ga=abc; _ga_TEST123456=def; unrelated=keep'; },
        set cookie(value) { deletedCookies.push(value); },
    };
    const location = new URL(options.url || 'https://darkolorin.com/essays.html?utm_source=telegram&utm_medium=post&utm_campaign=assistant&email=secret#private');
    const window = { addEventListener(type, fn) { listeners[type] = fn; } };
    const localStorage = {
        getItem(key) { if (options.storageBlocked) throw Error('blocked'); return stored.get(key) || null; },
        setItem(key, value) { if (options.storageBlocked) throw Error('blocked'); stored.set(key, value); },
    };
    const context = vm.createContext({ window, document, location, localStorage, URL, Date, queueMicrotask: fn => fn() });
    vm.runInContext(source.replace(/const MEASUREMENT_ID = "[^"]*";/, `const MEASUREMENT_ID = "${options.id === undefined ? id : options.id}";`), context);
    return {
        window, elements, head, footer, settings, stored, deletedCookies,
        button(label) { return elements.find(e => e.tagName === 'BUTTON' && e.textContent === label); },
        commands() { return (window.dataLayer || []).map(args => Array.from(args)); },
        storage(value, key = 'darkolorin.analytics') { listeners.storage?.({ key, newValue: value }); },
        clickLink(href, canceled = false) {
            const a = { href, closest(selector) { return selector === 'a[href]' ? this : null; } };
            listeners.click?.({ target: a, button: 0, defaultPrevented: canceled });
        },
    };
}

test('does not load Google or transmit events before a choice', () => {
    const b = browser();
    assert.ok(b.button('Accept analytics'), 'the optional analytics choice must be visible');
    assert.equal(b.head.children.length, 0);
    assert.equal(b.commands().length, 0);
    b.clickLink('https://trymirai.com/');
    assert.equal(b.commands().length, 0);
});

test('acceptance loads one tag and strips private query/hash while preserving campaign attribution', () => {
    const b = browser();
    b.button('Accept analytics')?.click();
    assert.equal(b.head.children.length, 1);
    assert.equal(b.head.children[0].src, `https://www.googletagmanager.com/gtag/js?id=${id}`);
    const config = b.commands().find(args => args[0] === 'config');
    assert.ok(config, 'acceptance configures Analytics');
    assert.equal(config[2].page_location, 'https://darkolorin.com/essays.html?utm_source=telegram&utm_medium=post&utm_campaign=assistant');
    assert.equal(config[2].page_referrer, 'https://news.example/post');
    assert.equal(config[2].allow_google_signals, false);
    assert.equal(config[2].allow_ad_personalization_signals, false);
    assert.equal(b.stored.get('darkolorin.analytics'), 'granted');
    const consent = b.commands().filter(args => args[0] === 'consent');
    assert.equal(consent[0][2].analytics_storage, 'denied');
    assert.equal(consent.at(-1)[2].analytics_storage, 'granted');
    assert.equal(consent.at(-1)[2].ad_storage, 'denied');
});

test('a saved refusal never loads Google; a saved grant starts the tag', () => {
    assert.equal(browser({ consent: 'denied' }).head.children.length, 0);
    assert.equal(browser({ consent: 'granted' }).head.children.length, 1);
});

test('reopening settings and accepting again does not duplicate the tag or page view', () => {
    const b = browser({ consent: 'granted' });
    b.settings.click();
    b.button('Accept analytics')?.click();
    assert.equal(b.head.children.length, 1);
    assert.equal(b.commands().filter(a => a[0] === 'config').length, 1);
});

test('withdrawal disables collection, deletes analytics cookies, and stops outbound events', () => {
    const b = browser({ consent: 'granted' });
    b.settings.click();
    b.button('No thanks')?.click();
    assert.equal(b.window[`ga-disable-${id}`], true);
    assert.equal(b.stored.get('darkolorin.analytics'), 'denied');
    assert.ok(b.deletedCookies.some(v => v.startsWith('_ga=') && v.includes('Max-Age=0')));
    assert.ok(b.deletedCookies.some(v => v.includes('Domain=darkolorin.com')));
    assert.ok(b.deletedCookies.some(v => v.startsWith('_ga_TEST123456=')));
    assert.ok(b.deletedCookies.every(v => !v.startsWith('unrelated=')));
    const before = b.commands().length;
    b.clickLink('https://trymirai.com/');
    assert.equal(b.commands().length, before);
});

test('blocked browser storage still allows a per-page choice', () => {
    const b = browser({ storageBlocked: true });
    b.button('Accept analytics')?.click();
    assert.equal(b.head.children.length, 1);
    b.settings.click();
    b.button('No thanks')?.click();
    assert.equal(b.window[`ga-disable-${id}`], true);
});

test('refusal in another tab stops collection in an already open page', () => {
    const b = browser({ consent: 'granted' });
    b.storage('denied');
    assert.equal(b.window[`ga-disable-${id}`], true);
    const before = b.commands().length;
    b.clickLink('https://trymirai.com/');
    assert.equal(b.commands().length, before);
    assert.equal(b.footer.children[0].hidden, true);
});

test('clearing the choice in another tab blocks collection until a new choice', () => {
    const b = browser({ consent: 'granted' });
    b.storage(null);
    assert.equal(b.window[`ga-disable-${id}`], true);
    assert.equal(b.footer.children[0].hidden, false);
    const before = b.commands().length;
    b.clickLink('https://trymirai.com/');
    assert.equal(b.commands().length, before);
    b.button('Accept analytics')?.click();
    assert.equal(b.window[`ga-disable-${id}`], false);
    assert.equal(b.head.children.length, 1);
});

test('outbound events use bounded labels without raw links or email addresses', () => {
    const b = browser({ consent: 'granted' });
    b.clickLink('https://trymirai.com/blog/the-computer-should-know-the-way?private=secret#fragment');
    b.clickLink('mailto:darkolorin+web@gmail.com?subject=secret');
    b.clickLink('https://darkolorin.com/essays.html');
    b.clickLink('https://trymirai.com/', true);
    const events = b.commands().filter(a => a[0] === 'event');
    assert.equal(events.length, 2);
    assert.equal(events[0][1], 'outbound_click');
    assert.equal(events[0][2].destination, 'mirai_blog');
    assert.equal(events[1][2].destination, 'email');
    assert.ok(!JSON.stringify(events).includes('secret'));
    assert.ok(!JSON.stringify(events).includes('@'));
});

test('invalid or email-shaped UTM values are dropped', () => {
    const b = browser({ consent: 'granted', url: 'https://darkolorin.com/?utm_source=person%40example.com&utm_medium=ok&utm_campaign=' + 'a'.repeat(101) });
    const config = b.commands().find(a => a[0] === 'config');
    assert.ok(config);
    assert.equal(config[2].page_location, 'https://darkolorin.com/?utm_medium=ok');
});

test('local, preview, and unconfigured sites remain inactive', () => {
    for (const options of [{ url: 'http://localhost:8000/' }, { url: 'https://preview.example/' }, { id: '' }]) {
        const b = browser({ ...options, consent: 'granted' });
        assert.equal(b.head.children.length, 0);
        assert.equal(b.settings.hidden, true);
        assert.equal(b.commands().length, 0);
    }
});
