# Universal Web Connector field guide

## Purpose

A saved connector describes how to read repeated message-like objects from a rendered web page. It is not a platform-specific API integration. It contains a URL, repeated message root selector, field selectors, navigation strategy and deduplication behavior.

## Normal setup

1. Create or open a saved connector in Inputs & Connectors → Web application collectors.
2. Enter the authenticated web application URL (the page where you sign in), not a public share/channel link. Put a public or canonical channel URL in `channel.target_url`; the connector's top-level `url` is the application entrypoint. The channel name is only a human-readable fallback. These are three different values. Known presets can migrate older rows where the public Eitaa URL was mistakenly stored as the app URL.
3. Open the connector's local browser profile. Session persistence is configurable per connector and defaults to on. The profile is keyed by workflow + connector, survives normal browser/app restarts, and is never exported with connector JSON. The user signs in only when the website requires it.
4. Inspect one message and the surrounding list containing multiple repeated messages. Use the visible Click select toolbar, right-click selection menu (including nearest repeated item), or browser DevTools to copy outerHTML; do not require Alt+click.
5. Map the repeated message root and fields: text (required), sender, timestamp, message ID, attachments (optional).
6. Validate root count and field coverage against multiple message samples. Prefer semantic attributes such as datetime, data-message-id and stable hrefs over visible text where available.
7. Configure navigation only from observed DOM evidence: manual, scroll container, infinite scroll, load-more or pagination. Per-connector controls include explicit scroll-container/action/previous/next selectors, direction, viewport-ratio or fixed-pixel step, adaptive/fixed wait, min/max wait, DOM quiet period, maximum idle cycles, maximum navigation cycles and timestamp timezone. Do not invent a selector or claim pagination works without observing page progress.
8. Start with adaptive waits. If a scroll produces no DOM/message change, the collector consumes the full wait budget and progressively increases it up to the configured maximum. When content changes and the DOM becomes quiet, it can continue earlier. Inspect per-cycle wait and mutation diagnostics before changing values. Fixed mode is available for sites with deterministic timing.
8. Save, capture a small visible sample, inspect the resulting inbox counts, then run a date-bounded collection.

## Automatic date-range navigation and selector coverage

A date-range request is a request to traverse relevant history, not merely filter whatever happens to be visible. `navigation.date_range_mode=auto` is the default: if the saved strategy is `manual`, the collector promotes that run to message-aware adaptive scrolling. Visible-only tests remain manual. Set `date_range_mode=manual` only when the operator deliberately wants currently loaded messages and accepts that history boundaries will remain unverified.

For a simple `tag.class1.class2` root selector, the collector may relax one trailing class when the broadened candidates all contain the configured non-empty text field and include every exact match. This handles volatile state/spacing classes without baking a site-specific selector into the application. The result reports the configured selector, effective selector, and both counts. Review the diagnostic before saving the broader selector permanently.

A URL fragment or username in the address bar alone is not proof that a conversation is open. Active identity is corroborated by visible message elements and a non-generic conversation title or active ID/handle evidence outside the sidebar. If the exact configured target route is active and the configured message-root selector finds visible message elements, that route-plus-message-DOM combination can verify the target even when the application exposes no readable header title. A generic title such as `جستجو` still blocks verification. Scroll diagnostics distinguish actual scroll movement from message growth; if no message-linked scroll container can be identified, the collector stops rather than scrolling an unrelated page pane.

Generic date-range results are complete only when the collector actually navigated and settled at the history edges (or observed timestamps on both sides of the requested interval). Human-readable timestamp `title` values are interpreted in the configured timezone. If either boundary is still unknown, the result remains explicitly partial.

## Channel identity and target resolution

Keep the authenticated application entry URL separate from the canonical/public channel URL and the channel identity. A connector stores the authenticated app URL in its top-level `url`, and can additionally store:

- `channel.target_url`: the canonical/public or direct conversation URL, when the platform exposes one. It is not necessarily the browser launch URL.
- `channel.username`: a stable username or handle.
- `channel.platform_id`: a platform-specific peer, room, thread or conversation ID.
- `channel.name`: a human-readable display name used as a fallback search query.
- `channel.identity_selector` + `channel.identity_attribute`: optional CSS evidence for verifying the active conversation header.
- `channel.search_input_selector` and `channel.search_result_selector`: optional selectors for site-specific search UI.

Resolve identity in this order: (1) check whether the already-open page matches a saved username, platform ID, direct URL or configured active-identity element; (2) if it does not, navigate to the configured direct target URL; (3) use username/platform ID to choose exactly one matching search result; (4) use the display name only when it produces one unambiguous result. Do not search again when the open page already matches a stable identity. Never treat a search result in a sidebar as proof that its conversation is open. After navigation or click, verify the active page again before capturing.

Search-result identity evidence should be read from the candidate row and its descendants (for example, a platform-specific `data-peer-id` attribute or username-bearing link), not inferred from the visible title alone. If duplicate names remain and no configured stable identity distinguishes them, stop and ask the operator to configure/confirm the intended target. Never open an arbitrary candidate.

A direct target URL is an operator-configured navigation destination and must be a valid HTTP(S) URL without embedded credentials. Use only a URL the operator supplied or verified. Do not infer platform IDs or usernames from untrusted page text.

## Date handling

Use the site's exact timestamp attribute when present (`time[datetime]`, data timestamp or equivalent). Normalize offset-aware timestamps explicitly. A visible date label is a fallback, not a substitute for an ISO timestamp when one exists. Date-range completeness requires observing a boundary or exhausting the relevant history; merely filtering loaded posts is not proof of complete collection.

## Browser-session persistence

Each connector has its own Chromium user-data directory under the workflow's local collector data folder. `session.persist=true` is the default; it keeps cookies, local storage, IndexedDB, session storage and site data after a normal close. `session.persist=false` uses a temporary profile deleted when the browser closes. The status panel reports the profile path and metadata (file size, cookie, local-storage, IndexedDB and session-storage presence), never cookie values or credentials. A cookie database only proves that browser storage exists; a website can still expire or revoke an account session. If the profile metadata disappears after a close/restart, check that the connector ID and workflow were not recreated and that persistence remains enabled. Do not delete or reset the profile as a first troubleshooting step.

A successful capture inserts source messages into the workflow `messages` table via the shared ingestion path. It reports added, queued, filtered and duplicate counts. A connector capture does not automatically create extraction `records` unless extraction is separately run. Verify the connector's inbox counts and then inspect the workflow Inbox. After extraction, verify record counts separately.

## Security and reliability

Keep authentication local in the persistent browser profile. Do not send cookies or credentials to the model. HTML samples may contain private content; obtain explicit consent before sending them to the configured model. Keep browser actions bounded and verify state after every navigation action.
