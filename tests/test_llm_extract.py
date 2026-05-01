from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from welfare_inspections import cli
from welfare_inspections.collect.llm_extract import (
    MissingProviderConfiguration,
    extract_llm_candidates,
)
from welfare_inspections.collect.manifest import (
    read_llm_candidate_manifest,
    write_rendered_page_manifest,
    write_source_manifest,
    write_text_extraction_diagnostics,
)
from welfare_inspections.collect.models import (
    LLMExtractionCandidate,
    RenderedPageArtifact,
    SourceDocumentRecord,
    TextExtractionRecordDiagnostic,
    TextExtractionRunDiagnostics,
)


def test_llm_candidate_schema_validates_required_input_identity() -> None:
    valid = _candidate_payload()
    candidate = LLMExtractionCandidate.model_validate(valid)

    assert candidate.validation_status == "valid"
    assert candidate.text_input_sha256 == _sha("text")

    invalid = dict(valid)
    invalid.pop("source_pdf_sha256")
    with pytest.raises(ValidationError):
        LLMExtractionCandidate.model_validate(invalid)


def test_llm_candidate_schema_rejects_malformed_date() -> None:
    payload = _candidate_payload(
        field_name="visit_date",
        normalized_value="2026-99-99",
    )

    with pytest.raises(ValidationError):
        LLMExtractionCandidate.model_validate(payload)


def test_extract_llm_dry_run_writes_empty_candidates_and_diagnostics(
    tmp_path: Path,
) -> None:
    record = _record("dry-run")
    manifest_path = tmp_path / "download_manifest.jsonl"
    output_path = tmp_path / "candidates.jsonl"
    diagnostics_path = tmp_path / "diagnostics.json"
    write_source_manifest(manifest_path, [record])

    candidates, diagnostics = extract_llm_candidates(
        source_manifest_path=manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        mode="dry-run",
    )

    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert candidates == []
    assert output_path.read_text(encoding="utf-8") == ""
    assert diagnostics.total_records == 1
    assert diagnostics.candidate_records == 0
    assert payload["record_diagnostics"][0]["status"] == "dry_run"
    assert payload["record_diagnostics"][0]["warnings"] == [
        "dry_run_no_provider_no_candidates"
    ]


def test_extract_llm_mock_response_validates_candidates_and_eval_report(
    tmp_path: Path,
) -> None:
    record = _record("mock")
    manifest_path = tmp_path / "download_manifest.jsonl"
    text_diagnostics_path = _write_text_diagnostics(tmp_path, record)
    render_manifest_path = _write_render_manifest(tmp_path, record)
    mock_response_path = tmp_path / "mock_responses.jsonl"
    fixture_path = tmp_path / "expected.jsonl"
    output_path = tmp_path / "candidates.jsonl"
    diagnostics_path = tmp_path / "diagnostics.json"
    eval_report_path = tmp_path / "eval_report.json"
    write_source_manifest(manifest_path, [record])
    _write_jsonl(
        mock_response_path,
        [
            {
                "source_document_id": record.source_document_id,
                "candidates": [
                    {
                        "field_name": "facility_name",
                        "raw_value": "בית לדוגמה",
                        "normalized_value": "בית לדוגמה",
                        "extraction_method": "llm_text",
                        "page_number": 1,
                        "raw_excerpt": "שם המסגרת: בית לדוגמה",
                        "confidence": 0.91,
                        "validation_status": "valid",
                    },
                    {
                        "field_name": "visit_date",
                        "raw_value": "99/99/2026",
                        "normalized_value": "2026-99-99",
                        "extraction_method": "llm_text",
                        "page_number": 1,
                        "raw_excerpt": "תאריך בקרה: 99/99/2026",
                        "confidence": 0.3,
                        "validation_status": "valid",
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        fixture_path,
        [
            {
                "source_document_id": record.source_document_id,
                "field_name": "facility_name",
                "expected_normalized_value": "בית לדוגמה",
            }
        ],
    )

    candidates, diagnostics = extract_llm_candidates(
        source_manifest_path=manifest_path,
        text_diagnostics_path=text_diagnostics_path,
        render_manifest_path=render_manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        eval_fixtures_path=fixture_path,
        eval_report_path=eval_report_path,
        mode="mock",
        mock_response_path=mock_response_path,
    )

    manifest_candidates = read_llm_candidate_manifest(output_path)
    report = json.loads(eval_report_path.read_text(encoding="utf-8"))
    assert len(candidates) == 1
    assert manifest_candidates == candidates
    assert diagnostics.candidate_records == 1
    assert diagnostics.warning_records == 1
    assert diagnostics.record_diagnostics[0].status == "extracted"
    assert "candidate_1_validation_failed" in (
        diagnostics.record_diagnostics[0].warnings[0]
    )
    candidate = candidates[0]
    assert candidate.source_pdf_sha256 == record.pdf_sha256
    assert candidate.text_input_sha256 == sha256(
        b"Synthetic extracted text\n"
    ).hexdigest()
    assert candidate.prompt_input_sha256
    assert candidate.model_name == "mock-llm"
    assert report["expected_field_count"] == 1
    assert report["correct_field_count"] == 1
    assert report["renderer_name"] == "pymupdf"


def test_extract_llm_multimodal_candidate_requires_rendered_hashes(
    tmp_path: Path,
) -> None:
    record = _record("multimodal")
    manifest_path = tmp_path / "download_manifest.jsonl"
    render_manifest_path = _write_render_manifest(tmp_path, record)
    mock_response_path = tmp_path / "mock_responses.jsonl"
    write_source_manifest(manifest_path, [record])
    _write_jsonl(
        mock_response_path,
        [
            {
                "source_document_id": record.source_document_id,
                "candidates": [
                    {
                        "field_name": "facility_type",
                        "raw_value": "דיור",
                        "normalized_value": "דיור",
                        "extraction_method": "llm_multimodal",
                        "field_evidence": {
                            "page_number": 1,
                            "visual_locator": {
                                "rendered_artifact_id": "rendered-page-x",
                                "coordinate_system": (
                                    "pixel_top_left_origin_1_based_page"
                                ),
                                "bounding_box": {
                                    "x": 1,
                                    "y": 2,
                                    "width": 30,
                                    "height": 40,
                                },
                            },
                        },
                        "confidence": 0.8,
                        "validation_status": "valid",
                    }
                ],
            }
        ],
    )

    candidates, _ = extract_llm_candidates(
        source_manifest_path=manifest_path,
        render_manifest_path=render_manifest_path,
        output_path=tmp_path / "candidates.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        mode="mock",
        mock_response_path=mock_response_path,
    )

    assert candidates[0].rendered_artifact_ids == ["rendered-page-x"]
    assert candidates[0].rendered_artifact_sha256s == [_sha("image")]


def test_extract_llm_production_mode_fails_closed_without_provider_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record("production")
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])
    monkeypatch.delenv("WELFARE_INSPECTIONS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("WELFARE_INSPECTIONS_LLM_MODEL", raising=False)

    with pytest.raises(MissingProviderConfiguration):
        extract_llm_candidates(
            source_manifest_path=manifest_path,
            output_path=tmp_path / "candidates.jsonl",
            diagnostics_path=tmp_path / "diagnostics.json",
            mode="production",
        )


def test_cli_extract_llm_invokes_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_extract_llm_candidates(**kwargs: object) -> object:
        calls.append(kwargs)
        return [], SimpleLLMDiagnostics()

    monkeypatch.setattr(cli, "extract_llm_candidates", fake_extract_llm_candidates)

    cli.extract_llm(
        source_manifest=tmp_path / "download.jsonl",
        text_diagnostics=tmp_path / "text.json",
        render_manifest=tmp_path / "rendered.jsonl",
        output=tmp_path / "candidates.jsonl",
        diagnostics=tmp_path / "diagnostics.json",
        eval_fixtures=tmp_path / "expected.jsonl",
        eval_report=tmp_path / "eval.json",
        mode="mock",
        mock_response_path=tmp_path / "mock.jsonl",
    )

    assert calls[0]["source_manifest_path"] == tmp_path / "download.jsonl"
    assert calls[0]["text_diagnostics_path"] == tmp_path / "text.json"
    assert calls[0]["render_manifest_path"] == tmp_path / "rendered.jsonl"
    assert calls[0]["mode"] == "mock"
    assert "Processed 1 source records" in capsys.readouterr().out


def test_cli_extract_llm_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "extract-llm", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "LLM extraction" in result.stdout


def _candidate_payload(
    field_name: str = "facility_name",
    normalized_value: str = "Example",
) -> dict[str, object]:
    return {
        "candidate_id": "llm-candidate-x",
        "source_document_id": "source-doc-x",
        "field_name": field_name,
        "raw_value": str(normalized_value),
        "normalized_value": normalized_value,
        "extraction_method": "llm_text",
        "extractor_version": "llm-candidate-v1",
        "source_pdf_sha256": _sha("pdf"),
        "text_input_sha256": _sha("text"),
        "rendered_artifact_ids": [],
        "rendered_artifact_sha256s": [],
        "prompt_id": "prompt",
        "prompt_version": "1",
        "prompt_input_sha256": _sha("prompt"),
        "model_name": "mock",
        "model_version": "1",
        "field_evidence": {
            "page_number": 1,
            "raw_excerpt": "Example",
        },
        "confidence": 0.9,
        "validation_status": "valid",
    }


def _record(name: str) -> SourceDocumentRecord:
    return SourceDocumentRecord(
        source_document_id=f"source-doc-{name}",
        govil_item_slug=name,
        govil_item_url=f"https://www.gov.il/item/{name}",
        pdf_url=f"https://www.gov.il/{name}.pdf",
        title=f"Report {name}",
        language_path="/he/",
        pdf_sha256=_sha(f"pdf-{name}"),
        local_path=f"/ignored/{name}.pdf",
        collector_version="0.1.0",
    )


def _write_text_diagnostics(tmp_path: Path, record: SourceDocumentRecord) -> Path:
    text_path = tmp_path / "text.txt"
    text_path.write_text("Synthetic extracted text\n", encoding="utf-8")
    path = tmp_path / "text_diagnostics.json"
    write_text_extraction_diagnostics(
        path,
        TextExtractionRunDiagnostics(
            source_manifest_path=str(tmp_path / "download_manifest.jsonl"),
            text_output_dir=str(tmp_path),
            total_records=1,
            extracted_records=1,
            record_diagnostics=[
                TextExtractionRecordDiagnostic(
                    source_document_id=record.source_document_id,
                    govil_item_url=record.govil_item_url,
                    pdf_url=record.pdf_url,
                    pdf_sha256=record.pdf_sha256,
                    local_path=record.local_path,
                    status="extracted",
                    text_path=str(text_path),
                    page_count=1,
                )
            ],
        ),
    )
    return path


def _write_render_manifest(tmp_path: Path, record: SourceDocumentRecord) -> Path:
    path = tmp_path / "rendered_pages.jsonl"
    write_rendered_page_manifest(
        path,
        [
            RenderedPageArtifact(
                rendered_artifact_id="rendered-page-x",
                source_document_id=record.source_document_id,
                source_pdf_sha256=record.pdf_sha256 or _sha("pdf"),
                page_number=1,
                artifact_type="page",
                renderer_name="pymupdf",
                renderer_version="1",
                render_profile_id="default-v1",
                render_profile_version="1",
                dpi=144,
                colorspace="rgb",
                image_format="png",
                rotation_degrees=0,
                coordinate_system="pixel_top_left_origin_1_based_page",
                width_px=100,
                height_px=200,
                image_sha256=_sha("image"),
                local_path=str(tmp_path / "page.png"),
            )
        ],
    )
    return path


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class SimpleLLMDiagnostics:
    total_records = 1
    failed_records = 0
    warning_records = 0
