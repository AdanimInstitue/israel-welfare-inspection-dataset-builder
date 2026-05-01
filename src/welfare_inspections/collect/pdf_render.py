"""Manual local PDF page rendering for multimodal extraction inputs."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import fitz
import structlog

from welfare_inspections.collect.manifest import (
    read_source_manifest,
    write_page_render_diagnostics,
    write_rendered_page_manifest,
)
from welfare_inspections.collect.models import (
    PageRenderRecordDiagnostic,
    PageRenderRunDiagnostics,
    RenderedPageArtifact,
    RenderProfile,
    SourceDocumentRecord,
    utc_now,
)
from welfare_inspections.collect.pdf_download import sha256_file

logger = structlog.get_logger(__name__)

DEFAULT_RENDER_PROFILE = RenderProfile(
    render_profile_id="default-v1",
    render_profile_version="1",
    dpi=144,
    colorspace="rgb",
    image_format="png",
    rotation_degrees=0,
    coordinate_system="pixel_top_left_origin_1_based_page",
)


def render_pages_from_manifest(
    *,
    source_manifest_path: Path,
    output_manifest_path: Path,
    diagnostics_path: Path,
    page_output_dir: Path,
    render_profile: RenderProfile = DEFAULT_RENDER_PROFILE,
    overwrite: bool = False,
) -> tuple[list[RenderedPageArtifact], PageRenderRunDiagnostics]:
    """Render downloaded PDFs from a PR 3 manifest into local page images."""
    records = read_source_manifest(source_manifest_path)
    diagnostics = PageRenderRunDiagnostics(
        source_manifest_path=str(source_manifest_path),
        output_manifest_path=str(output_manifest_path),
        page_output_dir=str(page_output_dir),
        render_profile=render_profile,
        total_records=len(records),
    )
    artifacts: list[RenderedPageArtifact] = []

    for record in records:
        record_artifacts, record_diagnostic = _render_record(
            record=record,
            page_output_dir=page_output_dir,
            render_profile=render_profile,
            overwrite=overwrite,
        )
        artifacts.extend(record_artifacts)
        diagnostics.record_diagnostics.append(record_diagnostic)
        diagnostics.artifact_count += len(record_artifacts)
        if record_diagnostic.status == "rendered":
            diagnostics.rendered_records += 1
        elif record_diagnostic.status == "skipped_existing":
            diagnostics.skipped_existing_records += 1
        else:
            diagnostics.failed_records += 1
            if record_diagnostic.status == "missing_pdf":
                diagnostics.missing_pdf_records += 1
            if record_diagnostic.status == "missing_checksum":
                diagnostics.missing_checksum_records += 1

    diagnostics.finished_at = utc_now()
    write_rendered_page_manifest(output_manifest_path, artifacts)
    write_page_render_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "page_render_complete",
        records=diagnostics.total_records,
        artifacts=diagnostics.artifact_count,
        failed=diagnostics.failed_records,
    )
    return artifacts, diagnostics


def _render_record(
    *,
    record: SourceDocumentRecord,
    page_output_dir: Path,
    render_profile: RenderProfile,
    overwrite: bool,
) -> tuple[list[RenderedPageArtifact], PageRenderRecordDiagnostic]:
    diagnostic = PageRenderRecordDiagnostic(
        source_document_id=record.source_document_id,
        pdf_sha256=record.pdf_sha256,
        local_path=record.local_path,
        status="pending",
    )
    if not record.local_path:
        diagnostic.status = "missing_pdf"
        diagnostic.error = "manifest_record_has_no_local_path"
        return [], diagnostic

    pdf_path = Path(record.local_path)
    if not pdf_path.exists():
        diagnostic.status = "missing_pdf"
        diagnostic.error = "local_pdf_not_found"
        return [], diagnostic

    observed_pdf_sha256 = sha256_file(pdf_path)
    expected_pdf_sha256 = record.pdf_sha256 or observed_pdf_sha256
    if not record.pdf_sha256:
        diagnostic.status = "missing_checksum"
        diagnostic.error = "manifest_record_has_no_pdf_sha256"
        return [], diagnostic
    if observed_pdf_sha256 != expected_pdf_sha256:
        diagnostic.status = "failed"
        diagnostic.error = "local_pdf_checksum_mismatch"
        return [], diagnostic

    try:
        with fitz.open(pdf_path) as document:
            diagnostic.page_count = len(document)
            expected_paths = [
                _artifact_path(
                    page_output_dir=page_output_dir,
                    record=record,
                    page_number=page_number,
                    render_profile=render_profile,
                )
                for page_number in range(1, len(document) + 1)
            ]
            if (
                not overwrite
                and expected_paths
                and all(path.exists() for path in expected_paths)
            ):
                artifacts = [
                    _artifact_from_existing(
                        path=path,
                        record=record,
                        page_number=page_number,
                        render_profile=render_profile,
                    )
                    for page_number, path in enumerate(expected_paths, 1)
                ]
                diagnostic.status = "skipped_existing"
                diagnostic.rendered_artifact_ids = [
                    artifact.rendered_artifact_id for artifact in artifacts
                ]
                diagnostic.warnings.append("existing_rendered_pages_not_overwritten")
                return artifacts, diagnostic

            artifacts = []
            for page_index, page in enumerate(document):
                page_number = page_index + 1
                path = expected_paths[page_index]
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(
                        render_profile.dpi / 72,
                        render_profile.dpi / 72,
                    ),
                    alpha=False,
                    colorspace=fitz.csRGB,
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary_path = path.with_name(f".{path.stem}.tmp{path.suffix}")
                pixmap.save(temporary_path)
                temporary_path.replace(path)
                artifacts.append(
                    _artifact_from_existing(
                        path=path,
                        record=record,
                        page_number=page_number,
                        render_profile=render_profile,
                        width_px=pixmap.width,
                        height_px=pixmap.height,
                    )
                )
    except Exception as exc:
        diagnostic.status = "failed"
        diagnostic.error = f"pdf_render_error:{exc}"
        return [], diagnostic

    diagnostic.status = "rendered"
    diagnostic.rendered_artifact_ids = [
        artifact.rendered_artifact_id for artifact in artifacts
    ]
    return artifacts, diagnostic


def _artifact_from_existing(
    *,
    path: Path,
    record: SourceDocumentRecord,
    page_number: int,
    render_profile: RenderProfile,
    width_px: int | None = None,
    height_px: int | None = None,
) -> RenderedPageArtifact:
    if width_px is None or height_px is None:
        pixmap = fitz.Pixmap(str(path))
        width_px = pixmap.width
        height_px = pixmap.height
    return RenderedPageArtifact(
        rendered_artifact_id=rendered_artifact_id(
            source_document_id=record.source_document_id,
            source_pdf_sha256=record.pdf_sha256 or "",
            page_number=page_number,
            render_profile=render_profile,
        ),
        source_document_id=record.source_document_id,
        source_pdf_sha256=record.pdf_sha256 or "",
        page_number=page_number,
        artifact_type="page",
        renderer_name="pymupdf",
        renderer_version=fitz.VersionBind,
        render_profile_id=render_profile.render_profile_id,
        render_profile_version=render_profile.render_profile_version,
        dpi=render_profile.dpi,
        colorspace=render_profile.colorspace,
        image_format=render_profile.image_format,
        rotation_degrees=render_profile.rotation_degrees,
        crop_box=None,
        coordinate_system=render_profile.coordinate_system,
        width_px=width_px,
        height_px=height_px,
        image_sha256=sha256_file(path),
        local_path=str(path),
    )


def _artifact_path(
    *,
    page_output_dir: Path,
    record: SourceDocumentRecord,
    page_number: int,
    render_profile: RenderProfile,
) -> Path:
    artifact_id = rendered_artifact_id(
        source_document_id=record.source_document_id,
        source_pdf_sha256=record.pdf_sha256 or "",
        page_number=page_number,
        render_profile=render_profile,
    )
    return (
        page_output_dir
        / record.source_document_id
        / render_profile.render_profile_id
        / f"{artifact_id}.{render_profile.image_format.lower()}"
    )


def rendered_artifact_id(
    *,
    source_document_id: str,
    source_pdf_sha256: str,
    page_number: int,
    render_profile: RenderProfile,
) -> str:
    source = (
        f"{source_document_id}|{source_pdf_sha256}|{page_number}|"
        f"{render_profile.render_profile_id}|{render_profile.render_profile_version}|"
        f"{render_profile.dpi}|{render_profile.colorspace}|"
        f"{render_profile.image_format}|{render_profile.rotation_degrees}"
    )
    digest = sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"rendered-page-{digest}"
