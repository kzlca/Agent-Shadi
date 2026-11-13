# Agent Shadi knowledge index

Purpose: a practical, product-specific operator and AI data-agent for Agent Shadi Studio. Retrieve only the pages relevant to the user's current task; do not load this entire directory into the model prompt.

## Knowledge modules
- [Agent purpose and operating contract](agent-purpose.md) — role, interaction style, user control, evidence rules.
- [Studio workflow map](workflow-map.md) — workflow sections and how work moves through the product.
- [Source Agent architecture](../docs/SOURCE_AGENT_ARCHITECTURE.md) — source-neutral acquisition pipeline, adapter contracts, reliability rules and migration plan.
- [Web connector field guide](web-connectors.md) — browser sessions, channel identity, DOM mapping, validation, collection.
- [Collection troubleshooting](collection-troubleshooting.md) — platform and custom collector diagnostics, recovery.
- [Data lifecycle and database](data-lifecycle.md) — raw inbox messages vs extracted records, persistence, status counts.
- [Extraction execution modes](extraction-modes.md) — AI-only vs deterministic rules, automatic extraction after collection.
- [Schema and variable design](schema-and-variables.md) — field naming, types, extraction prompts, provenance.
- [Golden data quality](golden-data.md) — normalization, deduplication, filtering, review and quality gates.

## Retrieval rules
1. Search by the user's actual task and current UI terms; load only the top few relevant sections.
2. Prefer current application code and live tool results over this documentation if they conflict.
3. Treat knowledge as operating guidance, not permission to take actions. Use application tools and require explicit user authorization for collection, extraction, or destructive changes.
4. If evidence is missing, say what is unknown and ask for the smallest useful diagnostic artifact.
5. Do not claim that a browser, connector, message, record, or setting changed unless a tool result confirms it.
