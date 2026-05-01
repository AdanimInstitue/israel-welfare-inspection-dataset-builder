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
normalized values. LLM and OCR candidates should also fail validation when they
lack immutable input identity, including source PDF SHA-256, prompt input hash,
and rendered page/crop hashes where applicable.

PR 7 validates rendered page artifacts and LLM candidates with Pydantic
contracts and committed JSON Schemas. Mocked LLM responses that omit required
provenance, include malformed date values, lack field evidence, or omit
required text/image input identity are preserved as extraction diagnostics
instead of being emitted as valid candidate rows.

PR 8 validates reconciliation decisions, reconciled metadata sidecars, and
backfill diagnostics with Pydantic contracts and committed JSON Schemas.
Malformed LLM candidate provenance, duplicate candidate IDs, duplicate report or
decision IDs, and material deterministic/LLM conflicts are diagnostics rather
than silent overwrites.

PR 9 validates weekly workflow safety through a planning contract rather than
live CI collection. The `weekly-plan` command records stage commands, required
review artifact paths, identity/version fields for future reuse decisions, and
excluded artifact classes. Production weekly mode is blocked until live LLM
provider calls and real incremental reuse are implemented. Tests cover this
blocking behavior without real secrets or live provider calls.

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

- a reviewed evaluation set must exercise representative real or synthetic PDFs
- the evaluation report must identify schema, model, prompt, renderer,
  preprocessor, and reconciler versions
- field-level coverage and correctness must meet the active release thresholds
- regressions against the last accepted model/prompt baseline must be explained
  or blocked
- every accepted LLM-derived value must include page evidence
- every LLM call must identify model and prompt/template version
- canonical rows must identify which fields used LLM-derived candidates
- conflicting deterministic and LLM candidates must be preserved in diagnostics
- low-confidence or unsupported values must be marked `needs_review` or omitted
  from canonical publication
- privacy checks must run on any extracted free-text fields before publication

Mocked provider tests are required for deterministic CI, but they are not a
quality gate by themselves. They only prove that the code can handle a shaped
response.

The PR 7 evaluator is offline and deterministic. It compares candidate manifests
to JSONL expected values, records field-level coverage and correctness, and
keeps regression reporting as a structural field until a reviewed baseline is
available.

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

The PR 8 reconciler makes unresolved reconciliation explicit. Any report with a
`needs_review` decision should block publication until reviewed or resolved by
future deterministic rules or explicit agreement thresholds.

The PR 9 weekly workflow reinforces this gate by uploading reconciliation
diagnostics, LLM evaluation reports, source/download/render diagnostics, and a
dry-run backfill summary without publishing. A successful artifact upload is
not a publication approval; it is review input for the later data-repo PR flow.

## Backfill Quality Gate

Backfills are expected when models, prompts, schema, rendering, parsing, or
reconciliation rules improve. A backfill is publishable only when it emits:

- the prior canonical value and candidate IDs
- the new candidate values and accepted value
- reason for any changed accepted value
- model/prompt/schema versions used
- source PDF, rendered page/crop, extracted text, and prompt input hashes used
- counts of `no_baseline`, changed, unchanged, unresolved, and rejected fields
- the relevant LLM evaluation report for the new model/prompt/render stack
- a data-repo PR summary suitable for human review

PR 8 provides the first dry-run backfill diagnostics contract for these fields.
It records accepted decisions as `no_baseline` because no published canonical
input is read yet; later PRs that compare against data-repo outputs must
populate real prior canonical values before reporting fields as changed and
still avoid silent overwrites.
