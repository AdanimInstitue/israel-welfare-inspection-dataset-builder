from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz

from welfare_inspections import cli
from welfare_inspections.collect.manifest import write_source_manifest
from welfare_inspections.collect.models import SourceDocumentRecord
from welfare_inspections.collect.pdf_download import sha256_file
from welfare_inspections.collect.pdf_text import (
    extract_embedded_text_from_manifest,
    extract_pdf_pages,
    pdf_page_count_and_metadata,
)
from welfare_inspections.text_normalization import (
    cleanup_whitespace,
    normalize_extracted_text,
    normalize_hebrew_geresh_gershayim,
    normalize_punctuation_variants,
    remove_zero_width_and_controls,
)


def test_normalize_extracted_text_handles_hebrew_punctuation_and_whitespace() -> None:
    raw = "\ufeffדו\"ח\u200f  מס'\u00a0  12\u2026\r\n\n\nמקף\u2013ארוך"

    normalized = normalize_extracted_text(raw)

    assert normalized == "דו״ח מס׳ 12...\n\nמקף-ארוך"


def test_normalization_helpers_are_individually_deterministic() -> None:
    assert remove_zero_width_and_controls("א\u200bב\x00ג") == "אבג"
    assert normalize_punctuation_variants("“x”—‘y’") == '"x"-\'y\''
    assert normalize_hebrew_geresh_gershayim('דו"ח מס\'') == "דו״ח מס׳"
    assert cleanup_whitespace("  a\t b \n\n\n c  ") == "a b\n\nc"


def test_extract_embedded_text_success_writes_text_and_diagnostics(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["Hello page one"])
    record = _record("one", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    diagnostics_path = tmp_path / "diagnostics.json"
    text_output_dir = tmp_path / "texts"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=text_output_dir,
        diagnostics_path=diagnostics_path,
    )

    text_path = text_output_dir / f"{record.source_document_id}.txt"
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics.extracted_records == 1
    assert diagnostics.failed_records == 0
    assert text_path.read_text(encoding="utf-8") == "--- page 1 ---\nHello page one\n"
    assert payload["record_diagnostics"][0]["source_document_id"] == (
        record.source_document_id
    )
    assert payload["record_diagnostics"][0]["pdf_url"] == record.pdf_url
    assert payload["record_diagnostics"][0]["pdf_sha256"] == record.pdf_sha256
    assert payload["record_diagnostics"][0]["page_count"] == 1
    assert payload["record_diagnostics"][0]["pdf_metadata"]["Title"] == "Synthetic"


def test_extract_embedded_text_handles_multiple_pages(tmp_path: Path) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "multi.pdf", ["First page", "Second page"])
    record = _record("multi", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    record_diagnostic = diagnostics.record_diagnostics[0]
    text = Path(record_diagnostic.text_path or "").read_text(encoding="utf-8")
    assert record_diagnostic.page_count == 2
    assert [page.status for page in record_diagnostic.pages] == [
        "extracted",
        "extracted",
    ]
    assert "--- page 1 ---\nFirst page" in text
    assert "--- page 2 ---\nSecond page" in text


def test_extract_embedded_text_records_missing_pdf_diagnostic(tmp_path: Path) -> None:
    record = _record("missing", tmp_path / "missing.pdf")
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    assert diagnostics.failed_records == 1
    assert diagnostics.missing_pdf_records == 1
    assert diagnostics.missing_local_path_records == 0
    assert diagnostics.record_diagnostics[0].status == "missing_pdf"
    assert diagnostics.record_diagnostics[0].error == "local_pdf_not_found"


def test_extract_embedded_text_records_missing_local_path(tmp_path: Path) -> None:
    record = _record("no-local-path", None)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    assert diagnostics.failed_records == 1
    assert diagnostics.missing_pdf_records == 0
    assert diagnostics.missing_local_path_records == 1
    assert diagnostics.record_diagnostics[0].status == "missing_local_path"


def test_extract_embedded_text_skips_existing_output_without_overwrite(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["Fresh text"])
    record = _record("existing-output", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    text_output_dir = tmp_path / "texts"
    text_path = text_output_dir / f"{record.source_document_id}.txt"
    text_path.parent.mkdir(parents=True)
    text_path.write_text("stale text\n", encoding="utf-8")
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=text_output_dir,
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    record_diagnostic = diagnostics.record_diagnostics[0]
    assert diagnostics.extracted_records == 0
    assert diagnostics.failed_records == 0
    assert diagnostics.skipped_existing_records == 1
    assert diagnostics.warning_records == 1
    assert record_diagnostic.status == "skipped_existing"
    assert record_diagnostic.warnings == ["existing_text_output_not_overwritten"]
    assert text_path.read_text(encoding="utf-8") == "stale text\n"


def test_extract_embedded_text_overwrites_existing_output_when_requested(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["Fresh text"])
    record = _record("overwrite-output", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    text_output_dir = tmp_path / "texts"
    text_path = text_output_dir / f"{record.source_document_id}.txt"
    text_path.parent.mkdir(parents=True)
    text_path.write_text("stale text\n", encoding="utf-8")
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=text_output_dir,
        diagnostics_path=tmp_path / "diagnostics.json",
        overwrite=True,
    )

    assert diagnostics.extracted_records == 1
    assert diagnostics.skipped_existing_records == 0
    assert text_path.read_text(encoding="utf-8") == "--- page 1 ---\nFresh text\n"


def test_extract_embedded_text_records_unreadable_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a pdf")
    record = _record("broken", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    assert diagnostics.failed_records == 1
    assert diagnostics.record_diagnostics[0].status == "failed"
    assert diagnostics.record_diagnostics[0].error
    assert diagnostics.record_diagnostics[0].error.startswith("pdf_metadata_error:")


def test_extract_embedded_text_records_pdf_text_extraction_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "text-error.pdf", ["Embedded text"])
    record = _record("text-error", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    def fail_extract_pdf_pages(_path: Path) -> list[str]:
        raise ValueError("text extraction failed")

    monkeypatch.setattr(
        "welfare_inspections.collect.pdf_text.extract_pdf_pages",
        fail_extract_pdf_pages,
    )

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    assert diagnostics.failed_records == 1
    assert diagnostics.record_diagnostics[0].status == "failed"
    assert diagnostics.record_diagnostics[0].error == (
        "pdf_text_error:text extraction failed"
    )


def test_extract_embedded_text_records_empty_page_warning(tmp_path: Path) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "empty-page.pdf", ["", "Text page"])
    record = _record("empty-page", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    record_diagnostic = diagnostics.record_diagnostics[0]
    assert diagnostics.extracted_records == 1
    assert diagnostics.warning_records == 1
    assert record_diagnostic.warnings == ["no_embedded_text_on_page"]
    assert [page.status for page in record_diagnostic.pages] == [
        "empty_text",
        "extracted",
    ]


def test_extract_embedded_text_fails_when_no_pages_have_text(tmp_path: Path) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "image-only.pdf", [""])
    record = _record("image-only", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    record_diagnostic = diagnostics.record_diagnostics[0]
    assert diagnostics.failed_records == 1
    assert diagnostics.warning_records == 1
    assert record_diagnostic.status == "failed"
    assert record_diagnostic.error == "no_embedded_text_extracted"
    assert record_diagnostic.warnings == ["no_embedded_text_on_page"]


def test_extract_embedded_text_uses_download_manifest_records(tmp_path: Path) -> None:
    good_pdf = _synthetic_pdf(tmp_path / "good.pdf", ["Good"])
    records = [_record("good", good_pdf), _record("missing", tmp_path / "missing.pdf")]
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, records)

    diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=manifest_path,
        text_output_dir=tmp_path / "texts",
        diagnostics_path=tmp_path / "diagnostics.json",
    )

    assert diagnostics.total_records == 2
    assert diagnostics.extracted_records == 1
    assert diagnostics.failed_records == 1
    assert [
        record_diagnostic.source_document_id
        for record_diagnostic in diagnostics.record_diagnostics
    ] == ["source-doc-good", "source-doc-missing"]


def test_pdf_metadata_and_page_text_helpers_use_deterministic_libraries(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "helpers.pdf", ["A", "B"])

    page_count, metadata = pdf_page_count_and_metadata(pdf_path)
    pages = extract_pdf_pages(pdf_path)

    assert page_count == 2
    assert metadata["Title"] == "Synthetic"
    assert pages == ["A\n", "B\n"]


def test_cli_parse_invokes_text_extraction(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_extract_embedded_text_from_manifest(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleTextDiagnostics()

    monkeypatch.setattr(
        cli,
        "extract_embedded_text_from_manifest",
        fake_extract_embedded_text_from_manifest,
    )

    cli.parse(
        source_manifest=tmp_path / "download.jsonl",
        text_output_dir=tmp_path / "texts",
        diagnostics=tmp_path / "diagnostics.json",
        overwrite=True,
    )

    assert calls[0]["source_manifest_path"] == tmp_path / "download.jsonl"
    assert calls[0]["text_output_dir"] == tmp_path / "texts"
    assert calls[0]["diagnostics_path"] == tmp_path / "diagnostics.json"
    assert calls[0]["overwrite"] is True
    assert "Processed 2 source records" in capsys.readouterr().out


def test_cli_parse_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "parse", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "embedded text" in result.stdout


def _synthetic_pdf(path: Path, page_texts: list[str]) -> Path:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.set_metadata({"title": "Synthetic"})
    document.save(path)
    document.close()
    return path


def _record(name: str, pdf_path: Path | None) -> SourceDocumentRecord:
    pdf_sha256 = sha256_file(pdf_path) if pdf_path and pdf_path.exists() else None
    return SourceDocumentRecord(
        source_document_id=f"source-doc-{name}",
        govil_item_slug=name,
        govil_item_url=f"https://www.gov.il/item/{name}",
        pdf_url=f"https://www.gov.il/{name}.pdf",
        title=f"Report {name}",
        language_path="/he/",
        pdf_sha256=pdf_sha256,
        local_path=str(pdf_path) if pdf_path else None,
        collector_version="0.1.0",
    )


class SimpleTextDiagnostics:
    total_records = 2
    extracted_records = 1
    failed_records = 1
    warning_records = 1
