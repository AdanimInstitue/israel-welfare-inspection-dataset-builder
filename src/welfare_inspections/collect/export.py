"""Local canonical report exports from parsed metadata artifacts."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from welfare_inspections.collect.manifest import (
    _atomic_write_text,
    write_export_diagnostics,
)
from welfare_inspections.collect.models import (
    CanonicalReportRow,
    ExportRecordDiagnostic,
    ExportRunDiagnostics,
    MetadataField,
    MetadataParseRecordDiagnostic,
    MetadataParseRunDiagnostics,
    ReportMetadataRecord,
    utc_now,
)

logger = structlog.get_logger(__name__)

REPORT_CSV_COLUMNS = [
    "report_id",
    "source_document_id",
    "govil_item_slug",
    "govil_item_url",
    "pdf_url",
    "title",
    "language_path",
    "pdf_sha256",
    "local_path",
    "text_path",
    "page_count",
    "extraction_status",
    "extraction_confidence",
    "parsed_at",
    "exported_at",
    "facility_name_raw",
    "facility_name_normalized",
    "facility_id_raw",
    "facility_id_normalized",
    "facility_type_raw",
    "facility_type_normalized",
    "district_raw",
    "district_normalized",
    "administration_raw",
    "administration_normalized",
    "visit_type_raw",
    "visit_type_normalized",
    "visit_date_raw",
    "visit_date",
    "report_publication_date_raw",
    "report_publication_date",
    "raw_fields_json",
    "normalized_fields_json",
    "field_evidence_json",
    "warnings_json",
    "parse_diagnostics_json",
]


def export_reports_from_metadata(
    *,
    metadata_path: Path,
    metadata_diagnostics_path: Path,
    output_dir: Path,
) -> ExportRunDiagnostics:
    """Validate PR 5 metadata and write local canonical report exports."""
    jsonl_output_path = output_dir / "reports.jsonl"
    csv_output_path = output_dir / "reports.csv"
    diagnostics_path = output_dir / "export_diagnostics.json"
    run_diagnostics = ExportRunDiagnostics(
        metadata_path=str(metadata_path),
        metadata_diagnostics_path=str(metadata_diagnostics_path),
        output_dir=str(output_dir),
        jsonl_output_path=str(jsonl_output_path),
        csv_output_path=str(csv_output_path),
    )

    parse_diagnostics_by_report: dict[
        str,
        list[MetadataParseRecordDiagnostic],
    ] = {}
    try:
        metadata_diagnostics = MetadataParseRunDiagnostics.model_validate_json(
            metadata_diagnostics_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        run_diagnostics.notes.append(
            f"Metadata diagnostics could not be read or validated: {exc}"
        )
        metadata_diagnostics = None

    if metadata_diagnostics is not None:
        for diagnostic in metadata_diagnostics.record_diagnostics:
            if diagnostic.report_id:
                parse_diagnostics_by_report.setdefault(
                    diagnostic.report_id,
                    [],
                ).append(diagnostic)

    seen_report_ids: set[str] = set()
    exported_rows: list[CanonicalReportRow] = []
    for line_number, line in _iter_jsonl_lines(metadata_path):
        run_diagnostics.total_records += 1
        report_id = _extract_optional_id(line, "report_id")
        source_document_id = _extract_optional_id(line, "source_document_id")
        base_diagnostic = ExportRecordDiagnostic(
            line_number=line_number,
            report_id=report_id,
            source_document_id=source_document_id,
            status="pending",
        )

        try:
            metadata_record = ReportMetadataRecord.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            base_diagnostic.status = "validation_failed"
            base_diagnostic.errors.extend(_validation_errors(exc))
            run_diagnostics.validation_failed_records += 1
            run_diagnostics.record_diagnostics.append(base_diagnostic)
            continue

        if metadata_record.report_id in seen_report_ids:
            base_diagnostic.status = "duplicate_report_id"
            base_diagnostic.errors.append(
                f"Duplicate report_id {metadata_record.report_id!r}."
            )
            run_diagnostics.duplicate_id_records += 1
            run_diagnostics.record_diagnostics.append(base_diagnostic)
            continue
        seen_report_ids.add(metadata_record.report_id)

        try:
            row = canonical_report_row_from_metadata(
                metadata_record,
                parse_diagnostics_by_report.get(metadata_record.report_id, []),
            )
        except ValidationError as exc:
            base_diagnostic.status = "validation_failed"
            base_diagnostic.errors.extend(_validation_errors(exc))
            run_diagnostics.validation_failed_records += 1
            run_diagnostics.record_diagnostics.append(base_diagnostic)
            continue

        base_diagnostic.status = "exported"
        base_diagnostic.exported = True
        base_diagnostic.warnings.extend(
            warning.message for warning in metadata_record.warnings
        )
        exported_rows.append(row)
        run_diagnostics.exported_records += 1
        run_diagnostics.record_diagnostics.append(base_diagnostic)

    write_report_jsonl(jsonl_output_path, exported_rows)
    write_report_csv(csv_output_path, exported_rows)
    run_diagnostics.diagnostic_records = len(run_diagnostics.record_diagnostics)
    run_diagnostics.finished_at = utc_now()
    write_export_diagnostics(diagnostics_path, run_diagnostics)
    logger.info(
        "export_complete",
        records=run_diagnostics.total_records,
        exported=run_diagnostics.exported_records,
        validation_failed=run_diagnostics.validation_failed_records,
        duplicates=run_diagnostics.duplicate_id_records,
    )
    return run_diagnostics


def canonical_report_row_from_metadata(
    metadata_record: ReportMetadataRecord,
    parse_diagnostics: list[MetadataParseRecordDiagnostic],
) -> CanonicalReportRow:
    """Flatten one PR 5 metadata record into the canonical report row contract."""
    fields = metadata_record.fields
    raw_fields = {
        field_name: field.raw_value for field_name, field in sorted(fields.items())
    }
    normalized_fields = {
        field_name: field.normalized_value
        for field_name, field in sorted(fields.items())
    }

    row = CanonicalReportRow(
        report_id=metadata_record.report_id,
        source_document_id=metadata_record.source_document_id,
        govil_item_slug=metadata_record.govil_item_slug,
        govil_item_url=metadata_record.govil_item_url,
        pdf_url=metadata_record.pdf_url,
        title=metadata_record.title,
        language_path=metadata_record.language_path,
        pdf_sha256=metadata_record.pdf_sha256,
        local_path=metadata_record.local_path,
        text_path=metadata_record.text_path,
        page_count=metadata_record.page_count,
        extraction_status=metadata_record.extraction_status,
        extraction_confidence=metadata_record.extraction_confidence,
        parsed_at=metadata_record.parsed_at,
        facility_name_raw=_raw(fields, "facility_name"),
        facility_name_normalized=_normalized_str(fields, "facility_name"),
        facility_id_raw=_raw(fields, "facility_id"),
        facility_id_normalized=_normalized_str(fields, "facility_id"),
        facility_type_raw=_raw(fields, "facility_type"),
        facility_type_normalized=_normalized_str(fields, "facility_type"),
        district_raw=_raw(fields, "district"),
        district_normalized=_normalized_str(fields, "district"),
        administration_raw=_raw(fields, "administration"),
        administration_normalized=_normalized_str(fields, "administration"),
        visit_type_raw=_raw(fields, "visit_type"),
        visit_type_normalized=_normalized_str(fields, "visit_type"),
        visit_date_raw=_raw(fields, "visit_date"),
        visit_date=_normalized_date(fields, "visit_date"),
        report_publication_date_raw=_raw(fields, "report_publication_date"),
        report_publication_date=_normalized_date(
            fields,
            "report_publication_date",
        ),
        raw_fields=raw_fields,
        normalized_fields=normalized_fields,
        field_evidence=fields,
        warnings=metadata_record.warnings,
        parse_diagnostics=[
            diagnostic.model_dump(mode="json") for diagnostic in parse_diagnostics
        ],
    )
    return CanonicalReportRow.model_validate(row.model_dump())


def write_report_jsonl(path: Path, rows: list[CanonicalReportRow]) -> None:
    lines = [row.model_dump_json() for row in rows]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def write_report_csv(path: Path, rows: list[CanonicalReportRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row))
    temporary_path.replace(path)


def _iter_jsonl_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if line.strip():
            lines.append((line_number, line))
    return lines


def _csv_row(row: CanonicalReportRow) -> dict[str, str | int | float | None]:
    payload = row.model_dump(mode="json")
    csv_payload = {column: payload.get(column) for column in REPORT_CSV_COLUMNS}
    csv_payload["raw_fields_json"] = _json_cell(row.raw_fields)
    csv_payload["normalized_fields_json"] = _json_cell(row.normalized_fields)
    csv_payload["field_evidence_json"] = _json_cell(row.field_evidence)
    csv_payload["warnings_json"] = _json_cell(row.warnings)
    csv_payload["parse_diagnostics_json"] = _json_cell(row.parse_diagnostics)
    return csv_payload


def _json_cell(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, MetadataField):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _raw(fields: dict[str, MetadataField], field_name: str) -> str | None:
    field = fields.get(field_name)
    return field.raw_value if field else None


def _normalized_str(fields: dict[str, MetadataField], field_name: str) -> str | None:
    field = fields.get(field_name)
    if field is None or field.normalized_value is None:
        return None
    if isinstance(field.normalized_value, date):
        return field.normalized_value.isoformat()
    return str(field.normalized_value)


def _normalized_date(
    fields: dict[str, MetadataField],
    field_name: str,
) -> Any:
    field = fields.get(field_name)
    if field is None or field.normalized_value is None:
        return None
    return field.normalized_value


def _extract_optional_id(line: str, field_name: str) -> str | None:
    try:
        value = json.loads(line).get(field_name)
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
    return [str(exc)]
