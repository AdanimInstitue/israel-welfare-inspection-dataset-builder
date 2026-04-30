"""Pydantic models for source discovery manifests and diagnostics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def source_document_id_from(
    govil_item_slug: str | None,
    item_url: str,
    pdf_url: str,
) -> str:
    source_key = f"{govil_item_slug or ''}|{pdf_url}"
    digest = sha256(source_key.encode("utf-8")).hexdigest()[:16]
    return f"source-doc-{digest}"


class SourceDocumentRecord(BaseModel):
    """A public source document discovered from the Gov.il collector."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    govil_item_slug: str | None = None
    govil_item_url: str
    pdf_url: str
    title: str | None = None
    language_path: str | None = None
    source_published_at: datetime | None = None
    source_updated_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=utc_now)
    downloaded_at: datetime | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    pdf_sha256: str | None = None
    local_path: str | None = None
    collector_version: str


class HttpDiagnostic(BaseModel):
    """HTTP-level diagnostics captured during source discovery."""

    model_config = ConfigDict(extra="forbid")

    url: str
    status_code: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    elapsed_seconds: float | None = None
    error: str | None = None
    is_blocked: bool = False
    fetched_at: datetime = Field(default_factory=utc_now)


class DynamicCollectorConfig(BaseModel):
    """Structured endpoint configuration embedded in a Gov.il collector page."""

    model_config = ConfigDict(extra="forbid")

    dynamic_template_id: str
    endpoint_url: str
    x_client_id: str
    items_per_page: int = 10


class DiscoveryRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one discovery run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    start_url: str
    attempted_urls: list[str] = Field(default_factory=list)
    http_diagnostics: list[HttpDiagnostic] = Field(default_factory=list)
    page_record_counts: dict[str, int] = Field(default_factory=dict)
    total_records: int = 0
    new_records: int = 0
    duplicate_records: int = 0
    blocked_responses: int = 0
    stop_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class DownloadRecordDiagnostic(BaseModel):
    """Per-source-record diagnostics for one manual PDF download attempt."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    pdf_url: str
    status: str
    local_path: str | None = None
    pdf_sha256: str | None = None
    error: str | None = None
    http_diagnostic: HttpDiagnostic | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class DownloadRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual PDF download run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    source_manifest_path: str
    output_manifest_path: str
    download_dir: str
    total_records: int = 0
    downloaded_records: int = 0
    skipped_existing_records: int = 0
    failed_records: int = 0
    checksum_mismatch_records: int = 0
    blocked_responses: int = 0
    record_diagnostics: list[DownloadRecordDiagnostic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class TextPageDiagnostic(BaseModel):
    """Per-page diagnostics for embedded PDF text extraction."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    status: str
    raw_char_count: int = 0
    normalized_char_count: int = 0
    warning: str | None = None


class TextExtractionRecordDiagnostic(BaseModel):
    """Per-source-record diagnostics for one embedded text extraction attempt."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    govil_item_slug: str | None = None
    govil_item_url: str
    pdf_url: str
    title: str | None = None
    language_path: str | None = None
    pdf_sha256: str | None = None
    local_path: str | None = None
    status: str
    text_path: str | None = None
    page_count: int | None = None
    pdf_metadata: dict[str, str] = Field(default_factory=dict)
    pages: list[TextPageDiagnostic] = Field(default_factory=list)
    raw_char_count: int = 0
    normalized_char_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class TextExtractionRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual embedded text extraction run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    source_manifest_path: str
    text_output_dir: str
    total_records: int = 0
    extracted_records: int = 0
    warning_records: int = 0
    failed_records: int = 0
    missing_pdf_records: int = 0
    missing_local_path_records: int = 0
    skipped_existing_records: int = 0
    record_diagnostics: list[TextExtractionRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class MetadataField(BaseModel):
    """One deterministic report-level metadata field plus evidence."""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    raw_value: str | None = None
    normalized_value: str | date | None = None
    raw_excerpt: str | None = None
    page_number: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class MetadataParseWarning(BaseModel):
    """Document-level metadata parsing warning."""

    model_config = ConfigDict(extra="forbid")

    warning_id: str
    source_document_id: str
    report_id: str | None = None
    severity: str = "warning"
    parser_stage: str = "metadata"
    message: str
    page_number: int | None = None
    raw_excerpt: str | None = None


class ReportMetadataRecord(BaseModel):
    """Top-level metadata parsed from one extracted inspection report."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    source_document_id: str
    govil_item_slug: str | None = None
    govil_item_url: str
    pdf_url: str
    title: str | None = None
    language_path: str | None = None
    pdf_sha256: str | None = None
    local_path: str | None = None
    text_path: str | None = None
    page_count: int | None = None
    extraction_status: str
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    fields: dict[str, MetadataField] = Field(default_factory=dict)
    warnings: list[MetadataParseWarning] = Field(default_factory=list)
    parsed_at: datetime = Field(default_factory=utc_now)


class MetadataParseRecordDiagnostic(BaseModel):
    """Per-document diagnostics for metadata parsing."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    report_id: str | None = None
    status: str
    text_path: str | None = None
    page_count: int | None = None
    extraction_status: str | None = None
    parsed_field_count: int = 0
    warnings: list[MetadataParseWarning] = Field(default_factory=list)
    error: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class MetadataParseRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual metadata parsing run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    text_diagnostics_path: str
    output_path: str
    total_records: int = 0
    parsed_records: int = 0
    warning_records: int = 0
    failed_records: int = 0
    record_diagnostics: list[MetadataParseRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class CanonicalReportRow(BaseModel):
    """Validated local report-level export row."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    govil_item_slug: str | None = None
    govil_item_url: str = Field(min_length=1)
    pdf_url: str = Field(min_length=1)
    title: str | None = None
    language_path: str | None = None
    pdf_sha256: str | None = None
    local_path: str | None = None
    text_path: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    extraction_status: str = Field(min_length=1)
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    parsed_at: datetime
    exported_at: datetime = Field(default_factory=utc_now)
    facility_name_raw: str | None = None
    facility_name_normalized: str | None = None
    facility_id_raw: str | None = None
    facility_id_normalized: str | None = None
    facility_type_raw: str | None = None
    facility_type_normalized: str | None = None
    district_raw: str | None = None
    district_normalized: str | None = None
    administration_raw: str | None = None
    administration_normalized: str | None = None
    visit_type_raw: str | None = None
    visit_type_normalized: str | None = None
    visit_date_raw: str | None = None
    visit_date: date | None = None
    report_publication_date_raw: str | None = None
    report_publication_date: date | None = None
    raw_fields: dict[str, str | None] = Field(default_factory=dict)
    normalized_fields: dict[str, str | date | None] = Field(default_factory=dict)
    field_evidence: dict[str, MetadataField] = Field(default_factory=dict)
    warnings: list[MetadataParseWarning] = Field(default_factory=list)
    parse_diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class ExportRecordDiagnostic(BaseModel):
    """Per-input-row diagnostics for local schema validation and export."""

    model_config = ConfigDict(extra="forbid")

    line_number: int | None = None
    report_id: str | None = None
    source_document_id: str | None = None
    status: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    exported: bool = False
    checked_at: datetime = Field(default_factory=utc_now)


class ExportRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual local export run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    metadata_path: str
    metadata_diagnostics_path: str
    output_dir: str
    jsonl_output_path: str
    csv_output_path: str
    total_records: int = 0
    exported_records: int = 0
    validation_failed_records: int = 0
    duplicate_id_records: int = 0
    diagnostic_records: int = 0
    record_diagnostics: list[ExportRecordDiagnostic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
