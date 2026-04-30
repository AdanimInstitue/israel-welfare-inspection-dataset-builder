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

PR 5 metadata warnings are emitted both on each report metadata row and in the
metadata parse diagnostics sidecar. Missing deterministic top-level fields,
malformed dates, unavailable extracted text, and missing text files are warnings
or per-document diagnostics rather than full-run failures.

## JSON Schemas

`schemas/report.schema.json` defines the PR 6 canonical report-level local
export row. Facility, inspection finding, and datapackage schemas remain
minimal placeholders until those export surfaces are implemented.
