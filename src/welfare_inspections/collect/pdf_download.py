"""Manual PDF download, checksum, and manifest update layer."""

from __future__ import annotations

import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import structlog

from welfare_inspections.collect.govil_client import BinaryFetch, GovilClient
from welfare_inspections.collect.manifest import (
    read_source_manifest,
    write_download_diagnostics,
    write_source_manifest,
)
from welfare_inspections.collect.models import (
    DownloadRecordDiagnostic,
    DownloadRunDiagnostics,
    SourceDocumentRecord,
    utc_now,
)

logger = structlog.get_logger(__name__)


def download_source_pdfs(
    *,
    source_manifest_path: Path,
    output_manifest_path: Path,
    diagnostics_path: Path,
    download_dir: Path,
    force: bool = False,
    request_delay_seconds: float = 1.0,
    client: GovilClient | None = None,
) -> tuple[list[SourceDocumentRecord], DownloadRunDiagnostics]:
    """Download PDFs from a source manifest and write updated local metadata."""
    records = read_source_manifest(source_manifest_path)
    diagnostics = DownloadRunDiagnostics(
        source_manifest_path=str(source_manifest_path),
        output_manifest_path=str(output_manifest_path),
        download_dir=str(download_dir),
        total_records=len(records),
    )
    own_client = client is None
    http_client = client or GovilClient()
    updated_records: list[SourceDocumentRecord] = []

    try:
        for index, record in enumerate(records):
            updated_record = _process_record(
                record=record,
                download_dir=download_dir,
                force=force,
                client=http_client,
                diagnostics=diagnostics,
            )
            updated_records.append(updated_record)

            if (
                index < len(records) - 1
                and request_delay_seconds > 0
                and _should_delay_after(diagnostics.record_diagnostics[-1])
            ):
                time.sleep(request_delay_seconds)
    finally:
        if own_client:
            http_client.close()

    diagnostics.finished_at = utc_now()
    write_source_manifest(output_manifest_path, updated_records)
    write_download_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "pdf_download_complete",
        records=len(updated_records),
        downloaded=diagnostics.downloaded_records,
        failed=diagnostics.failed_records,
    )
    return updated_records, diagnostics


def _process_record(
    *,
    record: SourceDocumentRecord,
    download_dir: Path,
    force: bool,
    client: GovilClient,
    diagnostics: DownloadRunDiagnostics,
) -> SourceDocumentRecord:
    local_path = _local_path_for(record, download_dir)
    existing = _valid_existing_record(record, local_path, force)
    if existing is not None:
        diagnostics.skipped_existing_records += 1
        diagnostics.record_diagnostics.append(existing.diagnostic)
        return existing.record

    if local_path.exists() and record.pdf_sha256 and not force:
        observed_sha256 = sha256_file(local_path)
        if observed_sha256 != record.pdf_sha256:
            diagnostics.checksum_mismatch_records += 1
            diagnostics.failed_records += 1
            diagnostics.record_diagnostics.append(
                DownloadRecordDiagnostic(
                    source_document_id=record.source_document_id,
                    pdf_url=record.pdf_url,
                    status="checksum_mismatch",
                    local_path=str(local_path),
                    pdf_sha256=observed_sha256,
                    error="existing_file_checksum_mismatch",
                )
            )
            return record

    fetch = client.fetch_binary(record.pdf_url)
    if fetch.diagnostic.is_blocked:
        diagnostics.blocked_responses += 1

    if fetch.diagnostic.error or fetch.diagnostic.status_code != 200:
        diagnostics.failed_records += 1
        diagnostics.record_diagnostics.append(
            _download_failure_diagnostic(record, local_path, fetch)
        )
        return record

    if not fetch.content:
        diagnostics.failed_records += 1
        diagnostics.record_diagnostics.append(
            DownloadRecordDiagnostic(
                source_document_id=record.source_document_id,
                pdf_url=record.pdf_url,
                status="failed",
                local_path=str(local_path),
                error="empty_response_body",
                http_diagnostic=fetch.diagnostic,
            )
        )
        return record

    written_sha256 = _write_download(local_path, fetch.content)
    updated = record.model_copy(
        update={
            "downloaded_at": utc_now(),
            "http_status": fetch.diagnostic.status_code,
            "response_headers": fetch.diagnostic.response_headers,
            "pdf_sha256": written_sha256,
            "local_path": str(local_path),
        }
    )
    diagnostics.downloaded_records += 1
    diagnostics.record_diagnostics.append(
        DownloadRecordDiagnostic(
            source_document_id=record.source_document_id,
            pdf_url=record.pdf_url,
            status="downloaded",
            local_path=str(local_path),
            pdf_sha256=written_sha256,
            http_diagnostic=fetch.diagnostic,
        )
    )
    return updated


def _valid_existing_record(
    record: SourceDocumentRecord,
    local_path: Path,
    force: bool,
) -> _ExistingRecord | None:
    if force or not local_path.exists():
        return None

    observed_sha256 = sha256_file(local_path)
    if record.pdf_sha256 and observed_sha256 != record.pdf_sha256:
        return None

    updated = record.model_copy(
        update={
            "downloaded_at": record.downloaded_at or utc_now(),
            "pdf_sha256": observed_sha256,
            "local_path": str(local_path),
        }
    )
    return _ExistingRecord(
        record=updated,
        diagnostic=DownloadRecordDiagnostic(
            source_document_id=record.source_document_id,
            pdf_url=record.pdf_url,
            status="skipped_existing",
            local_path=str(local_path),
            pdf_sha256=observed_sha256,
        ),
    )


@dataclass(frozen=True)
class _ExistingRecord:
    record: SourceDocumentRecord
    diagnostic: DownloadRecordDiagnostic


def _download_failure_diagnostic(
    record: SourceDocumentRecord,
    local_path: Path,
    fetch: BinaryFetch,
) -> DownloadRecordDiagnostic:
    status = "blocked" if fetch.diagnostic.is_blocked else "failed"
    error = fetch.diagnostic.error or f"http_status_{fetch.diagnostic.status_code}"
    return DownloadRecordDiagnostic(
        source_document_id=record.source_document_id,
        pdf_url=record.pdf_url,
        status=status,
        local_path=str(local_path),
        error=error,
        http_diagnostic=fetch.diagnostic,
    )


def _write_download(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.part")
    temporary_path.write_bytes(content)
    digest = sha256_bytes(content)
    temporary_path.replace(path)
    return digest


def _local_path_for(record: SourceDocumentRecord, download_dir: Path) -> Path:
    if record.local_path:
        return Path(record.local_path)
    return download_dir / f"{record.source_document_id}.pdf"


def _should_delay_after(diagnostic: DownloadRecordDiagnostic) -> bool:
    return diagnostic.status not in {"skipped_existing", "checksum_mismatch"}


def sha256_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
