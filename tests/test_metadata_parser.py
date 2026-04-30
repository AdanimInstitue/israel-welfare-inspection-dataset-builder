from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from welfare_inspections import cli
from welfare_inspections.collect.manifest import (
    read_text_extraction_diagnostics,
    write_text_extraction_diagnostics,
)
from welfare_inspections.collect.metadata_parser import (
    _extraction_confidence,
    parse_metadata_from_text_diagnostics,
    parse_numeric_date,
    split_extracted_pages,
)
from welfare_inspections.collect.models import (
    TextExtractionRecordDiagnostic,
    TextExtractionRunDiagnostics,
)


def test_parse_metadata_success_preserves_provenance_and_evidence(
    tmp_path: Path,
) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-success",
        """--- page 1 ---
שם המסגרת: בית חם
סמל מסגרת: 12345
סוג מסגרת: פנימיה
מחוז: תל אביב
מינהל: מוגבלויות
סוג ביקור: ביקורת פתע
תאריך ביקור: 01/02/2024
תאריך פרסום: 05.03.2024
""",
    )
    diagnostics_path = _write_diagnostics(tmp_path, [_diagnostic("success", text_path)])

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    rows = _read_jsonl(tmp_path / "metadata.jsonl")
    fields = rows[0]["fields"]
    assert diagnostics.parsed_records == 1
    assert diagnostics.failed_records == 0
    assert rows[0]["source_document_id"] == "source-doc-success"
    assert rows[0]["govil_item_url"] == "https://www.gov.il/item/success"
    assert rows[0]["pdf_url"] == "https://www.gov.il/success.pdf"
    assert rows[0]["pdf_sha256"] == "sha-success"
    assert rows[0]["page_count"] == 1
    assert rows[0]["extraction_status"] == "extracted"
    assert rows[0]["extraction_confidence"] == 0.95
    assert fields["facility_name"]["raw_value"] == "בית חם"
    assert fields["facility_name"]["normalized_value"] == "בית חם"
    assert fields["facility_id"]["normalized_value"] == "12345"
    assert fields["facility_type"]["raw_value"] == "פנימיה"
    assert fields["facility_type"]["normalized_value"] == "פנימייה"
    assert fields["visit_type"]["normalized_value"] == "פתע"
    assert fields["visit_date"]["normalized_value"] == "2024-02-01"
    assert fields["report_publication_date"]["normalized_value"] == "2024-03-05"
    assert fields["district"]["raw_excerpt"] == "מחוז: תל אביב"
    assert fields["district"]["page_number"] == 1


def test_parse_metadata_records_missing_fields_as_warnings(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-missing",
        "--- page 1 ---\nשם המסגרת: בית חלקי\nתאריך ביקור: 10/01/2024\n",
    )
    diagnostics_path = _write_diagnostics(tmp_path, [_diagnostic("missing", text_path)])

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    rows = _read_jsonl(tmp_path / "metadata.jsonl")
    warning_messages = [warning["message"] for warning in rows[0]["warnings"]]
    assert diagnostics.parsed_records == 1
    assert diagnostics.warning_records == 1
    assert rows[0]["fields"]["facility_name"]["raw_value"] == "בית חלקי"
    assert "No deterministic facility_id value found in extracted text." in (
        warning_messages
    )
    assert (
        "No deterministic report_publication_date value found in extracted text."
        in warning_messages
    )


def test_parse_metadata_records_malformed_date_warning(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-bad-date",
        "--- page 1 ---\nשם המסגרת: בית\nתאריך ביקור: 32/13/2024\n",
    )
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("bad-date", text_path)],
    )

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    rows = _read_jsonl(tmp_path / "metadata.jsonl")
    visit_date = rows[0]["fields"]["visit_date"]
    assert visit_date["raw_value"] == "32/13/2024"
    assert visit_date["normalized_value"] is None
    assert visit_date["confidence"] == 0.2
    assert visit_date["warnings"] == ["malformed_date"]
    assert any(
        warning["raw_excerpt"] == "תאריך ביקור: 32/13/2024"
        for warning in rows[0]["warnings"]
    )


def test_parse_metadata_finds_multi_page_excerpts(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-pages",
        """--- page 1 ---
שם המסגרת: בית רב דפי
--- page 2 ---
מחוז: ירושלים
סוג ביקור: מעקב
""",
    )
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("pages", text_path, 2)],
    )

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    fields = _read_jsonl(tmp_path / "metadata.jsonl")[0]["fields"]
    assert fields["facility_name"]["page_number"] == 1
    assert fields["district"]["page_number"] == 2
    assert fields["visit_type"]["raw_excerpt"] == "סוג ביקור: מעקב"


def test_parse_metadata_handles_unavailable_extraction_as_diagnostic(
    tmp_path: Path,
) -> None:
    source_diagnostic = _diagnostic("failed", None)
    source_diagnostic.status = "failed"
    source_diagnostic.error = "no_embedded_text_extracted"
    diagnostics_path = _write_diagnostics(tmp_path, [source_diagnostic])

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    payload = json.loads(
        (tmp_path / "metadata-diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics.parsed_records == 0
    assert diagnostics.failed_records == 1
    assert (tmp_path / "metadata.jsonl").read_text(encoding="utf-8") == ""
    assert payload["record_diagnostics"][0]["status"] == "failed"
    assert payload["record_diagnostics"][0]["warnings"][0]["message"].startswith(
        "Cannot parse metadata when extraction status"
    )


def test_parse_metadata_records_missing_text_path_as_diagnostic(
    tmp_path: Path,
) -> None:
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("missing-text-path", None)],
    )

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    payload = json.loads(
        (tmp_path / "metadata-diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics.failed_records == 1
    assert payload["record_diagnostics"][0]["status"] == "failed"
    assert payload["record_diagnostics"][0]["error"] == "missing_text_path"
    assert payload["record_diagnostics"][0]["warnings"][0]["message"] == (
        "Cannot parse metadata because the extraction diagnostics have no text_path."
    )


def test_parse_metadata_records_missing_text_file_as_diagnostic(
    tmp_path: Path,
) -> None:
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("missing-text-file", tmp_path / "missing.txt")],
    )

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    payload = json.loads(
        (tmp_path / "metadata-diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics.failed_records == 1
    assert payload["record_diagnostics"][0]["status"] == "failed"
    assert payload["record_diagnostics"][0]["error"] == "text_file_not_found"
    assert payload["record_diagnostics"][0]["warnings"][0]["message"].startswith(
        "Cannot parse metadata because text file was not found:"
    )


def test_parse_metadata_records_unreadable_text_and_continues(
    tmp_path: Path,
) -> None:
    bad_text_path = tmp_path / "source-doc-bad-text.txt"
    bad_text_path.write_bytes(b"\xff\xfe\x00")
    good_text_path = _write_text(
        tmp_path,
        "source-doc-good-text",
        "--- page 1 ---\nשם המסגרת: בית תקין\nסמל מסגרת: 12345\n",
    )
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [
            _diagnostic("bad-text", bad_text_path),
            _diagnostic("good-text", good_text_path),
        ],
    )

    diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    rows = _read_jsonl(tmp_path / "metadata.jsonl")
    payload = json.loads(
        (tmp_path / "metadata-diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics.parsed_records == 1
    assert diagnostics.failed_records == 1
    assert rows[0]["source_document_id"] == "source-doc-good-text"
    assert payload["record_diagnostics"][0]["status"] == "failed"
    assert payload["record_diagnostics"][0]["error"] == "text_file_unreadable"
    assert payload["record_diagnostics"][1]["status"] == "parsed"


def test_parse_metadata_warns_on_ambiguous_facility_id(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-ambiguous-id",
        "--- page 1 ---\nשם המסגרת: בית\nסמל מסגרת: 123 / 456\n",
    )
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("ambiguous-id", text_path)],
    )

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    facility_id = _read_jsonl(tmp_path / "metadata.jsonl")[0]["fields"]["facility_id"]
    assert facility_id["raw_value"] == "123 / 456"
    assert facility_id["normalized_value"] is None
    assert facility_id["confidence"] == 0.2
    assert facility_id["warnings"] == ["ambiguous_facility_id"]


def test_parse_metadata_allows_single_embedded_facility_id(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-single-id",
        "--- page 1 ---\nשם המסגרת: בית\nסמל מסגרת: מסגרת 12345\n",
    )
    diagnostics_path = _write_diagnostics(
        tmp_path,
        [_diagnostic("single-id", text_path)],
    )

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    facility_id = _read_jsonl(tmp_path / "metadata.jsonl")[0]["fields"]["facility_id"]
    assert facility_id["raw_value"] == "מסגרת 12345"
    assert facility_id["normalized_value"] == "12345"
    assert facility_id["warnings"] == []


def test_parse_metadata_lowers_extraction_confidence_for_warnings(
    tmp_path: Path,
) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-extraction-warning",
        "--- page 1 ---\nשם המסגרת: בית\n",
    )
    source_diagnostic = _diagnostic("extraction-warning", text_path)
    source_diagnostic.warnings.append("no_embedded_text_on_page")
    diagnostics_path = _write_diagnostics(tmp_path, [source_diagnostic])

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    row = _read_jsonl(tmp_path / "metadata.jsonl")[0]
    assert row["extraction_confidence"] == 0.75


def test_parse_metadata_records_skipped_existing_confidence(tmp_path: Path) -> None:
    text_path = _write_text(
        tmp_path,
        "source-doc-skipped-existing",
        "--- page 1 ---\nשם המסגרת: בית\n",
    )
    source_diagnostic = _diagnostic("skipped-existing", text_path)
    source_diagnostic.status = "skipped_existing"
    diagnostics_path = _write_diagnostics(tmp_path, [source_diagnostic])

    parse_metadata_from_text_diagnostics(
        text_diagnostics_path=diagnostics_path,
        output_path=tmp_path / "metadata.jsonl",
        diagnostics_path=tmp_path / "metadata-diagnostics.json",
    )

    row = _read_jsonl(tmp_path / "metadata.jsonl")[0]
    assert row["extraction_status"] == "skipped_existing"
    assert row["extraction_confidence"] == 0.65


def test_extraction_confidence_is_zero_for_unparseable_status() -> None:
    source_diagnostic = _diagnostic("confidence-failed", None)
    source_diagnostic.status = "failed"

    assert _extraction_confidence(source_diagnostic) == 0.0


def test_split_extracted_pages_without_markers_preserves_unknown_page() -> None:
    pages = split_extracted_pages("שם המסגרת: ללא סימון")

    assert len(pages) == 1
    assert pages[0].page_number is None
    assert pages[0].text == "שם המסגרת: ללא סימון"


def test_parse_numeric_date_is_deterministic() -> None:
    assert parse_numeric_date("1/2/24").isoformat() == "2024-02-01"
    assert parse_numeric_date("31.12.2024").isoformat() == "2024-12-31"
    assert parse_numeric_date("32/13/2024") is None
    assert parse_numeric_date("ינואר 2024") is None


def test_read_text_extraction_diagnostics_rejects_invalid_json(tmp_path: Path) -> None:
    diagnostics_path = tmp_path / "bad-diagnostics.json"
    diagnostics_path.write_text("{not-json", encoding="utf-8")

    try:
        read_text_extraction_diagnostics(diagnostics_path)
    except ValueError as exc:
        assert str(exc) == (
            f"Invalid text extraction diagnostics JSON at {diagnostics_path}"
        )
    else:
        raise AssertionError("expected invalid diagnostics to raise ValueError")


def test_cli_parse_metadata_invokes_metadata_parser(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_parse_metadata_from_text_diagnostics(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleMetadataDiagnostics()

    monkeypatch.setattr(
        cli,
        "parse_metadata_from_text_diagnostics",
        fake_parse_metadata_from_text_diagnostics,
    )

    cli.parse_metadata(
        text_diagnostics=tmp_path / "text.json",
        output=tmp_path / "metadata.jsonl",
        diagnostics=tmp_path / "diagnostics.json",
    )

    assert calls[0]["text_diagnostics_path"] == tmp_path / "text.json"
    assert calls[0]["output_path"] == tmp_path / "metadata.jsonl"
    assert calls[0]["diagnostics_path"] == tmp_path / "diagnostics.json"
    assert "Processed 3 text records" in capsys.readouterr().out


def test_cli_parse_metadata_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "parse-metadata", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "top-level report metadata" in result.stdout


def _write_text(tmp_path: Path, source_document_id: str, text: str) -> Path:
    text_path = tmp_path / f"{source_document_id}.txt"
    text_path.write_text(text.strip() + "\n", encoding="utf-8")
    return text_path


def _write_diagnostics(
    tmp_path: Path,
    records: list[TextExtractionRecordDiagnostic],
) -> Path:
    diagnostics_path = tmp_path / "text-diagnostics.json"
    write_text_extraction_diagnostics(
        diagnostics_path,
        TextExtractionRunDiagnostics(
            source_manifest_path=str(tmp_path / "download_manifest.jsonl"),
            text_output_dir=str(tmp_path),
            total_records=len(records),
            extracted_records=sum(record.status == "extracted" for record in records),
            failed_records=sum(record.status == "failed" for record in records),
            warning_records=sum(bool(record.warnings) for record in records),
            record_diagnostics=records,
        ),
    )
    return diagnostics_path


def _diagnostic(
    name: str,
    text_path: Path | None,
    page_count: int = 1,
) -> TextExtractionRecordDiagnostic:
    return TextExtractionRecordDiagnostic(
        source_document_id=f"source-doc-{name}",
        govil_item_slug=name,
        govil_item_url=f"https://www.gov.il/item/{name}",
        pdf_url=f"https://www.gov.il/{name}.pdf",
        title=f"Report {name}",
        language_path="/he/",
        pdf_sha256=f"sha-{name}",
        local_path=f"/tmp/{name}.pdf",
        status="extracted",
        text_path=str(text_path) if text_path else None,
        page_count=page_count,
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class SimpleMetadataDiagnostics:
    total_records = 3
    parsed_records = 2
    failed_records = 1
    warning_records = 1
