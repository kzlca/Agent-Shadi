# Extraction execution modes and automation

## Separate collection from extraction

Collection captures original source messages into the workflow Inbox. It does not need to call the LLM. The Sources option `After capture, automatically send queued messages to AI` controls whether a collection run immediately starts a batch extraction. It is opt-in and defaults off. When off, raw messages remain queued in Inbox. This setting is distinct from the Agent Shadi `start_extraction` tool, which is a separate explicit one-time action.

## Extraction modes

- `ai_only`: send the original source message directly to the configured LLM. Bypass preprocessing, deterministic transformation rules and the locale-specific property-listing guardrail profile. Requires the LLM to be enabled.
- `ai_plus_rules`: run the LLM, then apply the selected domain guardrails and enabled workflow transformation rules. This is the compatibility default for existing workflows.
- `rules_only`: do not call the LLM. Use the limited explicit label/value fallback plus configured deterministic rules and selected domain guardrails. It does not understand arbitrary free-form messages.

Configure this in Workflow Builder → Extraction execution. Test a representative message before processing a batch.

## Do not conflate three kinds of rules

1. Collection policy decides whether a captured message is queued or held. It does not extract schema fields.
2. Rules-only fallback is a limited local extractor for explicit label/value pairs when no LLM is used.
3. Workflow transformation rules and domain guardrails run after LLM extraction only in `ai_plus_rules` (or in the rules-only path). `ai_only` bypasses them.

A non-empty prompt only proves that prompt text exists. It does not prove that the prompt is correct; inspect its actual contents and test it against source messages.
