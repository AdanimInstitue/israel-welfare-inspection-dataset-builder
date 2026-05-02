# Extraction Methodology

The pipeline must be auditable and provenance-preserving, but it is now layered.
The first layer is a source-observed report index from the Gov.il listing page
and does not require PDF parsing. PDF-content-derived layers cannot be
deterministic-only: real Ministry PDF reports do not expose enough stable
embedded text structure for reliable metadata and finding extraction, and the
source PDFs are not expected to change in the near term. Those later layers use
both deterministic extraction and LLM-based extraction in production.

LLM extraction is a normal required stage, not an optional rescue path. It must
still be schema-bound, reproducible enough for review, and explicit about model
and prompt versions.

## Dataset and Extraction Layers

1. Report index collection reads Gov.il listing-page cards and preserves the
   visible Hebrew fields without parsing PDF contents.
2. Source discovery and download preserve Gov.il provenance, PDF URLs,
   checksums, and HTTP diagnostics.
3. PyMuPDF extracts embedded text and page text where available.
4. pypdf records page count and structural metadata.
5. PDF rendering creates page images or page crops for multimodal LLM
   extraction.
6. Deterministic parsers produce cheap, explainable candidates for fields they
   can parse reliably.
7. Embedded-text LLM extraction produces structured candidates from extracted
   text and provenance context.
8. Multimodal LLM extraction produces structured candidates from rendered pages
   when layout, scanned text, or visually grouped fields are needed.
9. Reconciliation merges candidates into canonical rows and preserves conflicts
   as diagnostics.

The report index layer is intentionally lighter than the extraction layers that
follow it. It should capture only what the listing exposes: `שם מסגרת`,
`סוג מסגרת`, `סמל מסגרת`, `מינהל`, `מחוז`, `תאריך ביצוע`, source links, and
provenance. `מינהל` maps to the English alias `administration`; `מחוז` maps to
`district`.

PR 13 implements report index collection without invoking any PDF-content
extraction stage. It accepts the structured DynamicCollector response only when
all six visible listing fields are present for emitted records; otherwise it
uses browser-rendered public DOM collection for the run. It records field
coverage, pagination/source coverage, missing fields, duplicate IDs, malformed
source-date text, and output guards as diagnostics. It does not normalize the
listing values or infer missing values.

OCR may still be useful later, but it is not the primary solution. If OCR is
added, OCR output is another candidate source that must be reconciled and
versioned like deterministic and LLM candidates.

## Rendered Page Contract

Multimodal extraction depends on stable rendered inputs. A rendered page or crop
artifact must record:

- source document ID and source PDF SHA-256
- page number using the same 1-based numbering used in field evidence
- renderer name and version
- render profile ID and version
- DPI, colorspace, image format, rotation, crop box, and any preprocessing
- image width and height in pixels
- coordinate system used by visual locators
- rendered image SHA-256
- local ignored artifact path

The first implementation should prefer full-page PNG renderings at a fixed DPI
before adding crops. If crops are added, the crop ID must be deterministic and
the crop coordinates must be expressed in the parent page coordinate system.
`visual_locator` values in candidates must reference the rendered page or crop
artifact and use the documented coordinate system so evidence remains stable
across backfills.

PR 7 implements the first full-page rendering contract with PyMuPDF PNG outputs
under ignored local output directories. Render manifests include source
document ID, source PDF SHA-256, page number, renderer name/version, render
profile ID/version, DPI, colorspace, image format, rotation/crop metadata,
coordinate system, dimensions, image SHA-256, and local path. Crops remain a
contract surface only until a later PR needs page regions.

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
- source PDF SHA-256, text input hash, rendered page/crop hashes, prompt input
  hash, and renderer/preprocessor versions where applicable
- confidence
- warnings and uncertainty notes

The extractor should prefer small page-scoped prompts over sending entire
documents when possible. Prompt inputs must not include secrets, private local
configuration, or unrelated browser/session state.

PR 7 adds the candidate contract and CLI plumbing but not live provider calls.
`extract-llm --mode dry-run` writes no candidates, `--mode mock` validates local
mock responses, and `--mode production` fails closed when provider settings are
missing. Candidate manifests remain sidecar artifacts for reconciliation.

## Finding-Level Review Contracts

PR 11 adds the first finding-level contract slice. `extract-findings` reads
local source/download manifests, optional embedded-text diagnostics, optional
rendered page manifests, and optional local mock finding responses. It writes
review-only sidecars:

- `outputs/finding_candidates.jsonl`
- `outputs/finding_extraction_diagnostics.json`

Finding candidates must preserve source document ID, source PDF hash when
available, finding text, optional recommendation/legal references, page
evidence, raw excerpt or visual locator, prompt/model metadata where
applicable, immutable prompt/text/rendered-artifact hashes where applicable,
confidence, warnings, and validation status. Missing evidence or required LLM
provenance fails validation. Malformed mock/provider payloads are diagnostics
and are not emitted as valid rows.

PR 11 keeps findings out of canonical exports, reconciliation acceptance,
publication plans, and paired data-repo inputs. OCR, live provider calls,
dashboards, publication of finding rows, and scheduled extraction workflows
remain later work.

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
- Keep material conflicts as `needs_review` unless deterministic rules or
  explicit agreement thresholds resolve them.
- Record the accepted source method and candidate IDs for every canonical field.
- Treat missing evidence, malformed dates, invalid enums, or low-confidence
  values as warnings or validation failures.

Some merge decisions may themselves use an LLM, but that LLM must also return
structured output with explicit reasoning, candidate references, and validation
status. The merge LLM proposes decisions; schema validation and provenance
checks enforce them. A merge LLM is not sufficient authority to auto-accept a
material conflict by itself.

PR 8 implements the first offline report-level reconciler. It reads only local
PR 5 metadata artifacts and PR 7 LLM candidate manifests, converts both to a
common candidate contract, and writes ignored reconciled metadata plus
diagnostics. Deterministic-only fields are accepted. Deterministic and valid LLM
candidates that agree are accepted while preserving every compared candidate ID.
Disagreements between deterministic and LLM candidates are material conflicts
and remain `needs_review`; the reconciler does not silently replace a
deterministic value with an LLM value. LLM-only fields remain reviewable
candidates rather than automatic canonical values.

## LLM Evaluation Gate

LLM extraction quality must be measured separately from mocked provider tests.
The project should maintain a small reviewed evaluation set of real or
representative PDFs, expected report-level fields, and known hard cases. The
offline evaluator compares candidate manifests against expected values and
emits field-level coverage, correctness, and regression summaries by schema,
prompt, model, renderer, and reconciler version.

PR 7 adds the offline evaluation report contract and evaluator stub. It compares
candidate manifests to JSONL expected field fixtures without calling a provider.
Regression comparison is represented structurally and remains zero until the
project introduces an accepted baseline artifact.

Publication must be blocked when required evaluation thresholds fail, even if
candidate JSON is schema-valid. Thresholds should be conservative at first and
field-specific: a date field, facility name, facility ID, and free-text field do
not have the same risk profile.

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

The PR 8 `backfill` command is contract/plumbing only. It is dry-run by default
and does not collect history, call live providers, publish data, or overwrite
canonical outputs. It records input hashes, schema and reconciler versions,
optional evaluation report references, and `no_baseline`/unresolved/rejected
counters so later historical backfills can be audited before any data-repo PR.
