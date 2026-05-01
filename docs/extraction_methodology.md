# Extraction Methodology

The pipeline must be auditable and provenance-preserving, but it can no longer
be deterministic-only. Real Ministry PDF reports do not expose enough stable
embedded text structure for reliable metadata and finding extraction, and the
source PDFs are not expected to change in the near term. V1 therefore uses both
deterministic extraction and LLM-based extraction on every production run.

LLM extraction is a normal required stage, not an optional rescue path. It must
still be schema-bound, reproducible enough for review, and explicit about model
and prompt versions.

## Extraction Layers

1. Source discovery and download preserve Gov.il provenance, checksums, and HTTP
   diagnostics.
2. PyMuPDF extracts embedded text and page text where available.
3. pypdf records page count and structural metadata.
4. PDF rendering creates page images or page crops for multimodal LLM
   extraction.
5. Deterministic parsers produce cheap, explainable candidates for fields they
   can parse reliably.
6. Embedded-text LLM extraction produces structured candidates from extracted
   text and provenance context.
7. Multimodal LLM extraction produces structured candidates from rendered pages
   when layout, scanned text, or visually grouped fields are needed.
8. Reconciliation merges candidates into canonical rows and preserves conflicts
   as diagnostics.

OCR may still be useful later, but it is not the primary solution. If OCR is
added, OCR output is another candidate source that must be reconciled and
versioned like deterministic and LLM candidates.

## LLM Extraction Contracts

Every LLM call must request strict JSON matching a versioned schema. Free-form
answers are diagnostics only and must not flow into canonical rows.

Each candidate field returned by an LLM must include:

- canonical field name
- raw value as read from the source
- normalized value where applicable
- page number or page range
- raw excerpt and/or visual locator
- extraction method, such as `llm_text` or `llm_multimodal`
- model name and model version where available
- prompt/template ID and prompt version
- input artifact references, such as text path, rendered page path, or checksum
- confidence
- warnings and uncertainty notes

The extractor should prefer small page-scoped prompts over sending entire
documents when possible. Prompt inputs must not include secrets, private local
configuration, or unrelated browser/session state.

## Reconciliation

The reconciler compares candidate values from deterministic parsing,
embedded-text LLM extraction, multimodal LLM extraction, OCR if present, and
existing canonical values during backfills.

Rules:

- Never silently overwrite a deterministic value with an LLM value.
- Never silently overwrite an existing published canonical value during
  backfill.
- Prefer values with stronger source evidence and schema-valid normalization.
- Preserve all conflicting candidates and emit diagnostics when candidates
  disagree materially.
- Record the accepted source method and candidate IDs for every canonical field.
- Treat missing evidence, malformed dates, invalid enums, or low-confidence
  values as warnings or validation failures.

Some merge decisions may themselves use an LLM, but that LLM must also return
structured output with explicit reasoning, candidate references, and validation
status. The merge LLM proposes decisions; schema validation and provenance
checks enforce them.

## Parser Contracts

Parser functions should return structured records plus diagnostics, not only
strings. A parsed or extracted field includes:

- canonical field name
- normalized value where applicable
- raw excerpt or visual locator
- page number
- extraction method
- model and prompt version where applicable
- confidence
- warning codes/messages where applicable

PR 5 implemented deterministic top-level metadata parsing from PR 4 extracted
text and diagnostics. Real PDF inspection showed that deterministic text
parsing alone is insufficient for the project’s publication goals.

PR 6 validates report-level canonical rows, flattens raw and normalized values
for local CSV/JSONL export, and carries forward field evidence, page numbers,
warnings, parse diagnostics, source provenance, page counts, extraction status,
and extraction confidence. The metadata diagnostics sidecar is required;
exports fail closed if it is missing or invalid because canonical rows must not
lose diagnostics. Repository-local exports are restricted to the ignored
`outputs/` tree.

Future LLM PRs should add candidate manifests and reconciliation diagnostics
before changing publication behavior.

## Hebrew Normalization

The normalization layer should handle:

- Unicode normalization, preferably NFKC where appropriate
- zero-width characters
- non-breaking spaces
- punctuation variants
- Hebrew geresh/gershayim variants
- whitespace normalization
- common date formats in Hebrew reports
- preservation of canonical logical text order

Stored canonical values must not use visual bidi transformations.
`python-bidi` may be used only for debugging/display if needed.

Rendered-page and multimodal outputs must also preserve canonical logical Hebrew
text. If the visual order and logical order differ, keep the logical-order text
in canonical fields and preserve the visual evidence separately.

## Confidence and Warnings

Confidence should be conservative and explainable. LLM confidence is not proof
of correctness and should not be used alone to publish a value. Parsing
uncertainty should produce warning rows where possible instead of failing the
whole pipeline.

Hard failures should be reserved for broken discovery/download inputs,
unreadable files, missing required diagnostics, schema corruption, provider
configuration errors in required LLM stages, or conditions that make downstream
data unsafe.

## Weekly Runs and Backfills

Weekly incremental runs should process newly discovered or changed source
documents. They should skip expensive LLM calls for unchanged PDFs when the
candidate and canonical artifacts already exist for the active schema, model,
prompt, and renderer versions.

Backfill runs intentionally revisit historical documents when any of these
change:

- canonical schema
- prompt/template version
- LLM model
- page renderer or image preprocessing
- deterministic extraction logic
- normalization or reconciliation rules
- privacy or publication policy

Backfills must be resumable, idempotent, and reviewable. They should emit
before/after diffs for canonical fields and should publish only through a
data-repo PR.
