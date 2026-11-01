# Personal website analytics implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect darkolorin.com to its own GA4 property, preserve plain HTML, and make current Mirai work easy to find.

**Architecture:** Keep the two static pages and existing Telegram feed. Load one shared, deferred analytics script that waits for an explicit analytics choice, records page views and outbound links, and offers a reversible choice. Use a separate GA4 property and web stream, without advertising features.

**Tech Stack:** HTML, vanilla JavaScript, GA4 Google tag, Node built-in test runner.

---

1. Create GA4 property and HTTPS web stream through the user's existing Chrome session; use Europe/London and GBP. Record the Measurement ID; stop for user action only if new binding terms are presented.
2. Add focused failing tests for no requests before consent, acceptance and saved choices, revoked consent, unavailable storage, and outbound event allowlists. Implement the shared script with no library or build step.
3. Update index.html and essays.html with metadata, canonical URLs, script references, and a small Selected writing area linking the verified Mirai article. Preserve existing author copy and feed content.
4. Add a plain privacy page and minimal robots.txt/sitemap.xml. Document GA4 reports and checks.
5. Run tests, check local links/metadata and desktop/mobile rendering, then review the patch independently.
6. Publish the authorized changes through GitHub, verify deployment and an explicit test visit in GA4. Check HTTP/HTTPS and www configuration separately, using existing host settings without DNS changes.
