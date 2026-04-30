from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from welfare_inspections import cli
from welfare_inspections.collect import export as export_module
from welfare_inspections.collect.export import export_reports_from_metadata
from welfare_inspections.collect.manifest import write_metadata_parse_diagnostics
from welfare_inspections.collect.models import (
    MetadataField,
    MetadataParseRecordDiagnostic,
    MetadataParseRunDiagnostics,
    MetadataParseWarning,
    ReportMetadataRecord,
)


def test_export_writes_valid_jsonl_and_csv_with_provenance(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-success", "report-success")
    metadata_path = _write_metadata(tmp_path, [record.model_dump(mode="json")])
    diagnostics_path = _write_parse_diagnostics(tmp_path, [record])

    diagnostics = export_reports_from_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=diagnostics_path,
        output_dir=tmp_path / "exports",
    )

    jsonl_rows = _read_jsonl(tmp_path / "exports" / "reports.jsonl")
    with (tmp_path / "exports" / "reports.csv").open(encoding="utf-8", newline="") as (
        handle
    ):
        csv_rows = list(csv.DictReader(handle))

    assert diagnostics.exported_records == 1
    assert diagnostics.validation_failed_records == 0
    assert jsonl_rows[0]["report_id"] == "report-success"
    assert jsonl_rows[0]["source_document_id"] == "source-doc-success"
    assert jsonl_rows[0]["govil_item_url"] == "https://www.gov.il/item/success"
    assert jsonl_rows[0]["pdf_url"] == "https://www.gov.il/success.pdf"
    assert jsonl_rows[0]["pdf_sha256"] == "sha-success"
    assert jsonl_rows[0]["page_count"] == 3
    assert jsonl_rows[0]["facility_name_raw"] == "בית חם"
    assert jsonl_rows[0]["facility_name_normalized"] == "בית חם"
    assert jsonl_rows[0]["facility_id_raw"] == "מסגרת 12345"
    assert jsonl_rows[0]["facility_id_normalized"] == "12345"
    assert jsonl_rows[0]["facility_type_raw"] == "פנימיה"
    assert jsonl_rows[0]["facility_type_normalized"] == "פנימייה"
    assert jsonl_rows[0]["visit_date"] == "2024-02-01"
    assert jsonl_rows[0]["report_publication_date"] == "2024-03-05"
    assert jsonl_rows[0]["raw_fields"]["visit_date"] == "01/02/2024"
    assert jsonl_rows[0]["field_evidence"]["visit_date"]["raw_excerpt"] == (
        "תאריך ביקור: 01/02/2024"
    )
    assert jsonl_rows[0]["parse_diagnostics"][0]["status"] == "parsed"
    assert csv_rows[0]["report_id"] == "report-success"
    assert csv_rows[0]["visit_date"] == "2024-02-01"
    assert json.loads(csv_rows[0]["field_evidence_json"])["facility_id"][
        "normalized_value"
    ] == "12345"


def test_export_records_missing_required_fields_as_diagnostics(
    tmp_path: Path,
) -> None:
    payload = _metadata_record("source-doc-missing", "report-missing").model_dump(
        mode="json"
    )
    del payload["report_id"]
    metadata_path = _write_metadata(tmp_path, [payload])
    diagnostics_path = _write_parse_diagnostics(tmp_path, [])

    diagnostics = export_reports_from_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=diagnostics_path,
        output_dir=tmp_path / "exports",
    )

    diagnostic_payload = json.loads(
        (tmp_path / "exports" / "export_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostics.exported_records == 0
    assert diagnostics.validation_failed_records == 1
    assert (tmp_path / "exports" / "reports.jsonl").read_text(encoding="utf-8") == ""
    assert diagnostic_payload["record_diagnostics"][0]["status"] == (
        "validation_failed"
    )
    assert any(
        "report_id" in error
        for error in diagnostic_payload["record_diagnostics"][0]["errors"]
    )


def test_export_records_duplicate_report_ids_as_diagnostics(tmp_path: Path) -> None:
    first = _metadata_record("source-doc-first", "report-duplicate")
    second = _metadata_record("source-doc-second", "report-duplicate")
    metadata_path = _write_metadata(
        tmp_path,
        [first.model_dump(mode="json"), second.model_dump(mode="json")],
    )
    diagnostics_path = _write_parse_diagnostics(tmp_path, [first, second])

    diagnostics = export_reports_from_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=diagnostics_path,
        output_dir=tmp_path / "exports",
    )

    rows = _read_jsonl(tmp_path / "exports" / "reports.jsonl")
    diagnostic_payload = json.loads(
        (tmp_path / "exports" / "export_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostics.exported_records == 1
    assert diagnostics.duplicate_id_records == 1
    assert len(rows) == 1
    assert diagnostic_payload["record_diagnostics"][1]["status"] == (
        "duplicate_report_id"
    )


def test_export_records_malformed_dates_as_validation_diagnostics(
    tmp_path: Path,
) -> None:
    payload = _metadata_record("source-doc-bad-date", "report-bad-date").model_dump(
        mode="json"
    )
    payload["fields"]["visit_date"]["normalized_value"] = "2024-99-99"
    metadata_path = _write_metadata(tmp_path, [payload])
    diagnostics_path = _write_parse_diagnostics(tmp_path, [])

    diagnostics = export_reports_from_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=diagnostics_path,
        output_dir=tmp_path / "exports",
    )

    diagnostic_payload = json.loads(
        (tmp_path / "exports" / "export_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostics.exported_records == 0
    assert diagnostics.validation_failed_records == 1
    assert any(
        "visit_date" in error
        for error in diagnostic_payload["record_diagnostics"][0]["errors"]
    )


def test_export_preserves_warnings_and_parse_diagnostics(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-warn", "report-warn")
    warning = MetadataParseWarning(
        warning_id="warning-1",
        source_document_id=record.source_document_id,
        report_id=record.report_id,
        message="No deterministic district value found in extracted text.",
        page_number=1,
        raw_excerpt="מחוז:",
    )
    record.warnings.append(warning)
    metadata_path = _write_metadata(tmp_path, [record.model_dump(mode="json")])
    diagnostics_path = _write_parse_diagnostics(tmp_path, [record])

    export_reports_from_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=diagnostics_path,
        output_dir=tmp_path / "exports",
    )

    row = _read_jsonl(tmp_path / "exports" / "reports.jsonl")[0]
    export_diagnostics = json.loads(
        (tmp_path / "exports" / "export_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert row["warnings"][0]["message"] == (
        "No deterministic district value found in extracted text."
    )
    assert row["warnings"][0]["raw_excerpt"] == "מחוז:"
    assert row["parse_diagnostics"][0]["warnings"][0]["warning_id"] == "warning-1"
    assert export_diagnostics["record_diagnostics"][0]["warnings"] == [
        "No deterministic district value found in extracted text."
    ]


def test_export_rejects_repo_internal_non_ignored_output_dir(tmp_path: Path) -> None:
    metadata_path = _write_metadata(
        tmp_path,
        [_metadata_record("source-doc-guard", "report-guard").model_dump(mode="json")],
    )
    diagnostics_path = _write_parse_diagnostics(tmp_path, [])

    with pytest.raises(ValueError, match="outputs/"):
        export_reports_from_metadata(
            metadata_path=metadata_path,
            metadata_diagnostics_path=diagnostics_path,
            output_dir=export_module.REPO_ROOT / "docs",
        )


def test_export_fails_closed_when_metadata_diagnostics_missing(
    tmp_path: Path,
) -> None:
    metadata_path = _write_metadata(
        tmp_path,
        [
            _metadata_record(
                "source-doc-missing-diagnostics",
                "report-missing-diagnostics",
            ).model_dump(mode="json")
        ],
    )

    with pytest.raises(ValueError, match="Metadata diagnostics"):
        export_reports_from_metadata(
            metadata_path=metadata_path,
            metadata_diagnostics_path=tmp_path / "missing-diagnostics.json",
            output_dir=tmp_path / "exports",
        )

    assert not (tmp_path / "exports" / "reports.jsonl").exists()
    assert not (tmp_path / "exports" / "reports.csv").exists()
    assert not (tmp_path / "exports" / "export_diagnostics.json").exists()


def test_export_does_not_promote_partial_artifacts_when_staging_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _metadata_record("source-doc-staging", "report-staging")
    metadata_path = _write_metadata(tmp_path, [record.model_dump(mode="json")])
    diagnostics_path = _write_parse_diagnostics(tmp_path, [record])

    def fail_write_report_csv(*args: object, **kwargs: object) -> None:
        raise OSError("simulated csv failure")

    monkeypatch.setattr(export_module, "write_report_csv", fail_write_report_csv)

    with pytest.raises(OSError, match="simulated csv failure"):
        export_reports_from_metadata(
            metadata_path=metadata_path,
            metadata_diagnostics_path=diagnostics_path,
            output_dir=tmp_path / "exports",
        )

    assert not (tmp_path / "exports" / "reports.jsonl").exists()
    assert not (tmp_path / "exports" / "reports.csv").exists()
    assert not (tmp_path / "exports" / "export_diagnostics.json").exists()


def test_cli_export_invokes_exporter(tmp_path: Path, monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_export_reports_from_metadata(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleExportDiagnostics()

    monkeypatch.setattr(
        cli,
        "export_reports_from_metadata",
        fake_export_reports_from_metadata,
    )

    cli.export(
        metadata=tmp_path / "metadata.jsonl",
        metadata_diagnostics=tmp_path / "metadata-diagnostics.json",
        output_dir=tmp_path / "exports",
    )

    assert calls[0]["metadata_path"] == tmp_path / "metadata.jsonl"
    assert calls[0]["metadata_diagnostics_path"] == (
        tmp_path / "metadata-diagnostics.json"
    )
    assert calls[0]["output_dir"] == tmp_path / "exports"
    assert "Processed 3 metadata records" in capsys.readouterr().out


def test_cli_export_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "export", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "local report rows" in result.stdout


def _metadata_record(source_document_id: str, report_id: str) -> ReportMetadataRecord:
    suffix = source_document_id.replace("source-doc-", "")
    return ReportMetadataRecord(
        report_id=report_id,
        source_document_id=source_document_id,
        govil_item_slug=suffix,
        govil_item_url=f"https://www.gov.il/item/{suffix}",
        pdf_url=f"https://www.gov.il/{suffix}.pdf",
        title=f"Report {suffix}",
        language_path="/he/",
        pdf_sha256=f"sha-{suffix}",
        local_path=f"/tmp/{suffix}.pdf",
        text_path=f"/tmp/{suffix}.txt",
        page_count=3,
        extraction_status="extracted",
        extraction_confidence=0.95,
        fields={
            "facility_name": MetadataField(
                field_name="facility_name",
                raw_value="בית חם",
                normalized_value="בית חם",
                raw_excerpt="שם המסגרת: בית חם",
                page_number=1,
                confidence=0.9,
            ),
            "facility_id": MetadataField(
                field_name="facility_id",
                raw_value="מסגרת 12345",
                normalized_value="12345",
                raw_excerpt="סמל מסגרת: מסגרת 12345",
                page_number=1,
                confidence=0.82,
            ),
            "facility_type": MetadataField(
                field_name="facility_type",
                raw_value="פנימיה",
                normalized_value="פנימייה",
                raw_excerpt="סוג מסגרת: פנימיה",
                page_number=1,
                confidence=0.82,
            ),
            "district": MetadataField(
                field_name="district",
                raw_value="תל אביב",
                normalized_value="תל אביב",
                raw_excerpt="מחוז: תל אביב",
                page_number=1,
                confidence=0.9,
            ),
            "administration": MetadataField(
                field_name="administration",
                raw_value="מוגבלויות",
                normalized_value="מוגבלויות",
                raw_excerpt="מינהל: מוגבלויות",
                page_number=1,
                confidence=0.9,
            ),
            "visit_type": MetadataField(
                field_name="visit_type",
                raw_value="ביקורת פתע",
                normalized_value="פתע",
                raw_excerpt="סוג ביקור: ביקורת פתע",
                page_number=1,
                confidence=0.82,
            ),
            "visit_date": MetadataField(
                field_name="visit_date",
                raw_value="01/02/2024",
                normalized_value=date(2024, 2, 1),
                raw_excerpt="תאריך ביקור: 01/02/2024",
                page_number=1,
                confidence=0.9,
            ),
            "report_publication_date": MetadataField(
                field_name="report_publication_date",
                raw_value="05.03.2024",
                normalized_value=date(2024, 3, 5),
                raw_excerpt="תאריך פרסום: 05.03.2024",
                page_number=1,
                confidence=0.9,
            ),
        },
    )


def _write_metadata(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    metadata_path = tmp_path / "metadata.jsonl"
    metadata_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return metadata_path


def _write_parse_diagnostics(
    tmp_path: Path,
    records: list[ReportMetadataRecord],
) -> Path:
    diagnostics_path = tmp_path / "metadata-diagnostics.json"
    write_metadata_parse_diagnostics(
        diagnostics_path,
        MetadataParseRunDiagnostics(
            text_diagnostics_path=str(tmp_path / "text-diagnostics.json"),
            output_path=str(tmp_path / "metadata.jsonl"),
            total_records=len(records),
            parsed_records=len(records),
            record_diagnostics=[
                MetadataParseRecordDiagnostic(
                    source_document_id=record.source_document_id,
                    report_id=record.report_id,
                    status="parsed",
                    text_path=record.text_path,
                    page_count=record.page_count,
                    extraction_status=record.extraction_status,
                    parsed_field_count=len(record.fields),
                    warnings=record.warnings,
                )
                for record in records
            ],
        ),
    )
    return diagnostics_path


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class SimpleExportDiagnostics:
    total_records = 3
    exported_records = 2
    validation_failed_records = 1
    duplicate_id_records = 0
