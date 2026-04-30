"""Manifest and diagnostics writers for source discovery."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from welfare_inspections.collect.models import (
    DiscoveryRunDiagnostics,
    SourceDocumentRecord,
)


def _write_model_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        model.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def write_source_manifest(path: Path, records: list[SourceDocumentRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [record.model_dump_json() for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_discovery_diagnostics(
    path: Path,
    diagnostics: DiscoveryRunDiagnostics,
) -> None:
    _write_model_json(path, diagnostics)
