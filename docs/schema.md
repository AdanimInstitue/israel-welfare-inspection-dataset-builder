# Schema

The v1 canonical model separates source provenance, report-level metadata,
finding-level extracted content, and parse diagnostics. Fields are classified as
raw, normalized, or derived.

Raw fields preserve source values as published. Normalized fields standardize
values for analysis while keeping the raw source value. Derived fields are
computed by the pipeline, such as IDs, checksums, confidence scores, and warning
records.

V1 also separates extraction candidates from accepted canonical values. A value
may come from deterministic parsing, embedded-text LLM extraction, multimodal
LLM extraction, OCR, or reconciliation. Canonical rows should preserve the
accepted value and enough candidate/provenance references to audit why it was
accepted.

## ID Strategy

IDs should be deterministic where possible. Source document IDs should be stable
across runs for the same Gov.il item or PDF URL. Report and finding IDs should
derive from source document identity plus stable parsed context. Random IDs
should be avoided for canonical rows.

## `source_documents`

Tracks discovered source PDFs and their provenance.

| Field | Type | Class |
| --- | --- | --- |
| `source_document_id` | string | derived |
| `govil_item_slug` | string/null | raw |
| `govil_item_url` | string | raw |
| `pdf_url` | string | raw |
| `pdf_sha256` | string/null | derived |
| `title` | string/null | raw |
| `language_path` | string/null | raw |
| `discovered_at` | datetime | derived |
| `downloaded_at` | datetime/null | derived |
| `source_published_at` | date/datetime/null | raw |
| `source_updated_at` | date/datetime/null | raw |

## `reports`

Tracks one parsed inspection report.

| Field | Type | Class |
| --- | --- | --- |
| `report_id` | string | derived |
| `source_document_id` | string | derived |
| `facility_name` | string/null | raw |
| `facility_id` | string/null | raw/normalized |
| `facility_type_raw` | string/null | raw |
| `facility_type_normalized` | string/null | normalized |
| `district` | string/null | normalized |
| `administration` | string/null | normalized |
| `visit_type` | string/null | normalized |
| `visit_date` | date/null | normalized |
| `report_publication_date` | date/null | normalized |
| `page_count` | integer/null | derived |
| `extraction_status` | string | derived |
| `extraction_confidence` | number/null | derived |
| `accepted_extraction_methods` | array | derived |
| `llm_candidate_ids` | array | derived |
| `reconciliation_status` | string | derived |

PR 5 emits local ignored metadata JSONL with the report provenance fields above
plus a `fields` object. Each parsed field keeps `raw_value`,
`normalized_value`, `raw_excerpt`, `page_number`, `confidence`, and field-level
`warnings` together. This output is an intermediate parse artifact, not the
final canonical dataset export.

PR 6 adds a validated local report-level export row. It flattens the PR 5
metadata fields into analysis-friendly columns while preserving the nested
evidence:

| Field | Type | Class |
| --- | --- | --- |
| `facility_name_raw` | string/null | raw |
| `facility_name_normalized` | string/null | normalized |
| `facility_id_raw` | string/null | raw |
| `facility_id_normalized` | string/null | normalized |
| `facility_type_raw` | string/null | raw |
| `facility_type_normalized` | string/null | normalized |
| `district_raw` | string/null | raw |
| `district_normalized` | string/null | normalized |
| `administration_raw` | string/null | raw |
| `administration_normalized` | string/null | normalized |
| `visit_type_raw` | string/null | raw |
| `visit_type_normalized` | string/null | normalized |
| `visit_date_raw` | string/null | raw |
| `visit_date` | date/null | normalized |
| `report_publication_date_raw` | string/null | raw |
| `report_publication_date` | date/null | normalized |
| `raw_fields` | object | raw |
| `normalized_fields` | object | normalized |
| `field_evidence` | object | derived |
| `warnings` | array | derived |
| `parse_diagnostics` | array | derived |

The JSONL export keeps nested objects. The CSV export keeps the same scalar
columns and serializes `raw_fields`, `normalized_fields`, `field_evidence`,
`warnings`, and `parse_diagnostics` as JSON strings.

PR 6 validates each metadata row before export. Missing required provenance or
IDs, malformed date values, and duplicate `report_id` values are recorded in
`export_diagnostics.json` where possible. Valid rows continue to export. The PR
5 metadata parse diagnostics sidecar is required so exported rows cannot
silently lose parse diagnostics.

Future report rows should add field-level accepted method metadata. Until that
schema is expanded, LLM and reconciliation outputs should be kept in sidecar
candidate/diagnostic manifests rather than flattening unexplained LLM values
directly into `reports.csv`.

## `extraction_candidates`

Tracks candidate values produced by deterministic parsers, OCR, or LLM
extractors before reconciliation.

| Field | Type | Class |
| --- | --- | --- |
| `candidate_id` | string | derived |
| `source_document_id` | string | derived |
| `report_id` | string/null | derived |
| `field_name` | string | derived |
| `raw_value` | string/null | raw |
| `normalized_value` | string/date/number/null | normalized |
| `page_number` | integer/null | derived |
| `raw_excerpt` | string/null | raw |
| `visual_locator` | object/null | derived |
| `extraction_method` | string | derived |
| `extractor_version` | string | derived |
| `model_name` | string/null | derived |
| `model_version` | string/null | derived |
| `prompt_id` | string/null | derived |
| `prompt_version` | string/null | derived |
| `prompt_input_sha256` | string/null | derived |
| `source_pdf_sha256` | string/null | derived |
| `text_input_sha256` | string/null | derived |
| `rendered_artifact_ids` | array | derived |
| `rendered_artifact_sha256s` | array | derived |
| `renderer_version` | string/null | derived |
| `preprocessor_version` | string/null | derived |
| `input_artifact_refs` | array | derived |
| `confidence` | number/null | derived |
| `warnings` | array | derived |
| `created_at` | datetime | derived |

`extraction_method` values should distinguish at least `deterministic`,
`llm_text`, `llm_multimodal`, `ocr`, `existing_canonical`, and
`reconciler_llm`.

`input_artifact_refs` is a convenience index, not the reproducibility contract.
LLM and OCR candidates must also carry immutable hashes for the exact PDF, text,
rendered image/crop, and prompt input artifacts that produced the value.

PR 8 adds a common local `extraction_candidates` compatibility model used by
the reconciler. PR 5 metadata fields are converted to deterministic candidates
with stable candidate IDs, field evidence, parser version, confidence, and
warnings. PR 7 LLM candidates are converted without dropping model, prompt,
input hash, rendered artifact, or evidence provenance. Invalid or duplicate
candidate IDs are reported in reconciliation diagnostics.

## `rendered_page_artifacts`

Tracks page images and crops used by multimodal LLM extraction.

| Field | Type | Class |
| --- | --- | --- |
| `rendered_artifact_id` | string | derived |
| `source_document_id` | string | derived |
| `source_pdf_sha256` | string | derived |
| `page_number` | integer | derived |
| `artifact_type` | string | derived |
| `parent_rendered_artifact_id` | string/null | derived |
| `renderer_name` | string | derived |
| `renderer_version` | string | derived |
| `render_profile_id` | string | derived |
| `render_profile_version` | string | derived |
| `dpi` | integer | derived |
| `colorspace` | string | derived |
| `image_format` | string | derived |
| `rotation_degrees` | integer | derived |
| `crop_box` | object/null | derived |
| `coordinate_system` | string | derived |
| `width_px` | integer | derived |
| `height_px` | integer | derived |
| `image_sha256` | string | derived |
| `local_path` | string | derived |

`artifact_type` should distinguish `page` and `crop`. `coordinate_system` must
match the `visual_locator` coordinate convention used by extraction candidates.

## `reconciliation_decisions`

Tracks how candidate values become accepted canonical values.

| Field | Type | Class |
| --- | --- | --- |
| `decision_id` | string | derived |
| `report_id` | string | derived |
| `field_name` | string | derived |
| `accepted_candidate_id` | string/null | derived |
| `candidate_ids` | array | derived |
| `decision_status` | string | derived |
| `decision_method` | string | derived |
| `reason` | string/null | derived |
| `warnings` | array | derived |
| `decided_at` | datetime | derived |
| `schema_version` | string | derived |
| `reconciler_version` | string | derived |

Decision statuses should include accepted, unresolved, conflict, rejected, and
needs_review. Publication should avoid silently emitting unresolved conflicts as
clean canonical values.

Material conflicts should remain `needs_review` unless deterministic rules or
explicit agreement thresholds resolve them. A `reconciler_llm` decision may be
stored as a candidate or decision aid, but it is not enough by itself to
auto-accept a disputed value.

PR 8 stores reconciliation sidecars in ignored local outputs:

- `schemas/reconciliation_decision.schema.json` for each field-level decision.
- `schemas/extraction_candidate.schema.json` for the common compatibility
  candidate contract used by reconciliation.
- `schemas/reconciliation_diagnostics.schema.json` for run and record
  diagnostics, including duplicate candidate IDs and duplicate decision IDs.
- `schemas/reconciled_report_metadata.schema.json` for report-level reconciled
  metadata, accepted extraction methods, LLM candidate IDs, decisions, and
  warnings.
- `schemas/backfill_diagnostics.schema.json` for dry-run backfill summaries,
  including before/after values, `no_baseline`/changed/unchanged/unresolved/
  rejected counts, input hashes, model/prompt/render/schema versions, and
  evaluation report references.

The first reconciliation rules are conservative: deterministic-only values are
accepted, deterministic and valid LLM candidates that agree are accepted with
all compared candidate IDs recorded, and material deterministic/LLM conflicts
stay `needs_review`. LLM-only values are retained as candidates and require
review before canonical acceptance.

## `inspection_findings`

Tracks individual findings, standards, recommendations, or section-level
observations.

| Field | Type | Class |
| --- | --- | --- |
| `finding_id` | string | derived |
| `report_id` | string | derived |
| `section_name` | string/null | raw/normalized |
| `topic` | string/null | raw/normalized |
| `question_or_standard` | string/null | raw |
| `finding_text` | string/null | raw |
| `status_raw` | string/null | raw |
| `status_normalized` | string/null | normalized |
| `recommendation_text` | string/null | raw |
| `page_number` | integer/null | derived |
| `extraction_confidence` | number/null | derived |
| `accepted_extraction_methods` | array | derived |
| `llm_candidate_ids` | array | derived |

## `parse_warnings`

Tracks row-level and document-level parsing diagnostics.

| Field | Type | Class |
| --- | --- | --- |
| `warning_id` | string | derived |
| `report_id` | string/null | derived |
| `severity` | string | derived |
| `parser_stage` | string | derived |
| `message` | string | derived |
| `page_number` | integer/null | derived |
| `raw_excerpt` | string/null | raw |

PR 5 metadata warnings are emitted both on each report metadata row and in the
metadata parse diagnostics sidecar. Missing deterministic top-level fields,
malformed dates, unavailable extracted text, missing text files, LLM provider
failures, low-confidence LLM candidates, and reconciliation conflicts are
warnings or per-document diagnostics rather than full-run failures when safe.

## JSON Schemas

`schemas/report.schema.json` defines the PR 6 canonical report-level local
export row. Facility, inspection finding, and datapackage schemas remain
minimal placeholders until those export surfaces are implemented.

PR 7 adds sidecar schema contracts:

- `schemas/rendered_page_artifact.schema.json` for rendered full-page and crop
  image artifacts used by multimodal extraction.
- `schemas/llm_extraction_candidate.schema.json` for schema-bound LLM field
  candidates before reconciliation.
- `schemas/llm_evaluation_report.schema.json` for offline comparison of LLM
  candidate manifests to reviewed expected values.

These PR 7 schemas describe intermediate local artifacts. They do not authorize
publishing LLM-derived values as canonical rows without later reconciliation,
privacy review, and publication gates.

PR 8 schemas also describe intermediate local artifacts. Reconciled metadata is
not published from the builder repository and backfill diagnostics do not
overwrite existing canonical values.
