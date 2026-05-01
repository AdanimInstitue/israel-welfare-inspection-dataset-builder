"""Pydantic models for source discovery manifests and diagnostics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ExtractionCandidate(BaseModel):
    """Normalized candidate value from deterministic, LLM, OCR, or canonical input."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    report_id: str | None = None
    field_name: str = Field(min_length=1)
    raw_value: str | None = None
    normalized_value: str | date | int | float | None = None
    page_number: int | None = Field(default=None, ge=1)
    raw_excerpt: str | None = None
    visual_locator: VisualLocator | None = None
    extraction_method: str = Field(
        pattern="^(deterministic|llm_text|llm_multimodal|ocr|existing_canonical)$"
    )
    extractor_version: str = Field(min_length=1)
    model_name: str | None = None
    model_version: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_input_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    source_pdf_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    text_input_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    rendered_artifact_ids: list[str] = Field(default_factory=list)
    rendered_artifact_sha256s: list[str] = Field(default_factory=list)
    renderer_version: str | None = None
    preprocessor_version: str | None = None
    input_artifact_refs: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_candidate_provenance(self) -> ExtractionCandidate:
        if not self.raw_excerpt and self.visual_locator is None:
            self.warnings.append("candidate_has_no_field_evidence")
        if self.field_name.endswith("_date") and isinstance(
            self.normalized_value,
            str,
        ):
            try:
                date.fromisoformat(self.normalized_value)
            except ValueError as exc:
                msg = (
                    f"{self.field_name} normalized_value must be an ISO date "
                    "when provided as a string."
                )
                raise ValueError(msg) from exc
        if self.extraction_method.startswith("llm_"):
            missing: list[str] = []
            if not self.source_pdf_sha256:
                missing.append("source_pdf_sha256")
            if not self.prompt_input_sha256:
                missing.append("prompt_input_sha256")
            if not self.prompt_id:
                missing.append("prompt_id")
            if not self.prompt_version:
                missing.append("prompt_version")
            if missing:
                msg = "LLM candidate missing provenance: " + ", ".join(missing)
                raise ValueError(msg)
        return self


class ReconciliationDecision(BaseModel):
    """Field-level decision describing how candidates became canonical values."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    accepted_candidate_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    decision_status: str = Field(
        pattern="^(accepted|unresolved|conflict|rejected|needs_review)$"
    )
    decision_method: str = Field(min_length=1)
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=utc_now)
    schema_version: str = Field(min_length=1)
    reconciler_version: str = Field(min_length=1)


class ReconciledReportMetadata(BaseModel):
    """Report metadata plus conservative reconciliation decisions."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    base_metadata: ReportMetadataRecord
    reconciled_fields: dict[str, str | date | int | float | None] = Field(
        default_factory=dict
    )
    raw_fields: dict[str, str | None] = Field(default_factory=dict)
    accepted_extraction_methods: dict[str, list[str]] = Field(default_factory=dict)
    llm_candidate_ids: dict[str, list[str]] = Field(default_factory=dict)
    reconciliation_status: str = Field(min_length=1)
    decisions: list[ReconciliationDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    schema_version: str = Field(min_length=1)
    reconciler_version: str = Field(min_length=1)
    reconciled_at: datetime = Field(default_factory=utc_now)


class ReconciliationRecordDiagnostic(BaseModel):
    """Per-record diagnostics for reconciliation."""

    model_config = ConfigDict(extra="forbid")

    line_number: int | None = None
    report_id: str | None = None
    source_document_id: str | None = None
    status: str
    decision_ids: list[str] = Field(default_factory=list)
    accepted_count: int = 0
    needs_review_count: int = 0
    rejected_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utc_now)


class ReconciliationRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual reconciliation run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    metadata_path: str
    metadata_diagnostics_path: str
    llm_candidates_path: str | None = None
    output_path: str
    diagnostics_path: str
    schema_version: str
    reconciler_version: str
    total_records: int = 0
    reconciled_records: int = 0
    validation_failed_records: int = 0
    duplicate_candidate_id_records: int = 0
    duplicate_decision_id_records: int = 0
    accepted_decisions: int = 0
    needs_review_decisions: int = 0
    rejected_decisions: int = 0
    record_diagnostics: list[ReconciliationRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class BackfillFieldChange(BaseModel):
    """Before/after view of one field considered by backfill."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    before_value: str | date | int | float | None = None
    after_value: str | date | int | float | None = None
    status: str = Field(
        pattern="^(changed|unchanged|unresolved|rejected|no_baseline)$"
    )
    accepted_candidate_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    decision_id: str | None = None


class BackfillRunDiagnostics(BaseModel):
    """Dry-run-friendly diagnostics for versioned historical backfills."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    mode: str = "dry-run"
    reconciled_metadata_path: str
    output_path: str
    evaluation_report_path: str | None = None
    schema_version: str
    reconciler_version: str
    input_hashes: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str | None] = Field(default_factory=dict)
    prompt_versions: dict[str, str | None] = Field(default_factory=dict)
    render_versions: dict[str, str | None] = Field(default_factory=dict)
    changed_count: int = 0
    unchanged_count: int = 0
    no_baseline_count: int = 0
    unresolved_count: int = 0
    rejected_count: int = 0
    field_changes: list[BackfillFieldChange] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


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


class CropBox(BaseModel):
    """Pixel-space crop coordinates in the parent rendered page."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RenderProfile(BaseModel):
    """Versioned PDF page rendering settings."""

    model_config = ConfigDict(extra="forbid")

    render_profile_id: str = Field(min_length=1)
    render_profile_version: str = Field(min_length=1)
    dpi: int = Field(gt=0)
    colorspace: str = Field(min_length=1)
    image_format: str = Field(min_length=1)
    rotation_degrees: int = Field(default=0)
    coordinate_system: str = Field(min_length=1)


class RenderedPageArtifact(BaseModel):
    """One rendered page or crop image used as multimodal LLM input."""

    model_config = ConfigDict(extra="forbid")

    rendered_artifact_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    source_pdf_sha256: str = Field(min_length=64, max_length=64)
    page_number: int = Field(ge=1)
    artifact_type: str = Field(pattern="^(page|crop)$")
    parent_rendered_artifact_id: str | None = None
    renderer_name: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)
    render_profile_id: str = Field(min_length=1)
    render_profile_version: str = Field(min_length=1)
    dpi: int = Field(gt=0)
    colorspace: str = Field(min_length=1)
    image_format: str = Field(min_length=1)
    rotation_degrees: int = Field(default=0)
    crop_box: CropBox | None = None
    coordinate_system: str = Field(min_length=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    image_sha256: str = Field(min_length=64, max_length=64)
    local_path: str = Field(min_length=1)
    rendered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_crop_contract(self) -> RenderedPageArtifact:
        if self.artifact_type == "page" and self.crop_box is not None:
            msg = "Full-page rendered artifacts must not include crop_box."
            raise ValueError(msg)
        if self.artifact_type == "crop" and self.crop_box is None:
            msg = "Crop rendered artifacts must include crop_box."
            raise ValueError(msg)
        return self


class PageRenderRecordDiagnostic(BaseModel):
    """Per-document diagnostics for PDF page rendering."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    pdf_sha256: str | None = None
    local_path: str | None = None
    status: str
    page_count: int | None = None
    rendered_artifact_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class PageRenderRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual page rendering run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    source_manifest_path: str
    output_manifest_path: str
    page_output_dir: str
    render_profile: RenderProfile
    total_records: int = 0
    rendered_records: int = 0
    skipped_existing_records: int = 0
    failed_records: int = 0
    missing_pdf_records: int = 0
    missing_checksum_records: int = 0
    artifact_count: int = 0
    record_diagnostics: list[PageRenderRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class VisualLocator(BaseModel):
    """Visual evidence locator using the rendered artifact coordinate system."""

    model_config = ConfigDict(extra="forbid")

    rendered_artifact_id: str = Field(min_length=1)
    coordinate_system: str = Field(min_length=1)
    bounding_box: CropBox
    note: str | None = None


class FieldEvidence(BaseModel):
    """Source evidence for one extracted candidate field."""

    model_config = ConfigDict(extra="forbid")

    page_number: int | None = Field(default=None, ge=1)
    raw_excerpt: str | None = None
    visual_locator: VisualLocator | None = None

    @model_validator(mode="after")
    def validate_evidence_present(self) -> FieldEvidence:
        if not self.raw_excerpt and self.visual_locator is None:
            msg = "Field evidence requires raw_excerpt or visual_locator."
            raise ValueError(msg)
        return self


class LLMExtractionCandidate(BaseModel):
    """Schema-bound candidate value emitted by an LLM extraction stage."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    report_id: str | None = None
    field_name: str = Field(min_length=1)
    raw_value: str | None = None
    normalized_value: str | date | int | float | None = None
    extraction_method: str = Field(pattern="^(llm_text|llm_multimodal)$")
    extractor_version: str = Field(min_length=1)
    source_pdf_sha256: str = Field(min_length=64, max_length=64)
    text_input_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    rendered_artifact_ids: list[str] = Field(default_factory=list)
    rendered_artifact_sha256s: list[str] = Field(default_factory=list)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_input_sha256: str = Field(min_length=64, max_length=64)
    model_name: str | None = None
    model_version: str | None = None
    field_evidence: FieldEvidence
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    validation_status: str = Field(pattern="^(valid|invalid|needs_review)$")
    validation_errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_input_identity(self) -> LLMExtractionCandidate:
        if self.field_name.endswith("_date") and isinstance(
            self.normalized_value,
            str,
        ):
            try:
                date.fromisoformat(self.normalized_value)
            except ValueError as exc:
                msg = (
                    f"{self.field_name} normalized_value must be an ISO date "
                    "when provided as a string."
                )
                raise ValueError(msg) from exc
        if self.extraction_method == "llm_text" and not self.text_input_sha256:
            msg = "llm_text candidates require text_input_sha256."
            raise ValueError(msg)
        if self.extraction_method == "llm_multimodal":
            if not self.rendered_artifact_ids or not self.rendered_artifact_sha256s:
                msg = (
                    "llm_multimodal candidates require rendered artifact IDs "
                    "and hashes."
                )
                raise ValueError(msg)
            if len(self.rendered_artifact_ids) != len(self.rendered_artifact_sha256s):
                msg = "Rendered artifact ID and hash counts must match."
                raise ValueError(msg)
            locator = self.field_evidence.visual_locator
            if (
                locator
                and locator.rendered_artifact_id not in self.rendered_artifact_ids
            ):
                msg = "visual_locator rendered_artifact_id must be an input artifact."
                raise ValueError(msg)
        return self


class LLMExtractionRecordDiagnostic(BaseModel):
    """Per-document diagnostics for one LLM extraction attempt."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    status: str
    extraction_methods: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utc_now)


class LLMExtractionRunDiagnostics(BaseModel):
    """Sidecar diagnostics for one manual LLM extraction run."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    mode: str
    source_manifest_path: str
    text_diagnostics_path: str | None = None
    render_manifest_path: str | None = None
    output_path: str
    diagnostics_path: str
    prompt_id: str
    prompt_version: str
    model_name: str | None = None
    model_version: str | None = None
    total_records: int = 0
    candidate_records: int = 0
    failed_records: int = 0
    warning_records: int = 0
    record_diagnostics: list[LLMExtractionRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class EvaluationExpectedField(BaseModel):
    """Reviewed expected value for offline LLM candidate evaluation."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    field_name: str
    expected_normalized_value: str | date | int | float | None = None
    required: bool = True


class EvaluationFieldResult(BaseModel):
    """Field-level offline evaluation result."""

    model_config = ConfigDict(extra="forbid")

    source_document_id: str
    field_name: str
    expected_normalized_value: str | date | int | float | None = None
    observed_normalized_value: str | date | int | float | None = None
    status: str
    candidate_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    observed_candidate_count: int = 0


class LLMEvaluationReport(BaseModel):
    """Offline evaluation report for LLM extraction candidate manifests."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    candidate_manifest_path: str
    fixture_path: str | None = None
    schema_version: str
    prompt_id: str
    prompt_version: str
    model_name: str | None = None
    model_version: str | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    render_profile_id: str | None = None
    render_profile_version: str | None = None
    expected_field_count: int = 0
    observed_field_count: int = 0
    covered_field_count: int = 0
    correct_field_count: int = 0
    missing_field_count: int = 0
    incorrect_field_count: int = 0
    regression_count: int = 0
    field_results: list[EvaluationFieldResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


ExtractionCandidate.model_rebuild()
