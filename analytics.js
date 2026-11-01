(() => {
    "use strict";

    // This is a public Google tag ID, not a secret.
    const MEASUREMENT_ID = "G-0J904NRELR";
    if (!/^G-[A-Z0-9]+$/.test(MEASUREMENT_ID) ||
        location.hostname !== "darkolorin.com" || location.protocol !== "https:") return;

    const storageKey = "darkolorin.analytics";
    const disableKey = "ga-disable-" + MEASUREMENT_ID;
    const denied = {
        analytics_storage: "denied",
        ad_storage: "denied",
        ad_user_data: "denied",
        ad_personalization: "denied"
    };
    let choice = "";
    let started = false;
    try { choice = localStorage.getItem(storageKey) || ""; } catch (_) { /* Per-page choice still works. */ }

    function gtag() {
        window.dataLayer = window.dataLayer || [];
        window.dataLayer.push(arguments);
    }

    function pageLocation() {
        const clean = new URL(location.origin + location.pathname);
        const current = new URL(location.href);
        for (const key of ["utm_source", "utm_medium", "utm_campaign"]) {
            const value = current.searchParams.get(key);
            if (value && /^[a-zA-Z0-9._~-]{1,100}$/.test(value)) clean.searchParams.set(key, value);
        }
        return clean.href;
    }

    function pageReferrer() {
        try {
            const url = new URL(document.referrer);
            return /^https?:$/.test(url.protocol) ? url.origin + url.pathname : "";
        } catch (_) { return ""; }
    }

    function start() {
        window[disableKey] = false;
        if (started) {
            gtag("consent", "update", { ...denied, analytics_storage: "granted" });
            return;
        }
        started = true;
        window.gtag = gtag;
        gtag("consent", "default", denied);
        gtag("consent", "update", { ...denied, analytics_storage: "granted" });
        gtag("js", new Date());
        gtag("config", MEASUREMENT_ID, {
            page_location: pageLocation(),
            page_referrer: pageReferrer(),
            allow_google_signals: false,
            allow_ad_personalization_signals: false,
            cookie_flags: "SameSite=Lax;Secure"
        });
        const script = document.createElement("script");
        script.async = true;
        script.src = "https://www.googletagmanager.com/gtag/js?id=" + MEASUREMENT_ID;
        document.head.appendChild(script);
    }

    function stop() {
        window[disableKey] = true;
        if (started) gtag("consent", "update", denied);
        const paths = new Set(["/"]);
        const segments = location.pathname.split("/");
        for (let i = 1; i < segments.length; i++) paths.add(segments.slice(0, i).join("/") + "/");
        for (const cookie of document.cookie.split(";")) {
            const name = cookie.split("=", 1)[0].trim();
            if (name !== "_ga" && !name.startsWith("_ga_")) continue;
            for (const path of paths) {
                for (const domain of ["", "darkolorin.com", ".darkolorin.com"]) {
                    document.cookie = name + "=; Max-Age=0; Path=" + path +
                        (domain ? "; Domain=" + domain : "") + "; SameSite=Lax; Secure";
                }
            }
        }
    }

    const panel = document.createElement("section");
    panel.setAttribute("aria-label", "Optional analytics");
    const explanation = document.createElement("p");
    explanation.textContent = "May I use Google Analytics to understand visits, traffic sources, and popular pages? It's optional. ";
    const privacy = document.createElement("a");
    privacy.href = "privacy.html";
    privacy.textContent = "Privacy details";
    explanation.appendChild(privacy);
    panel.appendChild(explanation);

    function choose(value) {
        choice = value;
        try { localStorage.setItem(storageKey, choice); } catch (_) { /* No persistent storage available. */ }
        if (choice === "granted") start(); else stop();
        panel.hidden = true;
    }

    for (const [label, value] of [["Accept analytics", "granted"], ["No thanks", "denied"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.addEventListener("click", () => choose(value));
        panel.appendChild(button);
    }
    const main = document.querySelector("main");
    if (main) main.before(panel);
    else (document.querySelector("footer") || document.body).appendChild(panel);
    for (const button of document.querySelectorAll("[data-analytics-settings]")) {
        button.hidden = false;
        button.addEventListener("click", () => { panel.hidden = false; });
    }
    panel.hidden = choice === "granted" || choice === "denied";
    if (choice === "granted") start();
    else if (choice === "denied") stop();

    window.addEventListener("storage", event => {
        if (event.key !== storageKey && event.key !== null) return;
        choice = event.newValue === "granted" || event.newValue === "denied" ? event.newValue : "";
        if (choice === "granted") start(); else stop();
        panel.hidden = choice !== "";
    });

    function destination(href) {
        try {
            const url = new URL(href, location.href);
            if (url.protocol === "mailto:") return "email";
            if (!/^https?:$/.test(url.protocol) || url.hostname === location.hostname) return "";
            if (url.hostname === "trymirai.com" || url.hostname === "www.trymirai.com") {
                return url.pathname.startsWith("/blog/") ? "mirai_blog" : "mirai";
            }
            const hosts = {
                "docs.trymirai.com": "mirai_docs", "intents.trymirai.com": "mirai_intents",
                "x.com": "twitter", "twitter.com": "twitter", "t.me": "telegram",
                "linkedin.com": "linkedin", "www.linkedin.com": "linkedin", "github.com": "github"
            };
            return hosts[url.hostname] || "other_external";
        } catch (_) { return ""; }
    }

    document.addEventListener("click", event => {
        const anchor = event.target.closest?.("a[href]");
        if (!anchor || event.button !== 0) return;
        // Check cancellation after all click handlers have had a chance to run.
        queueMicrotask(() => {
            if (choice !== "granted" || event.defaultPrevented) return;
            const label = destination(anchor.href);
            if (label) gtag("event", "outbound_click", { destination: label, transport_type: "beacon" });
        });
    });
})();
