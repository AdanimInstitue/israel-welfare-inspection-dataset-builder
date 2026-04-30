"""Pydantic models for source discovery manifests and diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
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
