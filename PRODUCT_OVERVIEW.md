# Agent Shadi — Product and Engineering Overview

## Purpose

Agent Shadi is a local-first data-preparation workbench. It helps people and teams transform messy, unstructured source information into structured, validated, reviewable datasets. The goal is not simply to collect messages or scrape pages; it is to prepare data that can be trusted and used downstream.

The product is source-independent. Information can enter through pasted text, imported files, supported built-in browser collection workflows, or customer-configurable connectors for browser-accessible services. Extraction schemas are kept separate from the acquisition method so the same data model can be used across different source types.

## What Golden Data means in Shadi

Golden Data is a curated dataset whose records have been checked against a defined schema, normalized where appropriate, checked for quality issues, deduplicated where justified, and reviewed by a person. Records retain provenance so a reviewer can trace a value back to its source.

AI output alone is not considered ground truth. Shadi helps an operator create a trusted dataset by preserving source material, applying schema-driven extraction and deterministic rules, surfacing validation warnings, enabling correction and review, and exporting approved records.

## Product workflow

1. **Choose an input method:** paste content, import files, use a supported built-in collector, or create/import a saved web connector.
2. **Define the dataset:** specify fields, types, required values, extraction instructions, examples, preprocessing, validation, and optional deterministic rules.
3. **Inspect the source:** for browser connectors, sign in manually where needed, sample representative page items, map selectors, and validate field coverage.
4. **Collect a bounded range:** manually open one channel, conversation, or page for the current collection run; configure date bounds and limits; verify page position and coverage.
5. **Preserve and normalize:** retain original source content and provenance while applying configured normalization and deduplication.
6. **Extract:** process content using a configured model, deterministic rules, or a supported combination.
7. **Review:** inspect proposed values and warnings, correct fields, compare duplicates, and make human approval decisions.
8. **Export:** download reviewed records as CSV, Excel, or JSON.

## Engineering principles

- **Source-independent preparation:** input adapters do not dictate the dataset schema.
- **Operator-directed acquisition:** one manually selected page per collection run; no unattended channel search or switching.
- **Evidence over assumptions:** a configured URL, selector, or successful click does not prove source identity or complete date coverage.
- **Traceability:** original source content and field provenance remain inspectable.
- **Deterministic where possible:** repeatable normalization and business rules complement semantic model extraction.
- **Human review:** AI output is inspectable and correctable before it becomes trusted data.
- **Local-first operation:** application data and persistent browser profiles remain on the user's machine by default.
- **Bounded automation:** browser actions are observable and designed around user confirmation.

## Current architecture

- FastAPI serves a browser-based local interface and local API.
- Playwright provides persistent browser sessions and rendered-page inspection.
- Built-in collectors and saved web connectors acquire page content.
- Source-neutral contracts and adapters establish a shared acquisition model.
- SQLite stores workflows, messages, records, connector definitions, settings, and review history.
- Configurable model endpoints and deterministic processing handle extraction.
- The Review Studio and Terminal Review Desk support human approval and correction.

## Scope and limitations

A web connector is a configurable integration, not a universal scraping guarantee. Sites can change their DOM, expose only virtualized content, restrict automation, or require manual interaction. Each connector must be tested against the target site and used within the operator's authorization and applicable service terms. Browser-based connectors do not control native desktop applications.

The current release is distributed as Python source with a local web interface and launch scripts. A signed, compiled desktop installer is a separate packaging task. The application is designed for local single-user use, not hardened multi-tenant hosting.

## Example data

All files in `examples/` use fictional, synthetic records. They demonstrate configurable extraction workflows and are not copied from real channels, accounts, or customer datasets.

## License

The source is available under the PolyForm Noncommercial License 1.0.0. Commercial use requires separate written permission. See [LICENSE](LICENSE) and [COMMERCIAL-LICENSING.md](COMMERCIAL-LICENSING.md).
