"""Deterministic top-level metadata parser for extracted report text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

import structlog

from welfare_inspections.collect.manifest import (
    read_text_extraction_diagnostics,
    write_metadata_manifest,
    write_metadata_parse_diagnostics,
)
from welfare_inspections.collect.models import (
    MetadataField,
    MetadataParseRecordDiagnostic,
    MetadataParseRunDiagnostics,
    MetadataParseWarning,
    ReportMetadataRecord,
    TextExtractionRecordDiagnostic,
    utc_now,
)
from welfare_inspections.text_normalization import normalize_extracted_text

logger = structlog.get_logger(__name__)

PAGE_MARKER_RE = re.compile(r"^--- page (?P<page_number>\d+) ---$", re.MULTILINE)
LINE_VALUE_RE_TEMPLATE = r"(?im)^\s*(?:{labels})\s*[:\-–]\s*(?P<value>.+?)\s*$"
DATE_VALUE_RE_TEMPLATE = (
    r"(?im)^\s*(?:{labels})\s*[:\-–]\s*(?P<value>\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}})\s*$"
)

FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "facility_name": ("שם המסגרת", "שם מסגרת", "שם המוסד", "שם מוסד"),
    "facility_id": ("סמל מסגרת", "מספר מסגרת", "קוד מסגרת", "מס׳ מסגרת"),
    "facility_type": ("סוג מסגרת", "סוג המוסד", "סוג שירות", "סוג השירות"),
    "district": ("מחוז",),
    "administration": ("מינהל", "מנהל", "אגף"),
    "visit_type": ("סוג ביקור", "סוג הביקור", "מהות הביקור"),
}
DATE_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "visit_date": ("תאריך ביקור", "מועד ביקור", "תאריך הביקור"),
    "report_publication_date": (
        "תאריך פרסום",
        "מועד פרסום",
        "תאריך הפקת הדוח",
        "תאריך הפקת דו״ח",
        "תאריך הדוח",
        "תאריך דו״ח",
    ),
}

FACILITY_TYPE_NORMALIZATIONS = {
    "פנימיה": "פנימייה",
    "פנימייה": "פנימייה",
    "הוסטל": "הוסטל",
    "מעון": "מעון",
    "דיור מוגן": "דיור מוגן",
}
VISIT_TYPE_NORMALIZATIONS = {
    "ביקורת פתע": "פתע",
    "פתע": "פתע",
    "ביקורת מתואמת": "מתואם",
    "מתואם": "מתואם",
    "מעקב": "מעקב",
}


@dataclass(frozen=True)
class PageText:
    page_number: int | None
    text: str


def parse_metadata_from_text_diagnostics(
    *,
    text_diagnostics_path: Path,
    output_path: Path,
    diagnostics_path: Path,
) -> MetadataParseRunDiagnostics:
    """Parse report-level metadata from PR 4 text outputs and diagnostics."""
    text_diagnostics = read_text_extraction_diagnostics(text_diagnostics_path)
    records: list[ReportMetadataRecord] = []
    run_diagnostics = MetadataParseRunDiagnostics(
        text_diagnostics_path=str(text_diagnostics_path),
        output_path=str(output_path),
        total_records=len(text_diagnostics.record_diagnostics),
    )

    for source_diagnostic in text_diagnostics.record_diagnostics:
        record, record_diagnostic = _parse_record(source_diagnostic)
        run_diagnostics.record_diagnostics.append(record_diagnostic)
        if record is not None:
            records.append(record)
            run_diagnostics.parsed_records += 1
        else:
            run_diagnostics.failed_records += 1
        if record_diagnostic.warnings:
            run_diagnostics.warning_records += 1

    run_diagnostics.finished_at = utc_now()
    write_metadata_manifest(output_path, records)
    write_metadata_parse_diagnostics(diagnostics_path, run_diagnostics)
    logger.info(
        "metadata_parse_complete",
        records=run_diagnostics.total_records,
        parsed=run_diagnostics.parsed_records,
        failed=run_diagnostics.failed_records,
    )
    return run_diagnostics


def _parse_record(
    diagnostic: TextExtractionRecordDiagnostic,
) -> tuple[ReportMetadataRecord | None, MetadataParseRecordDiagnostic]:
    report_id = report_id_from_source_document_id(diagnostic.source_document_id)
    record_diagnostic = MetadataParseRecordDiagnostic(
        source_document_id=diagnostic.source_document_id,
        report_id=report_id,
        status="pending",
        text_path=diagnostic.text_path,
        page_count=diagnostic.page_count,
        extraction_status=diagnostic.status,
    )
    if diagnostic.status not in {"extracted", "skipped_existing"}:
        warning = _warning(
            diagnostic.source_document_id,
            report_id,
            "source_text_not_available",
            f"Cannot parse metadata when extraction status is {diagnostic.status!r}.",
        )
        record_diagnostic.status = "failed"
        record_diagnostic.error = "source_text_not_available"
        record_diagnostic.warnings.append(warning)
        return None, record_diagnostic

    if not diagnostic.text_path:
        warning = _warning(
            diagnostic.source_document_id,
            report_id,
            "missing_text_path",
            (
                "Cannot parse metadata because the extraction diagnostics "
                "have no text_path."
            ),
        )
        record_diagnostic.status = "failed"
        record_diagnostic.error = "missing_text_path"
        record_diagnostic.warnings.append(warning)
        return None, record_diagnostic

    text_path = Path(diagnostic.text_path)
    if not text_path.exists():
        warning = _warning(
            diagnostic.source_document_id,
            report_id,
            "text_file_not_found",
            f"Cannot parse metadata because text file was not found: {text_path}",
        )
        record_diagnostic.status = "failed"
        record_diagnostic.error = "text_file_not_found"
        record_diagnostic.warnings.append(warning)
        return None, record_diagnostic

    pages = split_extracted_pages(text_path.read_text(encoding="utf-8"))
    record = _base_report_record(diagnostic=diagnostic, report_id=report_id)
    record.fields.update(
        parse_metadata_fields(pages, diagnostic.source_document_id, report_id)
    )
    record.warnings.extend(
        _missing_field_warnings(
            diagnostic.source_document_id,
            report_id,
            record.fields,
        )
    )
    record_diagnostic.status = "parsed"
    record_diagnostic.parsed_field_count = len(record.fields)
    record_diagnostic.warnings.extend(record.warnings)
    return record, record_diagnostic


def parse_metadata_fields(
    pages: list[PageText],
    source_document_id: str,
    report_id: str,
) -> dict[str, MetadataField]:
    fields: dict[str, MetadataField] = {}
    for field_name, labels in FIELD_LABELS.items():
        match = _first_labeled_value(pages, labels)
        if match is None:
            continue
        raw_value = normalize_extracted_text(match.value)
        normalized_value = _normalize_text_field(field_name, raw_value)
        fields[field_name] = MetadataField(
            field_name=field_name,
            raw_value=raw_value,
            normalized_value=normalized_value,
            raw_excerpt=match.excerpt,
            page_number=match.page_number,
            confidence=0.9 if normalized_value == raw_value else 0.82,
        )

    for field_name, labels in DATE_FIELD_LABELS.items():
        match = _first_labeled_value(pages, labels, date_only=True)
        if match is None:
            continue
        raw_value = normalize_extracted_text(match.value)
        parsed_date = parse_numeric_date(raw_value)
        warnings = []
        confidence = 0.9
        if parsed_date is None:
            warnings.append("malformed_date")
            confidence = 0.2
        fields[field_name] = MetadataField(
            field_name=field_name,
            raw_value=raw_value,
            normalized_value=parsed_date,
            raw_excerpt=match.excerpt,
            page_number=match.page_number,
            confidence=confidence,
            warnings=warnings,
        )

    for field in fields.values():
        field.warnings = list(dict.fromkeys(field.warnings))
    return fields


def split_extracted_pages(text: str) -> list[PageText]:
    """Split PR 4 extracted text while preserving page numbers when present."""
    matches = list(PAGE_MARKER_RE.finditer(text))
    if not matches:
        return [PageText(page_number=None, text=normalize_extracted_text(text))]

    pages: list[PageText] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append(
            PageText(
                page_number=int(match.group("page_number")),
                text=normalize_extracted_text(text[start:end]),
            )
        )
    return pages


def parse_numeric_date(value: str) -> date | None:
    """Parse deterministic numeric dates used in synthetic and source reports."""
    match = re.fullmatch(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\s*", value)
    if not match:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def report_id_from_source_document_id(source_document_id: str) -> str:
    digest = sha256(source_document_id.encode("utf-8")).hexdigest()[:16]
    return f"report-{digest}"


@dataclass(frozen=True)
class LabeledValue:
    value: str
    excerpt: str
    page_number: int | None


def _first_labeled_value(
    pages: list[PageText],
    labels: tuple[str, ...],
    *,
    date_only: bool = False,
) -> LabeledValue | None:
    pattern = _label_pattern(labels, date_only=date_only)
    for page in pages:
        match = pattern.search(page.text)
        if match:
            excerpt = normalize_extracted_text(match.group(0))
            return LabeledValue(
                value=match.group("value"),
                excerpt=excerpt[:500],
                page_number=page.page_number,
            )
    return None


def _label_pattern(labels: tuple[str, ...], *, date_only: bool) -> re.Pattern[str]:
    escaped_labels = "|".join(re.escape(label) for label in labels)
    template = DATE_VALUE_RE_TEMPLATE if date_only else LINE_VALUE_RE_TEMPLATE
    return re.compile(template.format(labels=escaped_labels))


def _normalize_text_field(field_name: str, value: str) -> str:
    if field_name == "facility_id":
        return re.sub(r"\D+", "", value)
    if field_name == "facility_type":
        return FACILITY_TYPE_NORMALIZATIONS.get(value, value)
    if field_name == "visit_type":
        return VISIT_TYPE_NORMALIZATIONS.get(value, value)
    return value


def _base_report_record(
    *,
    diagnostic: TextExtractionRecordDiagnostic,
    report_id: str,
) -> ReportMetadataRecord:
    return ReportMetadataRecord(
        report_id=report_id,
        source_document_id=diagnostic.source_document_id,
        govil_item_slug=diagnostic.govil_item_slug,
        govil_item_url=diagnostic.govil_item_url,
        pdf_url=diagnostic.pdf_url,
        title=diagnostic.title,
        language_path=diagnostic.language_path,
        pdf_sha256=diagnostic.pdf_sha256,
        local_path=diagnostic.local_path,
        text_path=diagnostic.text_path,
        page_count=diagnostic.page_count,
        extraction_status=diagnostic.status,
        extraction_confidence=_extraction_confidence(diagnostic),
    )


def _extraction_confidence(diagnostic: TextExtractionRecordDiagnostic) -> float:
    if diagnostic.status == "extracted" and not diagnostic.warnings:
        return 0.95
    if diagnostic.status == "extracted":
        return 0.75
    if diagnostic.status == "skipped_existing":
        return 0.65
    return 0.0


def _missing_field_warnings(
    source_document_id: str,
    report_id: str,
    fields: dict[str, MetadataField],
) -> list[MetadataParseWarning]:
    warnings: list[MetadataParseWarning] = []
    expected_fields = [
        "facility_name",
        "facility_id",
        "facility_type",
        "district",
        "administration",
        "visit_type",
        "visit_date",
        "report_publication_date",
    ]
    for field_name in expected_fields:
        if field_name not in fields:
            warnings.append(
                _warning(
                    source_document_id,
                    report_id,
                    f"missing_{field_name}",
                    f"No deterministic {field_name} value found in extracted text.",
                )
            )
        elif fields[field_name].warnings:
            for warning_code in fields[field_name].warnings:
                warnings.append(
                    _warning(
                        source_document_id,
                        report_id,
                        f"{field_name}_{warning_code}",
                        f"Parsed {field_name} with warning: {warning_code}.",
                        page_number=fields[field_name].page_number,
                        raw_excerpt=fields[field_name].raw_excerpt,
                    )
                )
    return warnings


def _warning(
    source_document_id: str,
    report_id: str | None,
    code: str,
    message: str,
    *,
    page_number: int | None = None,
    raw_excerpt: str | None = None,
) -> MetadataParseWarning:
    warning_key = (
        f"{source_document_id}|{report_id or ''}|{code}|"
        f"{page_number or ''}|{raw_excerpt or ''}"
    )
    digest = sha256(warning_key.encode("utf-8")).hexdigest()[:16]
    return MetadataParseWarning(
        warning_id=f"metadata-warning-{digest}",
        source_document_id=source_document_id,
        report_id=report_id,
        message=message,
        page_number=page_number,
        raw_excerpt=raw_excerpt,
    )
