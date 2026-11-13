# Agent Shadi — Source-Neutral Collection Architecture

## Core design

Agent Shadi treats a browser page, file, or other authorized input as a **source of information**. A source adapter is responsible for acquiring content and preserving provenance. A workflow is responsible for interpreting that content through its schema, extraction prompt, and validation rules.

This separation allows the same processing and review pipeline to work across messaging applications, communities, portals, dashboards, and other browser-accessible services.

## Current collection policy (1.8.37)

**One collection run = one manually selected source page or channel.**

- The operator chooses a built-in source or a saved customer web connector.
- Agent Shadi opens the source's configured application entry point or connector browser session.
- The operator signs in when necessary and manually navigates to the exact conversation, channel, or page.
- The operator positions the source history and configures the desired date range.
- The collector verifies the active page and checks date boundaries before it reports coverage.
- A separate page or channel requires a separate collection run.

The application does not automatically search for channels, click search results, resolve a list of targets, or switch between channels during a collection run. This explicit workflow reduces ambiguity about which source was actually inspected.

## Target processing pipeline

`Select source → Inspect → Sample → Validate → Capture → Normalize → Deduplicate → Inbox → Extract → Review → Dataset`

1. **Select source** — the operator chooses one built-in source or a saved connector.
2. **Inspect** — determine whether the current page is reachable and whether its visible structure exposes usable content.
3. **Sample** — inspect representative items and confirm what constitutes one message or record.
4. **Validate** — verify item boundaries, text, identity hints, timestamps, scroll/pagination behavior, and selector coverage.
5. **Capture** — perform bounded collection with explicit progress and date checks.
6. **Normalize** — preserve original content, source identity, stable item identifiers where available, timestamps, and acquisition metadata.
7. **Deduplicate** — use stable source IDs where available and content fingerprints as a fallback.
8. **Inbox** — route captured items into a shared review queue without silently treating historical archives as current-run input.
9. **Extract** — apply workflow-specific fields and model/rules-based processing independently of the source platform.
10. **Review** — let the operator inspect, correct, approve, reject, and export the structured records.

## Main boundaries

- `app/sources/contracts.py` defines source-neutral data contracts.
- `app/sources/adapters.py` contains generic text and structured-file adapters.
- `app/sources/browser_adapter.py` bridges rendered browser pages to the source-neutral layer.
- `app/sources/registry.py` registers adapters by source kind.
- `app/collectors/universal_web.py` validates and normalizes saved web connector captures.
- `app/collectors/web_inspector.py` manages the live browser inspector and visual selector mapping.
- `app/collectors/browser_runtime.py` centralizes persistent browser profile and launch handling.
- `app/server.py` connects collection, extraction, review, settings, and persistence through the local API.

The source-neutral contracts are an architectural foundation; not every legacy collector has yet been replaced by the unified adapter pipeline. The existing collection paths remain covered by regression tests while migration proceeds.

## Reliability invariants

- An uncertain source identity is not treated as confirmed.
- A failed source must not contribute new captures to the completed run.
- Counts distinguish current-run captures from duplicates and historical archive totals.
- A configured URL or selector is not proof that the intended page was opened or that all requested history was captured.
- Date coverage is reported only when the collector has evidence for the requested boundaries or the actual history edge.
- A user-deleted item should not be reintroduced silently by a later import.
- Browser credentials, cookies, and browser storage values must not be included in prompts or ordinary diagnostics.
- Browser actions are bounded and observable; the operator remains responsible for source selection and sign-in.

## Browser connector workflow

Customer connectors are reusable, user-managed definitions for browser-accessible sources. The connector builder can inspect live pages, use operator-selected elements, map item fields relative to a repeated item root, validate selectors against samples, and save or export connector JSON.

The browser agent can propose a bounded next action based on observed page evidence, but it is supervised: the operator reviews the observation and decides whether to continue. A connector is not a promise of universal compatibility. DOM changes, shadow roots, canvas-only interfaces, virtualized lists, and access restrictions can require a different adapter or may prevent reliable capture.

## Explicit non-goals

- No promise to access every website or bypass authentication, CAPTCHA, paywalls, access controls, or rate limits.
- No collection from private or hidden endpoints without explicit authorization.
- No automatic channel discovery or switching during a run.
- No claim of complete date coverage when the available evidence is inconclusive.
- No destructive cleanup of local databases, browser profiles, or archives during upgrades.

## Migration notes

The source-neutral contracts and generic adapters were introduced as a staged migration foundation. The Universal Web Connector remains the main user-facing extension point for unfamiliar browser-based services. Legacy source collectors are retained until the common adapter path has feature parity and regression coverage.
