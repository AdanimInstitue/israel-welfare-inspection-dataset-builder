# Data Quality

Data quality is handled through validation, parse warnings, confidence scores,
fixtures, provenance, LLM candidate review, and reconciliation diagnostics.

## Parse Warnings

Warnings should capture stage, severity, message, page number, and raw excerpt
where available. Expected stages include discovery, download, text extraction,
page rendering, OCR, LLM extraction, reconciliation, section detection, field
parsing, normalization, validation, publication, backfill, and export.

## Confidence

Confidence scores are not proof of correctness. They are a triage signal that
helps downstream users distinguish clean extraction from uncertain extraction.
Confidence should be computed from observable conditions and accompanied by
warnings where needed. LLM-reported confidence is only one signal; it must be
combined with schema validation, source evidence, and reconciliation status.

## Validation

Later PRs should validate canonical rows against JSON Schema, Pydantic models,
and tabular constraints. Validation should detect missing required IDs,
malformed dates, invalid enumerations, duplicate primary keys, and broken
foreign-key relationships between source documents, reports, findings, and
warnings.

LLM candidate manifests and reconciliation decisions also require validation.
At minimum, validation should reject candidates that lack source document IDs,
page evidence, model/prompt version, extraction method, or schema-compatible
normalized values.

## Row-Level Failure Handling

The pipeline should prefer row-level warnings over full pipeline failure when a
single field or section cannot be parsed. A document may still produce a
`reports` row with `extraction_status` indicating partial extraction. Full
pipeline failure is appropriate when discovery/download is broken, a required
LLM extraction stage is not configured for a production run, required
diagnostics are missing, or outputs would be structurally invalid.

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
derived value back to its source PDF, rendered page or text artifact,
deterministic parser version, LLM model/prompt version where applicable,
reconciliation decision, and extraction run.

## LLM Quality Gate

LLM extraction is required for production, but LLM output is not self-validating.
Before publication:

- every accepted LLM-derived value must include page evidence
- every LLM call must identify model and prompt/template version
- canonical rows must identify which fields used LLM-derived candidates
- conflicting deterministic and LLM candidates must be preserved in diagnostics
- low-confidence or unsupported values must be marked `needs_review` or omitted
  from canonical publication
- privacy checks must run on any extracted free-text fields before publication

## v0 Preview Quality Gate

Before any manual v0 preview publication, review local diagnostics from every
stage: discovery, download, text extraction, page rendering, LLM extraction,
reconciliation, metadata parsing, and export. Do not publish the preview if
diagnostics indicate missing required provenance, structural validation
failures, unexpectedly low extraction coverage, blocked or incomplete source
access, required LLM stages not run, unresolved reconciliation conflicts, or
privacy risk.

The v0 preview should publish only reviewed report-level metadata and a concise
diagnostics summary. It should not publish finding-level rows, downloaded PDFs,
or unreviewed large artifacts. LLM-derived fields may be included only when
they carry source evidence, model/prompt provenance, and reconciliation status.

## Backfill Quality Gate

Backfills are expected when models, prompts, schema, rendering, parsing, or
reconciliation rules improve. A backfill is publishable only when it emits:

- the prior canonical value and candidate IDs
- the new candidate values and accepted value
- reason for any changed accepted value
- model/prompt/schema versions used
- counts of changed, unchanged, unresolved, and rejected fields
- a data-repo PR summary suitable for human review
