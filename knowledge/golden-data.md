# Golden data quality

Golden data is not merely model output. It is a curated dataset produced through controlled capture, schema-conformant extraction, validation, normalization, deduplication and review.

## Quality pipeline

1. Preserve raw source messages and provenance.
2. Apply collection policy transparently; filtered means held, not deleted.
3. Extract using explicit field definitions and a constrained JSON contract.
4. Validate types, required fields, ranges, units, dates and cross-field consistency.
5. Normalize only deterministic conventions (digits, whitespace, phone formats, currency/unit representations) while retaining original raw text.
6. Deduplicate using stable source IDs where available, otherwise conservative fingerprints and human review for near-duplicates.
7. Flag missing, contradictory, implausible or low-confidence values.
8. Human review approves/corrects records before they are considered golden.
9. Export with provenance and an audit trail.

## Do not

- silently delete raw messages;
- fill missing values from guesses;
- merge records solely because text looks similar when dates/senders/identifiers differ;
- claim the dataset is golden while unresolved validation or review flags remain;
- conflate source-message capture counts with extraction-record counts.
