# Data Quality

Data quality is handled through validation, parse warnings, confidence scores,
fixtures, and provenance.

## Parse Warnings

Warnings should capture stage, severity, message, page number, and raw excerpt
where available. Expected stages include discovery, download, text extraction,
OCR, section detection, field parsing, normalization, validation, and export.

## Confidence

Confidence scores are not proof of correctness. They are a triage signal that
helps downstream users distinguish clean deterministic extraction from uncertain
or fallback extraction. Confidence should be computed from observable parsing
conditions and accompanied by warnings where needed.

## Validation

Later PRs should validate canonical rows against JSON Schema, Pydantic models,
and tabular constraints. Validation should detect missing required IDs,
malformed dates, invalid enumerations, duplicate primary keys, and broken
foreign-key relationships between source documents, reports, findings, and
warnings.

## Row-Level Failure Handling

The pipeline should prefer row-level warnings over full pipeline failure when a
single field or section cannot be parsed. A document may still produce a
`reports` row with `extraction_status` indicating partial extraction. Full
pipeline failure is appropriate when discovery/download is broken or outputs
would be structurally invalid.

## Fixtures and Golden Tests

Future parsing PRs should introduce small, clearly licensed fixtures or
hand-authored synthetic fixtures. Golden expected outputs should focus on stable
contracts and representative document patterns, not one-off overfitting to a
single PDF.

## Fixture Policy

The builder repository may contain only small, clearly licensed, reviewable
fixtures. Downloaded PDFs from normal runs must not be committed. Large or
generated artifacts belong outside the builder repository, and canonical dataset
outputs belong in the paired data repository.

Golden expected outputs should be text-based where possible, such as JSON, JSONL,
CSV, or plain text. Any real source PDF fixture must be intentionally added in a
later PR with clear provenance and licensing notes.

## Auditability

Every public row should be reproducible from source documents and parser
version. Exports should retain enough provenance for researchers to trace a
derived value back to its source PDF and extraction run.
