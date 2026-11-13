# Changelog

## 1.8.37
- Enforced one built-in source and one configured channel per collection run.
- Centralized the release number in the root `VERSION` file; the sidebar badge, static asset cache keys, diagnostics metadata, and health endpoint now use the same value.
- Replaced source-identifying regression fixture values with synthetic test identities and kept repository examples fictional and platform-neutral.
- Removed the combined Telegram + Rubika run option.
- Replaced built-in Telegram and Rubika automated channel search/click flows with explicit operator channel selection in the open browser.
- Custom web connector collection now captures the operator-selected active page instead of resolving or navigating to configured channel URLs.
- Preserved active-chat verification, history positioning confirmation and date-range scanning.

## 1.8.33 — Telegram active-chat identity and extraction preflight

- Tightened active-chat title discovery to dedicated conversation-header nodes. Broad `header [dir=auto]` and generic title candidates could include stale search/sidebar content and falsely certify a different active chat.
- The displayed active title is now taken from the primary active-pane heading, never substituted with another candidate that happens to match the clicked search row.
- Rechecks the selected Telegram peer ID throughout the history scan, not only at the initial readiness checkpoint.
- Expanded Telegram message-body discovery for `.text-content`, `.message-content`, `.content-inner`, `.bubble-content`, and media captions.
- Added an extraction preflight before history scrolling. If readiness sees message containers but the actual body extractor sees zero messages, collection stops immediately and records bounded DOM diagnostics rather than scrolling unrelated/undetected history and falsely confirming a date boundary.
- Added regression tests for wrong active headers, title-source isolation, peer-ID continuity, body selector coverage and preflight-before-scroll behavior.

## 1.8.31 — Telegram sign-in false-positive correction

- Fixed a Telegram readiness-check false positive: an unscoped `canvas` element was treated as proof that Telegram had returned to its QR sign-in screen. Telegram Web can render ordinary interface/media elements with canvas, including after a channel was successfully selected.
- Sign-in detection now requires an explicit QR/phone login control or `.auth-form`, and confirms the authenticated chat shell is not visible before reporting a session loss.
- If an actual sign-in view is detected, the error now records the matched login indicator, current URL and page title to make the diagnosis auditable.
- Added regression tests for ordinary canvas elements, explicit login UI, stale auth markup and the authenticated sidebar.

## 1.8.30 — Adaptive source agent and evidence-based browser actions

- Added a source-neutral browser observer that reports visible controls, repeated DOM candidates, scroll containers, page identity and bounded content evidence without reading input values, cookies or browser storage.
- Added a strict browser action vocabulary (`click`, `fill`, `press`, `scroll`, `wait`) with bounded inputs, credential-free URL validation, and before/after evidence snapshots.
- Added a one-step LLM browser planner to the saved web connector inspector. It requires explicit consent before sending the visible page snapshot to the configured model, grounds selectors in the observed DOM, restricts text entry and Enter to visible search inputs, rejects consequential controls, and prohibits autonomous navigation and destructive/account actions.
- Added live page inspection and an adaptive next-step control to the connector workbench. The operator can inspect the result after every action and decide whether to continue.
- Fixed Telegram search-result activation to use a real Playwright mouse pointer sequence rather than synthetic `HTMLElement.click()`, which can bypass delegated pointer/ripple handlers.
- Telegram result discovery now recognizes `.chatlist-chat[data-peer-id]`; active-channel confirmation can use matching peer identity in the active chat header, not only visible message text.
- Broadened Telegram message discovery to include message bubbles and stable message IDs within the active conversation region.
- Preserved the source-neutral acquisition contracts and legacy connectors; this is an incremental migration, not a claim that every website or protected app is universally accessible.

## 1.8.29 — Source-neutral acquisition foundation


- Added a common source contract for browser pages, files, text, HTTP, APIs, and databases. Captured items carry source identity, item identity, content type, timestamps, author, attachments, metadata and a deterministic content fingerprint.
- Added an adapter registry that routes by source kind rather than branching on platform names.
- Added generic text and TXT/CSV/JSON/JSONL adapters with bounded, resumable capture and provenance-preserving row identifiers.
- Added a generic rendered-browser adapter that inspects live DOM evidence, proposes repeated-item candidates and refuses to capture until an item selector is explicitly validated. It contains no Telegram/Rubika/Eitaa-specific selectors or navigation assumptions.
- Added a conservative source planner that separates inspection/planning from execution and makes sign-in, identity confirmation, completeness and access limitations explicit.
- Added `docs/SOURCE_AGENT_ARCHITECTURE.md` describing the source-neutral pipeline, reliability invariants and staged migration from legacy platform collectors.
- This is the first migration foundation, not a claim that all legacy collection screens have already been replaced. Existing databases, browser profiles, connectors and collection settings remain unchanged.

Verification: source-core tests and the existing full suite are recorded in BUILD_INFO.txt.

## 1.8.28 — Telegram search syntax and inbox re-import protection

- Fixed the missing closing parenthesis in the Telegram search-result JavaScript evaluated by Playwright. This was the direct cause of the `Page.evaluate: SyntaxError` after entering the channel search.
- Kept the manual channel-selection fallback for cases where the result list cannot be matched safely.
- Restricted inbox imports to the platform(s) selected for the current run, even though daily combined archive files may contain previous captures from other platforms.
- Collection status now distinguishes current-run channel captures from the combined daily archive.
- Clearing pending/all inbox messages writes durable fingerprint suppressions, preventing preserved source archives from reintroducing deleted messages into the workflow.

## 1.8.27 — Telegram result selection and reliable connector picking

- Telegram now searches by the configured username/ID inside the authenticated Telegram Web app, evaluates visible matching result rows instead of assuming one fixed DOM selector, and clicks only a row matching the requested identity. If the client layout hides the handle or the automatic click cannot be confirmed, the browser stays open and the collector waits for one explicit operator click rather than closing immediately. It then checks the opened chat header/message list and asks for confirmation when the row/header evidence is incomplete.
- Telegram verification now distinguishes the authenticated `web.telegram.org` app host from the public `t.me` channel URL. The public URL remains identity metadata; its host mismatch is no longer incorrectly reported as a wrong-site navigation.
- Connector visual picking now receives an explicit server acknowledgement with a selection revision. The browser only reports a saved selection after the application confirms it. Guided picks update both the selector input and the JSON draft preview, with input/change events dispatched.
- Fixed the inspector polling lifecycle when opening an existing connector. The picker now restarts its status poll when the editor is reopened, keeps polling while a browser session is already ready, and reads the current selection revision before arming a new pick. This prevents a click from being stored in the browser session without updating the visible settings.
- Collection status now identifies the source-level counts behind its combined total and uses platform-neutral selection guidance for both Telegram and Rubika. A mixed run will no longer make Rubika captures look like Telegram captures.

Verification: full suite 287 passed, 8 skipped (295 tests total); focused Telegram/collector/inspector/UI suite 101 passed. Python compilation, main app JavaScript and all four embedded browser scripts passed syntax checks. Live authenticated Telegram and user-session picker behavior still require local validation.

## 1.8.26 — RTL chat, universal diagnostics, reliable visual picking and authenticated Telegram navigation

- Agent chat now chooses paragraph direction from Unicode script content. Persian/Arabic messages use an RTL base direction; English identifiers, inline code and fenced snippets are isolated LTR runs.
- Added a global System Diagnostics drawer accessible from every workspace. It collects client errors, unhandled promise rejections, browser console errors, failed API calls, collector state/logs, active runs and custom connector inspector selection state. It provides a copyable support bundle while excluding cookies, credentials, browser storage contents, raw message bodies and model prompts.
- Guided visual picker now clears stale selections, tracks a monotonic per-session selection revision, awaits the browser-to-app binding and displays selection success/failure feedback. The web UI detects new selections by revision, not by comparing browser and app clocks.
- Dashboard-only zoom is set to 130%; other workspace tabs retain their normal scale.
- Review Desk number shortcuts immediately open the selected field for replacement. Saving updates the current in-memory record, refreshes the queue while preserving its ID and redraws the live review pane.
- Telegram collection always opens Telegram Web first, checks the authenticated session and searches for the channel inside the app. A configured `t.me/<username>` link is treated as channel identity metadata, not as the browser's initial destination.

Verification: full suite 302 passed, 8 skipped, 3 subtests passed; focused browser/collector/review/UI suite 94 passed; Python compileall and JavaScript syntax checks passed. Live authenticated Telegram/Rubika sessions still require local validation.

## 1.8.25 — AI context, extraction control, inline review editing and connector learning examples

- Agent chat now selects only the application tools relevant to the user's intent. Explanatory questions do not receive mutation tools; diagnostic questions receive inspection tools; explicit changes expose the matching update tool.
- Reduced the default chat context footprint by compacting the system guidance, limiting retrieved knowledge and history, bounding tool results and sending compact workflow metadata. On context overflow, the request retries with less history/knowledge and a shorter user input while preserving the latest question and any active tool-call/result exchange.
- Agent instructions now distinguish source collection, collection-policy filtering, rules-only fallback parsing, deterministic post-processing, AI-only extraction and the separate automatic-extraction-after-collection setting. Prompt presence is no longer treated as proof that the prompt is correct.
- Added workflow extraction modes: `ai_only`, `ai_plus_rules` and `rules_only`. AI-only passes the original raw source text to the LLM and bypasses preprocessing, domain guardrails and workflow transformation rules. It requires an enabled model.
- Automatic batch extraction after collection is now opt-in, defaults off for existing and new workflows, and persists as a per-workflow preference. Collection therefore leaves source messages queued in Inbox unless the user explicitly enables post-capture extraction.
- Replaced the Review Desk's external-editor handoff for E with an inline numbered field editor. Operators can jump to a field with number keys, navigate with arrows, replace the value, validate scalar/boolean/JSON types, save with S or cancel with Escape/Q.
- Added Telegram and Rubika connector blueprint panels with actual reference entry URLs, message-root/text/timestamp selectors and identity indicators to teach users how to map a custom website connector.
- Removed the user-facing “native connector” terminology in favor of platform examples/connectors.

## 1.8.24 — Bidirectional date-boundary scrolling

- Date-range collection now verifies the newer/end boundary first when it has not already been crossed by a timestamp, then traverses in the configured older direction. This covers messengers that open the active conversation at an intermediate scroll position.
- Newer and older phases each have their own navigation budget (bounded by the connector's Maximum navigation cycles per direction setting).
- Navigation diagnostics include phase and direction for each step, plus stop reasons for both boundaries.
- Collection summary labels duplicates as records already present, distinguishing them from newly captured rows.

Verification: full suite ran 279 tests (271 passed, 8 skipped); focused connector, browser and sandbox-runtime suite passed 28/28, including eight real Chromium/Playwright DOM tests. Python compilation and JavaScript syntax validation passed. The bidirectional date-range fixture reached the newest edge, reversed toward older history, triggered dynamic loading without resizing the browser, and verified both boundaries. Live authenticated Eitaa testing remains necessary.

## 1.8.23 — Universal upward scrolling fallback and actual Chromium sandboxing

- Fixed the live Eitaa Web failure where the collector correctly captured the five currently loaded messages but never scrolled to load older history. The saved connector was using the old pagination strategy, while the authenticated single-page client exposes a virtualized scroll pane and no `data-before` page link.
- Date-range pagination now falls back to the shared message-aware scroll engine when there is no usable older-page link (or no previous-page selector is configured). The fallback issues observable upward scroll steps against the actual scrollable ancestor of the selected message roots, repeatedly rescans newly loaded DOM, normalizes timestamps in the connector timezone, and stops only after crossing the requested start date, confirming the older-history edge, hitting a configured cap, or detecting a stall.
- A stale saved scroll selector is no longer fatal: it is validated for existence, message containment and scroll overflow, then replaced with universal scroll-ancestor inference when invalid. The document is never scrolled merely because a selector failed.
- Navigation diagnostics now identify the selected scroller, whether the saved selector was found/usable, whether fallback was used, the actual scrollTop movement, and whether new roots were discovered on each cycle.
- Fixed the Chromium warning at its real source. Playwright defaults `chromium_sandbox=False` and automatically injects `--no-sandbox`; the shared browser runtime now explicitly passes `chromium_sandbox=True` for the web inspector, Telegram and Rubika collectors. The shared launcher also rejects root execution, not only the web inspector.
- Added regression tests for pagination-to-scroll fallback, stale scroll selector recovery, dynamic older-message loading in Chromium, Playwright sandbox options, and root-launch rejection.
- Existing workflow databases, messages, connector configuration, browser profiles and `.venv` are excluded from the update package and are preserved.

Verification: full suite 284 passed, 7 skipped, 3 subtests passed (two existing FastAPI lifespan deprecation warnings); focused browser/collector suite 53/53 passed; Python compileall, app JavaScript and all four embedded browser scripts passed syntax checks. Real Chromium launched through the shared runtime as an unprivileged user with sandbox enabled and no --no-sandbox argument in its process command line. A Chromium fixture verified that upward scrolling triggers dynamic loading of older messages. Live authenticated Eitaa validation is still required.

## 1.8.22 — Main-conversation root ranking, Jalali timestamps and sandbox enforcement

- Fixed a false-positive discovery path exposed by real testing: repeated chat-list/sidebar rows and navigation controls could outrank the actual message history. Candidates inside chat lists, navigation menus, folder bars, contact lists and similar UI chrome are now excluded before message-root ranking; main-conversation context is weighted positively.
- Structural sibling discovery now runs alongside semantic discovery instead of only when no semantic group exists. This allows messengers with generated CSS-module classes to be discovered even when unrelated repeated UI controls are present.
- Date-like timestamp extraction now rejects time-only/sidebar preview labels and surfaces sample timestamps, candidate evidence, ancestor context and scrollable page regions in diagnostics.
- Timestamp normalization now handles Persian/Arabic-Indic digits, numeric Jalali dates, Persian month names, Unix epoch timestamps, Gregorian slash dates, ISO-8601 and RFC-style dates using the connector timezone.
- The web inspector no longer explicitly adds `--no-sandbox`, and root execution is rejected there. A later integration test found Playwright was still injecting the flag because `chromium_sandbox` remained at its default false; 1.8.23 fixes this in the shared browser launcher for all collectors.
- Added Chromium fixtures proving sidebar chat previews are excluded while repeated message blocks in the active conversation are selected, and added Jalali timestamp and root-execution regression tests.
- Existing workflow data, connector configuration, databases, browser profiles and `.venv` remain excluded from the update package and are preserved.

Verification: full suite ran 272 tests (266 passed, 6 skipped); focused connector suite passed 33/33 tests including six real Chromium/Playwright fixtures. Python compilation, app JavaScript syntax, all four embedded browser-script syntax checks and clean ZIP extraction/integrity passed. Live authenticated Eitaa validation is still required.

## 1.8.21 — Shared universal message discovery for scrolling and pagination

- Fixed a collector architecture split: regular capture and date-range pagination previously used different DOM-root discovery logic. Both now call the same platform-neutral discovery engine, so a connector no longer loses its selector recovery when it enters date-range scanning.
- The shared engine prioritizes the user's visual selector mapping, then safely attempts recovery using repeated semantic message blocks, common body descendants, stable message identifiers, timestamp metadata, sender metadata and repeated sibling structure. It does not depend on an Eitaa-only class list.
- When a saved root or text selector is stale, diagnostics report the effective mode, selected roots, selector match/non-empty counts, repeated candidate groups, timestamp/sender mapping counts and a small sanitized DOM sample. No cookies, storage values or session tokens are exposed.
- Date-pagination navigation waits for the page body rather than waiting on a possibly stale message selector. A no-root result now carries DOM discovery diagnostics instead of only reporting `no_message_roots`.
- The UI exposes an expandable automatic DOM-discovery diagnostic panel, including candidate roots that can be selected for connector mapping.
- Existing connector settings, workflow data, databases, browser profiles and collected messages are preserved.

Verification: 279 automated tests passed, 5 browser-integration tests passed when run directly with real Playwright and system Chromium (the full suite skips those five when another test has installed a Playwright stub), Python compilation passed, app JavaScript and all four embedded browser scripts passed syntax validation. Chromium fixtures covered Eitaa-like markup, semantic message wrappers and generated-class structural fallback. Live authenticated Eitaa collection still requires testing in the user's existing browser session.

## 1.8.20 — Universal DOM recovery and Chromium launch hardening

- Message-root discovery now recognizes repeated block-level message wrappers and common message-body descendants without depending exclusively on a previously saved text selector.
- Stale simple selectors can safely broaden optional classes while retaining all exact matches; a unique repeated candidate can be used as a fallback only when it contains at least two non-empty message bodies. The effective selector and recovery mode are reported.
- Active message diagnostics can detect known repeated message wrappers independently of the saved root selector. Exact peer ID plus the requested non-generic title on the configured in-app route can verify a conversation even when the app's header wrapper is unfamiliar.
- Removed Chromium's `--no-sandbox` argument for non-root launches; it is added only for root execution.
- CSP syntax warnings emitted by the website are treated as external page diagnostics, not collector errors.
- Existing settings, databases, browser profiles and collected data are preserved.

Verification: 279 automated tests passed; Python compilation, app JavaScript syntax, all four embedded browser-script syntax checks and ZIP integrity passed. Chromium fixture test using the supplied Eitaa message structure verified the channel and captured five messages; stale selector fallback expanded a partial match to all five. Live authenticated Eitaa testing remains outstanding.

## 1.8.20 — Guided visual selector mapping and header-first identity verification

- Added guided Pick buttons for message root, text, timestamp, sender, message ID and attachments directly in the connector setup steps. A pick button arms the existing browser inspector; the next element click automatically fills the corresponding CSS selector and attribute mapping.
- Promoted visual picking to the primary Step 2 of connector setup; selector review is Step 3. Manual HTML copy/paste and AI-assisted mapping are now an explicitly optional fallback, so a normal setup no longer requires copying outerHTML.
- The inspector now derives reusable repeated-container selectors instead of relying only on a unique DOM path. Field selectors are calculated relative to the repeated message root across multiple sibling samples, accommodating volatile state classes such as optional spacing modifiers.
- Collection identity can now be verified by an exact platform ID in the active conversation header plus an exact non-generic conversation title, independently of message-selector mapping. A missing root selector no longer disguises a verified conversation as an identity failure.
- When configured message roots match zero elements or contain no readable message text, collection stops before scrolling and reports generic candidate selectors with match counts. Candidate roots can be applied directly from the collection diagnostics.
- Deduplicated repeated platform IDs in identity diagnostics. Existing connector settings, databases and browser profiles are preserved.

## 1.8.18 — Public link / authenticated app URL separation

- Fixed legacy Eitaa connectors that stored `https://eitaa.com/<channel>` as the browser application's launch URL. The connector now launches the authenticated web client at `https://web.eitaa.com/` and preserves the public channel URL separately as `channel.target_url`.
- New Eitaa connector drafts created with a public Eitaa channel URL are normalized into the two-URL model at save time. Existing legacy database rows are migrated safely on connector read, preserving browser profile directories and session data.
- The shared route resolver now has a compatibility fallback: when an old Eitaa connector still supplies a public Eitaa origin, its default route resolves against the authenticated web client instead of returning the public URL.
- Eitaa usernames are derived from unambiguous public path/fragment handles; numeric archive/message paths are not mistaken for usernames.
- Clarified the connector builder: Website URL means the authenticated web application entrypoint; Direct channel URL means the canonical/public destination.
- Added regression coverage for new-draft normalization, legacy-row migration, URL routing, and API capture receiving the correct app URL.

## 1.8.17 — In-app route templates and safe inspector bootstrap

- Fixed the DOM inspector initialization race: Playwright may execute init scripts before `document.documentElement` exists. The inspector now observes the `Document` until the root element is available, then attaches its UI without passing a null value to `MutationObserver.observe()`.
- Separated canonical/public conversation URLs from the route used inside the authenticated web application. Connectors can configure an editable in-app target URL template using `{app_origin}`, `{app_url}`, `{username}`, `{platform_id}`, `{name}` and `{target_url}`.
- Added automatic Eitaa preset routing from a public `eitaa.com/<username>` URL to the configured web-app origin hash route `/#@<username>`. The rule is a preset default; the shared template mechanism works with arbitrary browser applications and is editable in the connector UI.
- Capture diagnostics now report the route template source and the resolved in-app target route, without exposing URL query strings.
- Existing direct URLs remain unchanged for connectors without a route template or preset default. Existing databases and Chromium profiles are preserved.

## 1.8.16 — Exact Channel Identity & Scoped Search Resolution

- Username/handle evidence is now exact: normalized username attributes, dedicated handle labels, exact handle tokens or exact URL path/hash segments. Substring matches against arbitrary links or page text are rejected.
- Active titles, handles and platform IDs are read from conversation-header regions rather than broad `main` page content. A generic active title such as `جستجو` cannot verify a conversation.
- Default search-result discovery is restricted to recognized chat/search result containers. The collector no longer scans every page anchor, button and list item, eliminating false ambiguous matches from unrelated links and navigation controls.
- When the configured direct route is loaded but the app still shows a generic search view, collection stops with `target_route_loaded_but_active_conversation_not_detected` instead of performing another broad search.
- Candidate diagnostics now show the exact usernames and row hrefs used for matching. URL diagnostics omit query strings and fragments to avoid exposing tokens.
- Added regression tests for the reported false-positive candidate list, exact handle matching and active-header scope.

## 1.8.15 — Adaptive Date-Range Collection & Honest Active-Channel Verification

- Explicit date-range collection automatically switches a connector saved as `manual` to adaptive message-aware scrolling by default. Visible-only capture remains manual, and `date_range_mode=manual` is available when current-page-only behavior is intentional.
- Active conversation verification now rejects URL/hash-only matches and usernames found only in the route. URL/handle evidence must agree with a non-generic active conversation title and configured message elements; IDs are also checked against an active message view.
- Added conservative selector coverage fallback for simple class-based message roots: relax one trailing class only when the configured text field exists and all original matches remain included. Capture returns configured and effective selectors plus their counts.
- Improved scroll diagnostics with before/after movement, edge detection, and a safe no-scrollable-pane failure instead of blindly scrolling the document.
- Generic date-range results now calculate oldest/newest observed days, in-range counts, and history-boundary confirmation from the actual scrolled sample. Human-readable title timestamps are parsed using the connector timezone.
- Renamed result counts from “page turns” to “navigation steps” and exposed auto-promoted navigation in the collection summary.
- Added regression coverage for strategy resolution, active identity requirements, selector relaxation, timezone timestamp parsing and generic date-range boundary accounting.

## 1.8.14 — Universal Channel Identity & Verified Navigation

- Added configurable target identity fields: direct channel URL, username/handle, platform-specific ID, active identity CSS selector and attribute.
- Reworked target resolution to check the already-open page first, navigate to a configured direct destination when necessary, and use stable identifiers before display-name search.
- Search results can be matched by descendant IDs and username-bearing links/attributes; ambiguous display names no longer force a manual search when a stable identifier is available.
- Active identity checks exclude chat-list/sidebar elements to prevent a search result from being mistaken for the current conversation.
- Capture API and Agent Shadi tools accept and persist direct URL, username and platform-ID overrides.
- Capture result now includes identity verification evidence (`already_open`, resolution method, active title and IDs).
- Added validation and regression coverage for target URLs, CSS identity selectors, identity persistence and capture overrides.

## 1.8.13 — Universal Browser Selection, Persistent Sessions & Adaptive Navigation

- Replaced the Alt-only DOM selection workflow with a visible in-page Click select mode and right-click selection menu. Alt+click remains optional; the menu can select the clicked node, its parent, grandparent, or nearest repeated sibling item.
- Added idle-state browser-profile diagnostics. Connector status now checks the stable per-workflow/per-connector Chromium profile even when the browser is closed, reporting profile existence, cookie, local-storage or IndexedDB/session-storage data presence and aggregate metadata only. It never reads or returns cookie values or credentials.
- Made per-connector session retention explicit and editable (persistent by default; temporary profiles are deleted on close). Agent Shadi can inspect and update this setting. Existing profile directories are preserved.
- Generalized date-aware pagination selectors and timestamp timezone handling for any connector. Generic pagination now requires explicit previous/next selectors; the Eitaa defaults remain only as a compatibility preset. Date-only timestamps are not shifted across timezones.
- Added adaptive and fixed wait modes, configurable minimum/maximum wait, DOM quiet interval, viewport-ratio or fixed-pixel scroll step, max idle cycles, timestamp timezone and per-page navigation selectors. No-change cycles now consume the full adaptive budget and progressively wait longer; pages that change can finish after a quiet DOM interval.
- Optimized scroll-container discovery by ranking ancestors of sampled message roots rather than scanning every DOM node against every message.
- Exposed per-cycle scroll diagnostics (wait duration, DOM mutations, new messages and scroll position) in capture results and the UI.
- Updated Agent Shadi connector guidance and troubleshooting to be platform-agnostic. Added regression tests for selection modes, profile diagnostics, session updates, generic pagination configuration, timezone behavior and adaptive navigation.
- Verified locally with automated tests and JavaScript/Python syntax checks. Live authenticated Rubika/Eitaa sessions are not available in this build environment and remain an on-device verification step.

## 1.8.12 — Product-specialist Agent, channel-aware custom collection and clearer source controls

- Repositions Agent Shadi as a knowledge-based AI data-collection and data-quality specialist, not a generic full-stack development partner.
- Adds focused Markdown product-knowledge modules with per-turn BM25-style section retrieval so only relevant guidance enters small local-model contexts.
- Reworks Dashboard and Ask Agent Shadi copy around source connection, collector operation, variable/schema design, extraction, data organization and golden-data quality.
- Adds channel/conversation name plus optional search-input and search-result selectors to custom connector configuration.
- Custom collection now searches for the configured channel name, opens only one unambiguous match, and verifies the active conversation title before capture. Ambiguous or unverified results stop safely.
- Makes the channel name available in the shared Run collection panel and persists a changed channel name to the connector.
- Clarifies source browser and collection actions with numbered, primary steps.
- Adds a database persistence receipt to custom collection results, distinguishing persisted source messages from structured extraction records.
- Adds focused tests for knowledge retrieval, connector channel configuration, channel-opening safeguards and database counts.

## 1.8.11 — Eitaa Date-Range Collection in the Shared Collector

- Adds Saved web connector (Eitaa / custom) to the main Run collection platform selector. It uses the same Jalali/Gregorian/Auto/Custom start and end date inputs, workflow collection policy and automatic-extraction toggle as Telegram/Rubika, plus a per-run message cap.
- Adds an Open Eitaa / web browser action and browser-session status to the main collection panel. Users no longer need to open the connector editor just to start the persistent browser session.
- Detects Eitaa's actual DOM and applies a deterministic preset: repeated message wrapper, message text, author, numeric wrapper ID, ISO timestamp from `time[datetime]`, optional photo link, and older/newer pagination cursors.
- Automatically repairs an existing saved Eitaa connector on first list/use when its saved DOM selectors identify Eitaa. This replaces the incorrect meta timestamp selector and manual navigation with the evidence-backed `datetime` selector and Eitaa pagination strategy.
- Adds date-aware Eitaa pagination across same-origin before/after links, deduplication, message caps and explicit boundary diagnostics. It crosses beyond each requested boundary (or reaches actual history exhaustion) before reporting a complete range; it does not treat merely seeing a post on the boundary day as proof that all posts for that day were collected.
- Normalizes ISO timestamps to Asia/Tehran before date filtering so Eitaa UTC datetimes align with the local date shown by the site's clock.
- Eitaa preset generation is deterministic and does not send HTML to the local model, so it no longer requires model consent for this known structure. Other websites still require explicit HTML-sharing consent for model assistance.
- Adds regression tests for multi-page boundary dates, timezone conversion, old connector migration, deterministic Eitaa setup and shared Jalali date-range collection.

## 1.8.10 — Robust AI Connector Proposal Parsing

- Tightened the connector-assistance prompt to request compact, minified JSON with concise explanations.
- Increased the connector proposal output-token allowance and detects `finish_reason: length`.
- Automatically retries incomplete or malformed proposals with smaller HTML evidence and a stricter JSON-only reminder.
- Added syntax-only JSON recovery for Markdown fences, embedded unescaped quotes, trailing commas and omitted commas between clearly separated object members. Truncated JSON is never completed by guessing.
- Added required top-level shape checks before selector evidence validation and proposal normalization.
- Added regression coverage for malformed JSON and token-limited responses.

## 1.8.9 — Context-Aware Universal Web Connector Assistance

- Fixes local model context overflow during AI connector setup with large individual-message and surrounding-list HTML samples.
- Compacts HTML structurally, strips non-selector noise and tracking query values, and enforces a combined sample budget.
- Summarizes deterministic selector evidence to prevent it from overwhelming the request.
- Reserves a bounded response budget and retries progressively smaller excerpts after context-size errors.
- Reports original/sent sample sizes and retry count in the UI.
- Uses the same excerpt for model analysis, supported-root checks and selector validation.

## 1.8.8 — Adaptive Rubika Scrolling + In-App Recovery

- Reworked Rubika history scrolling to inspect ancestors of real visible message cards, score candidate viewports, use wheel coordinates taken from message cards, and try direct scrolling across candidates rather than returning after a no-op.
- Fixed a false-success condition: a successful `page.evaluate()` call no longer counts as scrolling unless the selected container's scroll position or message viewport demonstrably changes.
- Scroll diagnostics now include candidate type/class, depth, position, size, overflow behavior and visible-message evidence. The collector fails closed when it cannot identify a useful scroller.
- Added an in-app **Manual history recovery** checkpoint after two verified no-progress attempts. The browser stays open; the operator scrolls the actual message list and presses **Continue history**. The channel is revalidated, and the checkpoint only succeeds if oldest date, viewport signature or scroll state changes.
- Bounded manual recovery to two attempts. A still-stalled scan stops with actionable diagnostics and cannot be recorded as complete.
- Strengthened manual Rubika identity evidence: the clicked search row and active chat header are compared; mismatch/unproven cases remain explicitly labeled and are never called username-verified.
- Shadi's collector diagnosis now identifies manual history recovery, identity mismatch and scroll stalls from application telemetry. It inspects state first and recommends the exact permitted recovery action; it does not self-modify executable code or perform blind clicks.
- Added regression tests for recovery checkpoint bounds, channel revalidation, diagnosis routing, candidate fallback and no-op scroll handling.

## 1.8.7 — Rubika Display-Name Selection + Safe Continue

- Fixed the Rubika case where search results expose a Persian channel display name and subscriber count but omit the configured @username.
- When the application cannot safely identify a matching channel result, it no longer fails immediately or sends another Enter key after the operator has clicked a result. It watches for the operator's click inside the search results and for the newly opened chat to reach a stable message-list state.
- Added an explicit **Select channel in browser** phase. The user clicks the intended channel result; Agent Shadi detects the active chat and only then presents the normal in-app **Continue collection** checkpoint. Message-preview rows are not automatically selected as a fallback.
- Pins a manually selected chat to its observed active display title and rechecks that title after Continue, so switching to a different chat aborts collection before capture.
- Keeps the browser open while waiting for the manual choice and reports a clear timeout/error if no stable chat opens.
- Added regression coverage for Persian display titles mapped to username identifiers, wrong-chat detection after manual selection, early recognition of manual clicks and stable-chat confirmation.

## 1.8.6 — Reliable Rubika Search + In-App Collection Continue

- Replaced the normal Playwright Inspector debugger pause with an explicit
  in-app Continue collection checkpoint. The browser stays open while the
  operator positions the requested history; one button press signals the
  collector through a one-shot local file gate.
- Removed `PWDEBUG=1` from application-launched collection runs, eliminating
  the confusing Resume/Step-over debugger workflow. Direct CLI runs retain the
  Inspector fallback for developers.
- Rubika search now matches the visible search result against the saved channel
  identity/username and clicks only a matching result. It no longer clicks the
  first generic `.c-ripple` row or labels a search submission as channel-opened.
- Removed a duplicate Rubika navigation that reset page state after login.
- Removed a second, legacy `open_channel()` definition that shadowed the verified Rubika search implementation. The older function could fill the search field, click a generic result and return no selection, causing the collector to fail before capture. A regression test now ensures the robust implementation cannot be shadowed.
- The channel must be verified and the message list stable before the operator
  checkpoint appears. After Continue, the channel and readiness are checked
  again before any history scrolling or capture.
- Added one-shot API resume signaling, a clear waiting UI and regression tests
  for search-result matching, pre-pause readiness and duplicate Continue clicks.
- Channel runners now return structured per-channel success/failure details. A failed
  channel cannot disappear into a successful zero-message run; partial successes
  are still imported and the overall run is labelled completed with errors.

## 1.8.5 — Live Progress + State-Aware Collectors + In-App Operator

- Live AI progress is published before local model preflight, so a slow or offline model no longer leaves the user looking at a stale “not extracted yet” state. The browser polls without the initial idle-response race and reports model check, preparation, inference, validation and save phases.
- Stale in-flight extraction messages are recovered into a retryable interrupted state after server restart or when no active worker progress exists. They are never silently left stuck as `processing`.
- Agent Shadi is now an app-aware operator with bounded application tools: inspect workflow and message state, edit supported schema/prompt/rule/collector/connector settings, test extraction without persisting, inspect collector phases and start explicitly authorized collection/extraction. Shell execution, arbitrary SQL, credential access, deletion and record approval/rejection remain unavailable.
- Shadi's operating instructions emphasize paired troubleshooting: inspect real state/logs first, use available tools instead of asking the user to repeat a supported UI operation, verify each change, avoid blind browser actions during loading, and stay with the task until the actual blocker is resolved.
- Telegram/Rubika collectors emit structured phases consumed by the application status monitor and by Shadi. The Inspector pause is after the configured channel is opened, allowing manual positioning at the requested end date without later auto-navigation overwriting it.
- After Resume, collectors re-verify the expected channel and wait for stable message count plus a stable signature of the latest visible messages before any scroll/capture. The scroller is selected only when it contains actual message nodes; there is no keyboard/PageUp fallback that could scroll an unrelated pane.
- Telegram/Rubika history scans must confirm the requested start-date boundary before writing a successful manifest. A stalled or partial scan now fails explicitly instead of appearing as a complete collection.
- Fixed Rubika oldest-date tracking and added tests for stale live extraction recovery, progress before model health probing, structured collector phases, stable message readiness, correct Inspector placement and incomplete history failure.

## 1.8.4 — Compact RTL-Safe Review + Connector-Guided Agent

- Simplified the Review Desk extraction pane to show only each configured field label and its value. Removed repeated internal keys, provenance labels, confidence and duplicated source/date metadata from the compact view.
- Added a persistent vertical divider between the original-message and extracted-values panes. Both remain visible and independently scrollable.
- Replaced character-count wrapping with terminal-cell-aware wrapping and clipping. Long URLs/tokens, Persian/Arabic text, combining marks and wide characters are kept inside their assigned panes.
- Repositioned Agent Shadi as the in-app guide for the existing Universal Web Connector. For browser-based channel collection it now directs users to the connector UI, then guides them step by step through browser login, DOM inspection, selector mapping, validation, visible capture, history collection and downstream extraction/review.
- Added non-sensitive saved-connector context to chat (connector name, sanitized URL, configured selector coverage, navigation strategy and browser status). URL query strings/fragments, raw messages, HTML samples, cookies and credentials are not sent to chat.
- Added regression tests for RTL/wide-text clipping, pane boundaries, compact extraction rendering, connector-aware guidance and URL-secret redaction.

## 1.8.2 — Web Developer Agent + Side-by-Side Review Inspector

- Repositioned Agent Shadi as a senior full-stack web developer and software engineering consultant, not a real-estate or source-platform-specific assistant.
- Workflow metadata is now explicitly secondary context; the assistant answers the actual question and uses workflow details only when relevant.
- Added bounded chat generation (`max_tokens=600`) and a longer configurable local-model read timeout to reduce premature cancellation on slower quantized models.
- Rebuilt the terminal Review Desk as three persistent panes: numbered queue, complete original message, and extracted fields. The message and extraction stay visible simultaneously.
- Kept independent message/extraction scrolling; Tab selects which pane receives Page Up/Down scrolling.
- Added regression tests for the general web-development persona, chat timeout/token settings, and simultaneous message/extraction visibility.

## 1.8.1 — Full Extraction Inspector + AI Connector Setup

- Added a dedicated right-hand Review Desk inspector with independent Message and Extraction tabs, independent scrolling and a complete schema-field list (including empty fields).
- Restored distinct per-field colors and retained provenance, confidence and validation details in the Extraction view.
- Fixed Ask Agent Shadi chat payloads for strict local chat templates by combining workflow metadata into the single leading system message.
- Added automatic model discovery from the configured OpenAI-compatible `/v1/models` endpoint, readable short model names and manual-ID fallback; the exact server-required model ID remains stored internally.
- Added regression tests for long-message inspection, field colors, inspector navigation, one-system-message chat payloads and model discovery.

## 1.8.0 — Sequential Live Review + Background Process Control

- Live AI Review Desk automatically extracts the focused raw message on opening; after approve/reject it sends the next eligible message automatically when Auto-advance is enabled.
- With Auto-advance disabled, the desk pauses after each decision and sends the next message only after the operator explicitly continues.
- Added cooperative pause, resume and cancel controls to batch extraction runs. In-flight LLM requests finish safely before pause/cancel takes effect.
- Added a persistent background process monitor with progress, failures, remaining count, recent logs and controls while navigating modules.
- Added regression tests for sequential Live AI and run controls.

## 1.8.0 — Verified Review Desk + Process All

- Add a Review Desk startup handshake; the API waits until the TUI has drawn its first screen before it reports success.
- Launch Konsole with `--nofork` so the local service can track the separate terminal session; successful terminal-client handoff is not mistaken for a UI startup failure.
- Preserve visible startup errors, remove transient handshake files and never show a green success toast without the Review Desk readiness signal.
- Add a prominent, counted **Process all queued messages** card to the dashboard and both Review Studio paths.
- Show queued, failed and interrupted counts separately from collection-policy-held messages; held items must be requeued before batch processing.
- Permit an explicit per-request batch override when Live AI is the saved default; do not mutate the saved preference.
- Keep normal human approval requirements for all extraction results.

# Changelog

## 1.6.2 — One-click Review Desk launch
- The Review Studio web button now launches the full-screen reviewer in a new terminal window through the running local Agent Shadi service.
- Removed command-copying and desktop-menu installer instructions from the normal user flow.
- Added same-origin, loopback-only launch protection and clearer no-terminal/headless-session diagnostics.
- Added API and terminal-command tests for successful launch, cross-origin rejection, missing terminal and headless sessions.

## 1.6.2 — One-click desktop Review Desk launch
- Replaced the browser launch instructions and copy-command action with a single **Open Review Desk** button.
- Added a local API endpoint that starts the separate terminal reviewer in a new desktop terminal window on the same computer.
- Supports Konsole (preferred on KDE/Manjaro), GNOME Terminal, x-terminal-emulator, Kitty, Alacritty, WezTerm, Foot and XTerm; includes Windows console and macOS Terminal.app launch paths.
- Added loopback-only and same-origin checks to prevent remote websites from triggering local process launches.
- Removed the need to install a desktop-menu shortcut for the normal web-to-terminal flow; direct shell launchers remain available as fallbacks.


## 1.6.1 — Standalone Keyboard-first Review Desk
- Replaced the embedded browser terminal command console with a launch card for a separate full-screen terminal application.
- Added a curses-based Review Desk with one-keystroke approve/reject/edit for the focused extracted record, fast J/K or arrow navigation, batch selection, workflow/path switching, paging, search, undo and an optional command bar.
- Kept one-by-one approval for already-extracted results: each batch-extracted record remains in `needs_review` until explicitly approved/rejected/edited. Guided mode can pause after every decision, and the TUI enforces that pause before another decision key can be accepted.
- Kept Live AI sequential extraction separate: X sends only the focused raw message to the configured model and requires a human decision before another message is sent.
- Added Linux, macOS and Windows launchers; Linux `review.sh` opens a new Konsole window, and `install_review_launcher.sh` adds a desktop application-menu entry.
- Direct execution of the historical `review_terminal.py` entry point now opens the full-screen Review Desk instead of the old line-input prompt.
- Added UI regression checks that prevent reintroducing the embedded command console and cover the standalone launcher.

- Made the selected review processing path authoritative: batch extraction API requests are rejected while Live AI one-by-one is selected.
- Prevented collector auto-process from bypassing Live AI mode; newly captured messages remain queued for explicit sequential extraction.
- Dashboard Run controls now open Live Review in Live AI mode and retain batch processing only in Review extracted results mode.
- Added regression coverage for the server-side batch guard and dashboard/collector routing.

## 1.5.0 — Live AI Review & Standalone Review Terminal
- Added an explicit choice between reviewing pre-extracted records and live sequential LLM extraction of one raw message at a time.
- Added live-review queue and single-message extraction APIs with model health preflight, atomic message claiming, retryable failure handling and mandatory human decision status.
- Added an explicit Run button click handler, Enter handling, command busy state and live extraction commands in the Review Studio console.
- Added a dependency-free standalone terminal review client and Linux, Windows and macOS launchers.
- Added tests for live extraction success, offline safety, queue transitions and persistent review path settings.


## 1.4.0 — Review Studio & Shadi Review Terminal

- Replaced the basic Review Queue page with a dedicated Review Studio supporting Guided one-record-at-a-time review and Batch multi-select review.
- Added direct Review Studio controls for human approval on/off for new extraction results and automatic/manual advance after each decision. Existing pending records remain unchanged when the approval setting is toggled.
- Added a numbered queue with search, source and issue filters, confidence/error sorting, paging, immutable original-message evidence, source/date references, field provenance, confidence, warnings and errors.
- Added approve, reject, edit and skip actions for the focused record. Guided manual-advance mode pauses after a decision and requires an explicit Continue action.
- Added batch selection with row numbers, approve/reject selected, current-page actions, confirmation for bulk decisions and reversible decision history.
- Added the Shadi Review Terminal with commands such as `approve 1-5`, `reject 2,4`, `edit 3`, `select 1-10`, `select all`, `approve selected`, `approve all`, `page next`, `page prev`, `next`, `prev`, `filter warning` and `undo`. Commands use the same server-side action endpoints as the visual controls.
- Fixed guided navigation so next/previous traverses page boundaries and manual advance retains the intended next-row position after the approved/rejected item leaves the queue.
- Added page-aware range validation and regression coverage for paginated decisions and undo restoration.
- Renamed the sidebar entry to Review Studio and added a direct auto-advance and bulk-confirmation controls, configurable 50/100/250/500 row page sizes, and persistent sort preferences in the review toolbar.
- Updated version and cache-busted static assets to 1.4.0.

## 1.3.1 — Live Model Health & Sidebar Reliability

- Replaced the stale persisted-green model badge with a live runtime check of the configured OpenAI-compatible `/models` endpoint.
- Added automatic checks on startup, every 30 seconds, on window focus/visibility return, and when Model & Settings is opened; status clicks and the settings page can force an immediate refresh.
- Verify the exact configured model identifier against the live endpoint's model list. Report Online, Offline, Model not loaded, Needs configuration, LLM disabled and Rules-only states distinctly.
- Automatically synchronize the persisted extraction-verification flag with live reachability; failed probes invalidate it and successful later probes restore it.
- Hardened extraction preflight to check the endpoint and selected model again before creating a run, preventing stale client state from starting an extraction batch.
- Added a live status panel with detected model IDs and one-click model selection in Model & Settings.
- Moved the Private workspace information card and Model & Settings navigation item into the main sidebar list. Made the sidebar navigation independently scrollable and pinned only the version footer to the bottom.
- Added regression tests for stale status, recovery, missing models, disabled/rules-only states, and persistent sidebar navigation.
- Updated version and cache-busted UI assets to 1.3.1.

## 1.3.0 — Agent Shadi AI Workspace

- Rebranded the application as Agent Shadi while retaining the legacy `Structura_Flow` project directory and `STRUCTURA_FLOW_DATA` environment variable for safe in-place upgrades.
- Replaced the static shell with a futuristic dark desktop-style workspace: agent identity, robot vector mark, grouped navigation, command palette (`Ctrl/Cmd + K`), searchable workspace navigation and responsive layout.
- Rebuilt the dashboard around a selectable workflow canvas showing Sources, Collection Policy, LLM Extraction, Quality & Review and Dataset nodes. The inspector and dashboard cards use actual workflow counts, schema fields, connector counts, model status and run history.
- Added an LLM-backed Agent Shadi chat endpoint. It receives workflow metadata only, includes strict read-only/no-tools instructions and does not automatically transmit raw source messages or API credentials.
- Added responsive chat, agent context and explicit model-connection status. The assistant does not claim to execute actions; users retain control over configuration, collection and destructive operations.
- Removed the external Google Fonts dependency; the new UI uses system fonts and inline vector artwork so the interface remains usable offline.
- Preserved the existing extraction, collection, filtering, universal web connector, inbox, review, cleanup, corrections and export APIs.

## 1.2.1 — Flexible Collection Policies

- Separated source acquisition from workflow filtering. Telegram/Rubika collectors now preserve every captured in-range message in complete JSONL day archives before policy routing; the built-in real-estate classifier is an optional routing preset rather than a mandatory acquisition gate.
- Added per-workflow `Capture all`, `Keep matching`, `Exclude matching` and `Real-estate preset` modes with configurable ALL/ANY rule sets.
- Added conditions for text, sender, source, source reference, channel, posting date, message length, links, attachment presence and attachment count, with containment, equality, prefix/suffix, regex, numeric, date/text before/after, empty and list operators.
- Applied collection policy consistently to Telegram/Rubika imports, custom browser captures, pasted messages and uploaded files. Non-matching items remain in the Source messages inbox as `filtered` and can be manually queued; no collection policy silently deletes them.
- Added separate captured/queued/filtered/duplicate counts for platform collection, paste, file import and browser capture results.
- Corrected inbox-clear wording and counts so clearing unprocessed messages explicitly includes policy-held items; separate collector archives remain untouched by that operation.
- Added regression coverage for complete generic-source capture, custom include/exclude routing, held-message requeue, invalid/unsafe rule sets, sender/attachment metadata and date comparisons.
- Updated the app version and cache-busted static assets to 1.2.1.


## 1.2.0 — Universal Web Collector Studio

- Replaced the fixed-platform-only collection direction with a reusable custom web connector builder while retaining the Telegram and Rubika platform collectors.
- Added HTML evidence analysis for individual message `outerHTML` and surrounding list HTML, including repeated-root candidates and field-level selector suggestions.
- Added constrained CSS selector mappings for message root, text, sender, timestamp, message ID and attachments, plus sample match-count and field-coverage validation.
- Added optional AI connector assistance with a strict JSON-only contract, evidence-grounded selector requirements, explicit HTML privacy consent and human review before saving.
- Added persistent local Chromium inspection sessions with manual login and Alt+click DOM selector capture.
- Added browser capture for loaded messages and bounded collection strategies for manual capture, scroll containers, infinite scroll, load-more buttons and pagination. The engine scans incrementally to support virtualized lists and deduplicates within a run.
- Added per-workflow connector CRUD, configuration versioning, JSON import/export and import of captured messages into the existing inbox.
- Pasted HTML is parsed as data; AI-generated JavaScript is not accepted or executed. Browser profiles and session data remain local and are excluded from connector exports.
- Added API and unit coverage for HTML inference, CSS validation, connector persistence, consent gates and selector normalization.

## 1.1.0 — Expanded Dataset Explorer and large-dataset review

- Reworked Message inbox into a six-view data-quality workspace: Overview, Dataset records, Source messages, Quality checks, Field coverage and Change history.
- Added a dataset overview showing total/active records, whole-dataset quality flags, message processing statuses, top source channels, weakest fields and direct review shortcuts.
- Added quick review presets, text search, status/source/date filters, per-field conditions (contains, equals, empty, not empty, greater than and less than), sorting and grouping by source, status, date/month, quality signal or selected schema fields.
- Added table, card and compact layouts, per-workflow visible-column selection and side-by-side comparison of 2–4 selected records with differing fields highlighted.
- Added source-message inspection, original-text editing with re-extraction queueing, individual and bulk soft deletion, and linked-record handling.
- Added record approval/rejection, inline field correction, provenance display and reversible quality-history actions. Deletions and edits are soft/auditable; quality flags never remove records automatically.
- Added offset pagination for source messages and extracted records, stable ordering, and Load next batch controls so datasets larger than the first 1,000 rows can be inspected without loading everything into the browser at once.
- Added tests for real tab dispatch, overview composition, pagination endpoint stability, reversible edits and bulk source deletion.

## 1.0.9 — Guard extraction startup and recover stale runs

- Fresh installs no longer enable a fake `local-model` placeholder by default.
- Extraction is rejected before a run is created unless an LLM has been configured and its `/models` endpoint successfully tested, or rules-only processing has been explicitly enabled.
- Changing connection-critical settings (LLM enable state, API URL, model name or API key) invalidates the previous connection verification.
- Model settings now distinguish a configured but untested LLM from a verified connection and an explicitly selected rules-only mode.
- The Process action now shows an actionable inline explanation when extraction is not started.
- On application restart, abandoned queued/running runs are marked `interrupted` and in-progress messages are moved to `failed` so they can be retried or cleared.
- Fatal worker exceptions also release messages left in `processing`.

## 1.0.8 — Safe inbox clearing

- Added a Clear inbox action to the Message inbox.
- Added a safe mode to remove only waiting, failed, and interrupted messages while preserving successfully processed messages and their extracted records.
- Added a full workflow inbox reset that deletes that workflow's messages, linked extracted records, correction history, and duplicate-cleanup snapshots.
- Full reset requires an explicit acknowledgement.
- Clearing is blocked while collection or extraction is active.
- Source archives, exports, workflow schema/prompts, channel configuration, and browser sessions are preserved.
- Added API and UI regression tests for both clear modes and active-collection protection.

## 1.0.7 — Preserve source message boundaries and tail the live collection log

- Fixed a critical import-stage bug: collector output TXT files were split by blank lines, which could fracture one multi-paragraph source post into several inbox messages.
- Daily combiner now emits a structured JSONL sidecar for each rental/sale day file, preserving one record per actual platform post, including blank lines inside the post.
- Collector worker imports structured JSONL records directly and only uses legacy TXT segmentation when reading an older manifest without a sidecar.
- Rubika extraction prefers top-level `.message-item` nodes and excludes nested message fragments; Telegram also excludes nested matching message containers.
- Added an indeterminate activity bar after Playwright Inspector Resume.
- Collection log now displays the latest 80 lines, automatically scrolls to the newest line and preserves the outer page scroll position.
- Added regression tests proving a post containing internal blank paragraphs remains exactly one inbox record, cross-platform duplicates are still removed, and log auto-tail/progress behaviour is present.
- Versioned assets and visible build number updated to 1.0.7.

## 1.0.6 — Restore original Playwright Inspector controls

- Enabled `PWDEBUG=1` for collector subprocesses.
- Restored the original `page.pause()` breakpoint before each channel navigation.
- Removed the separate web-app resume-signal gate and its Start extraction prompt.
- Added Inspector pause/resume status markers to the collection log.
- Restored finite action/navigation timeouts after enabling Playwright debug mode.
- Updated collection instructions to point users to the Inspector Resume/Step toolbar.

# Changelog

## 1.5.0 — Live AI Review & Standalone Review Terminal
- Added an explicit choice between reviewing pre-extracted records and live sequential LLM extraction of one raw message at a time.
- Added live-review queue and single-message extraction APIs with model health preflight, atomic message claiming, retryable failure handling and mandatory human decision status.
- Added an explicit Run button click handler, Enter handling, command busy state and live extraction commands in the Review Studio console.
- Added a dependency-free standalone terminal review client and Linux, Windows and macOS launchers.
- Added tests for live extraction success, offline safety, queue transitions and persistent review path settings.


## 1.0.5 — Manual browser collection checkpoints

- Added a first pause on the Telegram/Rubika home screen so the operator can complete QR login and confirm the session before channel navigation.
- Added a pause after each configured channel is opened; extraction starts only after the operator presses **Start extraction** in the app.
- Added **Continue to channels** and **Start extraction** controls backed by a local resume signal.
- If automatic channel navigation fails, the browser remains open and the operator can open the channel manually before continuing.
- Prevented starting a second collection while an existing collector is paused.
- Added regression tests for the pause/resume gate and resume API.


## 1.0.3
- Added versioned CSS/JS URLs to prevent stale browser assets.
- Added visible 1.0.3 build indicator in the sidebar.
- Rebuilt file upload dropzone without a transparent full-area file-input overlay.
- Consolidated navigation into one delegated handler.
- Added visible in-app errors when a view fails to load.
- Increased common text, label, table and helper font sizes.

# Changelog

## 1.5.0 — Live AI Review & Standalone Review Terminal
- Added an explicit choice between reviewing pre-extracted records and live sequential LLM extraction of one raw message at a time.
- Added live-review queue and single-message extraction APIs with model health preflight, atomic message claiming, retryable failure handling and mandatory human decision status.
- Added an explicit Run button click handler, Enter handling, command busy state and live extraction commands in the Review Studio console.
- Added a dependency-free standalone terminal review client and Linux, Windows and macOS launchers.
- Added tests for live extraction success, offline safety, queue transitions and persistent review path settings.


## 1.0.3 UI refinement — 2026-11-09

- Increased global and component typography for easier reading at normal laptop viewing distance.
- Increased navigation, headings, field labels, helper text, buttons, tables, metadata and review text sizes.
- Fixed the Upload files drop-zone layout by making the label a full-width block element and placing the file input over the complete target area.
- Added actual drag-and-drop file import, visual drag-over feedback and a client-side 32 MB size check.
- Fixed Model & settings navigation: the sidebar shortcut now participates in delegated navigation outside the main navigation element.
- Added UI regression tests for settings navigation, upload drop-zone layout/behaviour and typography overrides.

## 1.0.1 Browser runtime fix

- Detect system Chromium/Chrome and avoid mandatory Playwright CDN downloads.
- Keep the application usable when no browser is installed; channel collection reports how to install one.

## 1.0.0 Private Preview

- Initial configurable extraction workflow, real-estate ruleset, collectors, review, cleanup and export.

## 1.0.5 — Collector import and flexible date inputs

- Fixed the standalone collector runner's Python import path. It now adds the actual product root and imports shared calendar utilities from `app.core.jalali`, instead of resolving the compatibility shim from a per-workflow working directory.
- Added Jalali, Gregorian ISO, auto-detected Jalali/Gregorian, and explicit custom date input formats for collection ranges.
- Added strict date parsing, date-order validation, unambiguous auto-detection, and consistent normalization to the collector's canonical internal Jalali format.
- Persisted date input preferences per workflow.
- Versioned frontend assets and the visible build number to 1.0.5.
