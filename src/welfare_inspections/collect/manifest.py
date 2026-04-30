"""Manifest and diagnostics readers/writers for source collection stages."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from welfare_inspections.collect.models import (
    DiscoveryRunDiagnostics,
    DownloadRunDiagnostics,
    SourceDocumentRecord,
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
