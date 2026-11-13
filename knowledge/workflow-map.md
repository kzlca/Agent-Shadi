# Studio workflow map

## 1. Dashboard

Shows active workflow, overall dataset status, collection/extraction progress and entry points. The product goal is to turn heterogeneous source content into structured, reviewable data—not to provide generic web-development consulting.

## 2. Workflow Builder

Defines the output schema (variables/fields), extraction prompt, examples, validation rules, preprocessing and review behavior. Each field should have a stable machine name, readable label, type, required flag and precise description. The prompt must say not to infer unsupported values.

## 3. Inputs & Connectors

Accepts pasted text, uploaded files, Telegram and Rubika platform channels and saved Universal Web Connectors. Collection settings include source identity, date range, calendar format, maximum items and collection policy. Browser sign-in is performed by the user in the persistent local browser.

## 4. Inbox / Source messages

Stores original collected messages, source name/reference, posted timestamp, attachment metadata and status. Typical statuses include queued, filtered, processed, failed, interrupted and deleted. Collection policy may hold a message as filtered; this is not the same as deletion.

## 5. Extraction

Transforms queued source messages into structured records using the workflow schema and configured model. Test extraction is non-persisting. Batch/live extraction behavior is controlled by review settings. Extraction failure should leave the source message available for retry.

## 6. Review Studio / Review Desk

Human review of extracted records. Correct field values and approve/reject decisions remain human-controlled. Do not describe an inbox message as an extracted record.

## 7. Data Explorer / Quality

Inspect source messages and structured records, filter/sort/group data, inspect completeness and quality flags, and locate duplicates or anomalies.

## 8. Cleanup

Deduplication and cleanup should be auditable and conservative. Prefer flags, previews and reversible status changes over silent destructive edits. Golden data is the curated result after validation, normalization, deduplication and human review.
