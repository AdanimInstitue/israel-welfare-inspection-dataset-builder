"""Manual embedded PDF text extraction and diagnostics."""

from __future__ import annotations

from pathlib import Path

import fitz
import structlog
from pypdf import PdfReader

from welfare_inspections.collect.manifest import (
    read_source_manifest,
    write_text_extraction_diagnostics,
)
from welfare_inspections.collect.models import (
    SourceDocumentRecord,
    TextExtractionRecordDiagnostic,
    TextExtractionRunDiagnostics,
    TextPageDiagnostic,
    utc_now,
)
from welfare_inspections.text_normalization import normalize_extracted_text

logger = structlog.get_logger(__name__)


def extract_embedded_text_from_manifest(
    *,
    source_manifest_path: Path,
    text_output_dir: Path,
    diagnostics_path: Path,
    overwrite: bool = False,
) -> TextExtractionRunDiagnostics:
    """Extract embedded text from downloaded PDFs listed in a manifest."""
    records = read_source_manifest(source_manifest_path)
    diagnostics = TextExtractionRunDiagnostics(
        source_manifest_path=str(source_manifest_path),
        text_output_dir=str(text_output_dir),
        total_records=len(records),
    )

    for record in records:
        record_diagnostic = _extract_record(
            record=record,
            text_output_dir=text_output_dir,
            overwrite=overwrite,
        )
        diagnostics.record_diagnostics.append(record_diagnostic)
        if record_diagnostic.status == "extracted":
            diagnostics.extracted_records += 1
        elif record_diagnostic.status == "skipped_existing":
            diagnostics.skipped_existing_records += 1
        elif record_diagnostic.status == "missing_pdf":
            diagnostics.failed_records += 1
            diagnostics.missing_pdf_records += 1
        elif record_diagnostic.status == "missing_local_path":
            diagnostics.failed_records += 1
            diagnostics.missing_local_path_records += 1
        else:
            diagnostics.failed_records += 1
        if record_diagnostic.warnings:
            diagnostics.warning_records += 1

    diagnostics.finished_at = utc_now()
    write_text_extraction_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "pdf_text_extraction_complete",
        records=diagnostics.total_records,
        extracted=diagnostics.extracted_records,
        failed=diagnostics.failed_records,
    )
    return diagnostics


def _extract_record(
    *,
    record: SourceDocumentRecord,
    text_output_dir: Path,
    overwrite: bool,
) -> TextExtractionRecordDiagnostic:
    diagnostic = _base_record_diagnostic(record)
    if not record.local_path:
        return diagnostic.model_copy(
            update={
                "status": "missing_local_path",
                "error": "manifest_record_has_no_local_path",
            }
        )

    pdf_path = Path(record.local_path)
    diagnostic.local_path = str(pdf_path)
    if not pdf_path.exists():
        return diagnostic.model_copy(
            update={"status": "missing_pdf", "error": "local_pdf_not_found"}
        )

    text_path = text_output_dir / f"{record.source_document_id}.txt"
    diagnostic.text_path = str(text_path)
    if text_path.exists() and not overwrite:
        diagnostic.warnings.append("existing_text_output_not_overwritten")
        diagnostic.status = "skipped_existing"
        return diagnostic

    try:
        page_count, metadata = pdf_page_count_and_metadata(pdf_path)
        diagnostic.page_count = page_count
        diagnostic.pdf_metadata = metadata
    except Exception as exc:
        return diagnostic.model_copy(
            update={"status": "failed", "error": f"pdf_metadata_error:{exc}"}
        )

    try:
        pages = extract_pdf_pages(pdf_path)
    except Exception as exc:
        return diagnostic.model_copy(
            update={"status": "failed", "error": f"pdf_text_error:{exc}"}
        )

    chunks: list[str] = []
    for page_number, raw_text in enumerate(pages, 1):
        normalized_text = normalize_extracted_text(raw_text)
        page_status = "extracted" if normalized_text else "empty_text"
        warning = None if normalized_text else "no_embedded_text_on_page"
        if warning:
            diagnostic.warnings.append(warning)
        diagnostic.pages.append(
            TextPageDiagnostic(
                page_number=page_number,
                status=page_status,
                raw_char_count=len(raw_text),
                normalized_char_count=len(normalized_text),
                warning=warning,
            )
        )
        if normalized_text:
            chunks.append(f"--- page {page_number} ---\n{normalized_text}")

    diagnostic.raw_char_count = sum(len(page) for page in pages)
    output_text = "\n\n".join(chunks).strip()
    diagnostic.normalized_char_count = len(output_text)
    if not output_text:
        diagnostic.status = "failed"
        diagnostic.error = "no_embedded_text_extracted"
        return diagnostic

    if not text_path.exists() or overwrite:
        _write_text(text_path, output_text + "\n")
    diagnostic.status = "extracted"
    return diagnostic


def pdf_page_count_and_metadata(path: Path) -> tuple[int, dict[str, str]]:
    """Read page count and document metadata using pypdf."""
    reader = PdfReader(path)
    metadata: dict[str, str] = {}
    if reader.metadata:
        metadata = {
            str(key).lstrip("/"): str(value)
            for key, value in reader.metadata.items()
            if value is not None
        }
    return len(reader.pages), metadata


def extract_pdf_pages(path: Path) -> list[str]:
    """Extract embedded page text with PyMuPDF."""
    pages: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            pages.append(page.get_text("text"))
    return pages


def _base_record_diagnostic(
    record: SourceDocumentRecord,
) -> TextExtractionRecordDiagnostic:
    return TextExtractionRecordDiagnostic(
        source_document_id=record.source_document_id,
        govil_item_slug=record.govil_item_slug,
        govil_item_url=record.govil_item_url,
        pdf_url=record.pdf_url,
        title=record.title,
        language_path=record.language_path,
        pdf_sha256=record.pdf_sha256,
        local_path=record.local_path,
        status="pending",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)
