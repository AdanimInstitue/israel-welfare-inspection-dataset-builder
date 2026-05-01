"""Manifest and diagnostics readers/writers for source collection stages."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from welfare_inspections.collect.models import (
    DiscoveryRunDiagnostics,
    DownloadRunDiagnostics,
    ExportRunDiagnostics,
    LLMEvaluationReport,
    LLMExtractionCandidate,
    LLMExtractionRunDiagnostics,
    MetadataParseRunDiagnostics,
    PageRenderRunDiagnostics,
    RenderedPageArtifact,
    ReportMetadataRecord,
    SourceDocumentRecord,
    TextExtractionRunDiagnostics,
)


def _write_model_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, model.model_dump_json(indent=2) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def read_source_manifest(path: Path) -> list[SourceDocumentRecord]:
    records: list[SourceDocumentRecord] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            records.append(SourceDocumentRecord.model_validate_json(line))
        except ValueError as exc:
            msg = f"Invalid source manifest JSONL at {path}:{line_number}"
            raise ValueError(msg) from exc
    return records


def write_source_manifest(path: Path, records: list[SourceDocumentRecord]) -> None:
    lines = [record.model_dump_json() for record in records]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def read_text_extraction_diagnostics(path: Path) -> TextExtractionRunDiagnostics:
    try:
        return TextExtractionRunDiagnostics.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        msg = f"Invalid text extraction diagnostics JSON at {path}"
        raise ValueError(msg) from exc


def write_metadata_manifest(path: Path, records: list[ReportMetadataRecord]) -> None:
    lines = [record.model_dump_json() for record in records]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def read_rendered_page_manifest(path: Path) -> list[RenderedPageArtifact]:
    records: list[RenderedPageArtifact] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            records.append(RenderedPageArtifact.model_validate_json(line))
        except ValueError as exc:
            msg = f"Invalid rendered page manifest JSONL at {path}:{line_number}"
            raise ValueError(msg) from exc
    return records


def write_rendered_page_manifest(
    path: Path,
    records: list[RenderedPageArtifact],
) -> None:
    lines = [record.model_dump_json() for record in records]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def read_llm_candidate_manifest(path: Path) -> list[LLMExtractionCandidate]:
    records: list[LLMExtractionCandidate] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            records.append(LLMExtractionCandidate.model_validate_json(line))
        except ValueError as exc:
            msg = f"Invalid LLM candidate manifest JSONL at {path}:{line_number}"
            raise ValueError(msg) from exc
    return records


def write_llm_candidate_manifest(
    path: Path,
    records: list[LLMExtractionCandidate],
) -> None:
    lines = [record.model_dump_json() for record in records]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def write_discovery_diagnostics(
    path: Path,
    diagnostics: DiscoveryRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_download_diagnostics(
    path: Path,
    diagnostics: DownloadRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_text_extraction_diagnostics(
    path: Path,
    diagnostics: TextExtractionRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_metadata_parse_diagnostics(
    path: Path,
    diagnostics: MetadataParseRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_export_diagnostics(path: Path, diagnostics: ExportRunDiagnostics) -> None:
    _write_model_json(path, diagnostics)


def write_page_render_diagnostics(
    path: Path,
    diagnostics: PageRenderRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_llm_extraction_diagnostics(
    path: Path,
    diagnostics: LLMExtractionRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)


def write_llm_evaluation_report(path: Path, report: LLMEvaluationReport) -> None:
    _write_model_json(path, report)
