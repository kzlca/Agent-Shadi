# Data lifecycle and database semantics

## Two distinct persistent entities

### Source messages (`messages`)

Raw source content captured from Telegram, Rubika, a saved web connector, pasted text or uploaded files. Includes workflow ID, source, source reference, posted timestamp, raw/normalized text, fingerprint and status. Collection inserts here first.

### Structured extraction records (`records`)

The schema-shaped output produced by running the extraction engine on a source message. A record is linked to its source message by `message_id`. Records may be pending review, approved, rejected or flagged depending on workflow state.

## Expected lifecycle

Website or platform collector → `messages` inbox → collection policy (`queued` or `filtered`) → extraction run → `records` → human review → approved/curated dataset.

Collection completion does not imply extraction completion. A message count without a record count is expected before extraction. Conversely, if a capture response says `added > 0` but a fresh database query shows no matching messages for that workflow/source, treat it as a persistence defect and investigate the insertion transaction, workflow ID and source filter.

## Required diagnostics

For a connector, compare:
- `messages` grouped by `source` and `status`;
- `records` joined through `records.message_id` to `messages`, grouped by source and record status;
- capture result: found, added, queued, filtered, duplicates, undated skipped, out-of-range skipped, warnings;
- workflow ID and connector ID.

Do not report “not in database” solely because there are no extraction records. Inspect the source-message inbox separately.

See `extraction-modes.md` for the separate automatic-after-collection setting and AI-only execution path.
