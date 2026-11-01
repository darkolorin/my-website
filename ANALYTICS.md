# Website analytics

The website uses a shared `analytics.js` file, with no package or build step.
Its public `MEASUREMENT_ID` is `G-0J904NRELR`; the GA4 web stream ID is `16250583133`.
An empty `MEASUREMENT_ID` disables the integration.
It runs only on `https://darkolorin.com`; local development and other hosts do not send visits.

The dedicated Google Analytics account ID is `414342821`, and the property ID is `561820412`.
[Open this GA4 property](https://analytics.google.com/analytics/web/#/a414342821p561820412).

## Collection

- A small, plain HTML choice appears in the footer. The Google tag is not loaded before acceptance.
- Acceptance is stored as `darkolorin.analytics=granted` in local storage; refusal is stored as `denied`.
- “Analytics settings” reopens the choice. Refusal disables further GA collection and removes `_ga` / `_ga_*` cookies.
- Changes in another open tab are applied immediately. Clearing the saved choice stops collection and asks again.
- Storage failures leave a per-page choice, without breaking the website.
- Google signals and ad personalization are disabled; all advertising consent types remain denied.
- One Google tag configuration sends the page view. Reopening settings does not send another page view.
- `outbound_click` contains only a `destination` label (`mirai`, `mirai_blog`, `mirai_docs`, `mirai_intents`, `telegram`, `twitter`, `linkedin`, `github`, `email`, or `other_external`).
- Page addresses preserve only valid, bounded `utm_source`, `utm_medium`, and `utm_campaign` labels. Other query parameters and all fragments are removed; referrers omit query parameters and fragments. Do not put personal data in campaign labels.

Disable **Enhanced measurement** on the GA4 web stream. The website already sends page views and a limited outbound event. Automatic outbound clicks, form tracking, or site search could otherwise send extra URL/form metadata and duplicate click events.

## Useful GA4 reports

- **Reports → Realtime:** confirm an accepted test visit is received.
- **Acquisition → Traffic acquisition:** session source/medium, referrers, and campaign labels.
- **Engagement → Pages and screens:** popular pages and engagement.
- **User attributes → Demographic details:** approximate country/city; small samples may be withheld.
- **Tech → Tech details:** browser/device breakdown.
- **Engagement → Events:** `outbound_click` count. To break down its categories in reports/explorations, register an event-scoped custom dimension with event parameter `destination` (display name “Outbound destination”).

Analytics describes browsers and visits; it does not identify individual people by name. Refused visits and blocked tags are absent from these reports. Standard reports are processed asynchronously; Realtime is the first collection check.

## Verification

Run `node --test tests/analytics.test.cjs` for consent, URL sanitization, revocation, storage failure, and outbound behavior checks.

On the deployed site, clear the analytics choice or use a fresh browser context. Before choosing, confirm there are no requests to Google Analytics/Tag Manager. Accept, confirm a Google tag and collection request, visit a second page, then follow a Mirai link. Check the accepted page view and `outbound_click` in GA4 Realtime. Reopen settings and choose “No thanks”; verify further link clicks do not collect and GA cookies are removed. A successful deployment alone does not prove GA4 has received events.
