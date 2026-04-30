# Schema

The v1 canonical model separates source provenance, report-level metadata,
finding-level extracted content, and parse diagnostics. Fields are classified as
raw, normalized, or derived.

Raw fields preserve source values as published. Normalized fields standardize
values for analysis while keeping the raw source value. Derived fields are
computed by the pipeline, such as IDs, checksums, confidence scores, and warning
records.

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

## Placeholder JSON Schemas

The `schemas/` directory contains placeholder schemas in PR 1. Later PRs should
expand them into complete JSON Schema and Pydantic contracts before exporters
are treated as stable.
