from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from welfare_inspections import cli
from welfare_inspections.collect.manifest import (
    read_rendered_page_manifest,
    write_source_manifest,
)
from welfare_inspections.collect.models import (
    RenderedPageArtifact,
    SourceDocumentRecord,
)
from welfare_inspections.collect.pdf_download import sha256_file
from welfare_inspections.collect.pdf_render import (
    DEFAULT_RENDER_PROFILE,
    render_pages_from_manifest,
)


def test_render_pages_success_writes_artifacts_manifest_and_diagnostics(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["A", "B"])
    record = _record("render", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    output_manifest_path = tmp_path / "rendered_pages.jsonl"
    diagnostics_path = tmp_path / "render_diagnostics.json"
    page_output_dir = tmp_path / "rendered_pages"
    write_source_manifest(manifest_path, [record])

    artifacts, diagnostics = render_pages_from_manifest(
        source_manifest_path=manifest_path,
        output_manifest_path=output_manifest_path,
        diagnostics_path=diagnostics_path,
        page_output_dir=page_output_dir,
    )

    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    manifest_records = read_rendered_page_manifest(output_manifest_path)
    assert diagnostics.rendered_records == 1
    assert diagnostics.failed_records == 0
    assert len(artifacts) == 2
    assert [artifact.page_number for artifact in artifacts] == [1, 2]
    assert manifest_records == artifacts
    assert payload["artifact_count"] == 2
    assert payload["record_diagnostics"][0]["rendered_artifact_ids"] == [
        artifact.rendered_artifact_id for artifact in artifacts
    ]
    for artifact in artifacts:
        image_path = Path(artifact.local_path)
        assert image_path.is_file()
        assert artifact.image_sha256 == sha256_file(image_path)
        assert artifact.source_pdf_sha256 == record.pdf_sha256
        assert artifact.renderer_name == "pymupdf"
        assert artifact.render_profile_id == DEFAULT_RENDER_PROFILE.render_profile_id
        assert artifact.coordinate_system == (
            DEFAULT_RENDER_PROFILE.coordinate_system
        )
        assert artifact.width_px > 0
        assert artifact.height_px > 0


def test_render_pages_uses_deterministic_paths_and_ids(tmp_path: Path) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["Stable"])
    record = _record("stable", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    first_artifacts, _ = render_pages_from_manifest(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "first.jsonl",
        diagnostics_path=tmp_path / "first.json",
        page_output_dir=tmp_path / "rendered",
    )
    second_artifacts, second_diagnostics = render_pages_from_manifest(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "second.jsonl",
        diagnostics_path=tmp_path / "second.json",
        page_output_dir=tmp_path / "rendered",
    )

    assert second_diagnostics.skipped_existing_records == 1
    assert [artifact.rendered_artifact_id for artifact in first_artifacts] == [
        artifact.rendered_artifact_id for artifact in second_artifacts
    ]
    assert [artifact.local_path for artifact in first_artifacts] == [
        artifact.local_path for artifact in second_artifacts
    ]
    assert [artifact.image_sha256 for artifact in first_artifacts] == [
        artifact.image_sha256 for artifact in second_artifacts
    ]


def test_rendered_artifact_schema_rejects_missing_required_provenance() -> None:
    with pytest.raises(ValueError):
        RenderedPageArtifact.model_validate(
            {
                "rendered_artifact_id": "rendered-page-x",
                "source_document_id": "source-doc-x",
                "page_number": 1,
                "artifact_type": "page",
                "renderer_name": "pymupdf",
            }
        )


def test_render_pages_records_missing_pdf_and_checksum_diagnostics(
    tmp_path: Path,
) -> None:
    missing_record = _record("missing", tmp_path / "missing.pdf")
    missing_checksum_record = _record(
        "no-checksum",
        _synthetic_pdf(tmp_path / "x.pdf", ["X"]),
    )
    missing_checksum_record = missing_checksum_record.model_copy(
        update={"pdf_sha256": None}
    )
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [missing_record, missing_checksum_record])

    _, diagnostics = render_pages_from_manifest(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "rendered.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        page_output_dir=tmp_path / "rendered",
    )

    assert diagnostics.failed_records == 2
    assert diagnostics.missing_pdf_records == 1
    assert diagnostics.missing_checksum_records == 1
    assert [record.status for record in diagnostics.record_diagnostics] == [
        "missing_pdf",
        "missing_checksum",
    ]


def test_render_pages_rejects_generated_outputs_inside_tracked_repo_paths(
    tmp_path: Path,
) -> None:
    pdf_path = _synthetic_pdf(tmp_path / "report.pdf", ["A"])
    record = _record("bad-output", pdf_path)
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])
    repo_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="outputs/"):
        render_pages_from_manifest(
            source_manifest_path=manifest_path,
            output_manifest_path=repo_root / "schemas" / "rendered.jsonl",
            diagnostics_path=tmp_path / "diagnostics.json",
            page_output_dir=tmp_path / "rendered",
        )


def test_cli_render_pages_invokes_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_render_pages_from_manifest(**kwargs: object) -> object:
        calls.append(kwargs)
        return [], SimpleRenderDiagnostics()

    monkeypatch.setattr(
        cli,
        "render_pages_from_manifest",
        fake_render_pages_from_manifest,
    )

    cli.render_pages(
        source_manifest=tmp_path / "download.jsonl",
        output_manifest=tmp_path / "rendered.jsonl",
        page_output_dir=tmp_path / "pages",
        diagnostics=tmp_path / "diagnostics.json",
        overwrite=True,
    )

    assert calls[0]["source_manifest_path"] == tmp_path / "download.jsonl"
    assert calls[0]["output_manifest_path"] == tmp_path / "rendered.jsonl"
    assert calls[0]["page_output_dir"] == tmp_path / "pages"
    assert calls[0]["diagnostics_path"] == tmp_path / "diagnostics.json"
    assert calls[0]["overwrite"] is True
    assert "Processed 1 source records" in capsys.readouterr().out


def test_cli_render_pages_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "render-pages", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "render" in result.stdout


def _synthetic_pdf(path: Path, page_texts: list[str]) -> Path:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _record(name: str, pdf_path: Path) -> SourceDocumentRecord:
    return SourceDocumentRecord(
        source_document_id=f"source-doc-{name}",
        govil_item_slug=name,
        govil_item_url=f"https://www.gov.il/item/{name}",
        pdf_url=f"https://www.gov.il/{name}.pdf",
        title=f"Report {name}",
        language_path="/he/",
        pdf_sha256=sha256_file(pdf_path) if pdf_path.exists() else None,
        local_path=str(pdf_path),
        collector_version="0.1.0",
    )


class SimpleRenderDiagnostics:
    total_records = 1
    rendered_records = 1
    failed_records = 0
