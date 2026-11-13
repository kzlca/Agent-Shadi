# Schema and variable design

## Field contract

Every extraction variable should have:
- stable machine name: lowercase snake_case, no spaces, stable across prompt revisions;
- human label: short and clear in the user's language;
- type: string, integer, number, boolean, date, array or object;
- required flag: true only when absence should count as a quality issue;
- description: define exact meaning, units, normalization and evidence boundary.

Avoid duplicate variables with overlapping meaning. Separate distinct concepts (e.g. total price vs monthly rent, posting timestamp vs event date, channel name vs sender name). Define currency and measurement units explicitly. For unknown values, return null/empty rather than guessing.

## Prompt design

State the extraction task, field semantics, allowed normalization, null policy, ambiguous-value handling and output format. Include positive and negative examples. Instruct the model to preserve source language when appropriate and never infer absent values.

## Connector variables vs extraction variables

Connector fields describe source-message metadata (message text, sender, timestamp, source ID, attachments). Workflow schema fields describe business/domain information extracted from that message. Do not conflate them. The connector timestamp is the message posting time; a date mentioned inside the message is a separate extracted variable.
