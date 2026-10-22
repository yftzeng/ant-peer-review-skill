# D-0001 Fetch fallback order: retries, browser, AMP, archive, paste

| | |
|---|---|
| Status | accepted |
| Decided | 2026-10-22 |
| Features | source-acquisition |
| Glossary term | |
| Authority | user, 2026-10-22: "好" / "同意" to the proposed order and to porting it from ant-pr-review |
| Guard | tests/test_fallback.py (S-source-acquisition-024..031); tests/test_sources.py (N-source-acquisition-002) |
| Migration | |
| Related | ant-pr-review D-PR-15 (the same order, first built there); DESIGN.md D-16 (pinned crawler) |

## Decision

When a fetch fails or reads as thin, sources are tried in this order:
1. The honest-UA crawler, with bounded retries on 429/502/503/504 (Retry-After honoured, capped at 30 s, within the total deadline).
2. A headless browser (Playwright, optional extra `render`), only for thin or empty JS-rendered pages or `needs_js` site profiles. Every request the browser makes passes the crawler's address check.
3. The page's AMP version, then the newest Wayback Machine snapshot, labelled with its date in the sources table.
4. The user pastes the text, or passes a saved file.

robots.txt, a site-profile block, internal addresses and a login or paywall never fall back. A refusal the site makes to us (HTTP 403 or a bot challenge) uses the archive only when the user agrees: interactively they are told the archive date and choose; a non-interactive run needs `--archive-on-block`. A soft 404, 5xx and network errors use the archive automatically. A challenge never uses the browser.

Revised 2026-10-22 (user): 403 and challenges first used the archive automatically; that routed around a refusal the user had not seen. A site-profile User-Agent must still name ant-peer-review.

## Why not the alternative

curl-impersonate, or a browser User-Agent or TLS fingerprint: its only use is getting past a site's refusal. A headless browser solving a bot challenge is the same evasion. An archive copy of a robots-denied or paywalled page routes around the refusal it would honour.

## Deliberately not done

- No DNS pinning inside the browser: it resolves names itself after our check (a rebinding window), and WebSockets are not routed through the check (DESIGN §11).
- No automatic login or cookie import for paywalled pages: the user's own saved copy is the path.

## Why a new record

no decision covers what to do when a fetch fails or is blocked; DESIGN D-1..D-16 are about crawling safely, not about recovering
