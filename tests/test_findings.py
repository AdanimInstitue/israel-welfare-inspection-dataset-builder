from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from welfare_inspections import cli
from welfare_inspections.collect.findings import (
    UnsupportedFindingProductionMode,
    extract_finding_candidates,
)
from welfare_inspections.collect.manifest import (
    read_finding_candidate_manifest,
    write_rendered_page_manifest,
    write_source_manifest,
    write_text_extraction_diagnostics,
)
from welfare_inspections.collect.models import (
    FindingExtractionCandidate,
    RenderedPageArtifact,
    SourceDocumentRecord,
    TextExtractionRecordDiagnostic,
    TextExtractionRunDiagnostics,
)


def test_finding_candidate_schema_validates_required_evidence() -> None:
    candidate = FindingExtractionCandidate.model_validate(_candidate_payload())

    assert candidate.validation_status == "valid"
    assert candidate.evidence[0].raw_excerpt == "ליקוי תברואה נמצא במטבח"

    payload = _candidate_payload()
    payload["evidence"] = []
    with pytest.raises(ValidationError):
        FindingExtractionCandidate.model_validate(payload)


def test_extract_findings_mock_writes_valid_candidates(tmp_path: Path) -> None:
    record = _record("mock")
    manifest_path = tmp_path / "download_manifest.jsonl"
    text_diagnostics_path = _write_text_diagnostics(tmp_path, record)
    render_manifest_path = _write_render_manifest(tmp_path, record)
    mock_response_path = tmp_path / "mock_findings.jsonl"
    output_path = tmp_path / "finding_candidates.jsonl"
    diagnostics_path = tmp_path / "finding_diagnostics.json"
    write_source_manifest(manifest_path, [record])
    _write_jsonl(
        mock_response_path,
        [
            {
                "source_document_id": record.source_document_id,
                "findings": [
                    {
                        "finding_index": 1,
                        "finding_type": "sanitation",
                        "severity": "medium",
                        "finding_text": "ליקוי תברואה נמצא במטבח",
                        "finding_text_normalized": "ליקוי תברואה נמצא במטבח",
                        "recommendation_raw": "לתקן בתוך 30 יום",
                        "legal_refs": ["תקנה 1"],
                        "extraction_method": "llm_text",
                        "page_number": 2,
                        "raw_excerpt": "ליקוי תברואה נמצא במטבח",
                        "confidence": 0.82,
                        "validation_status": "valid",
                    }
                ],
            }
        ],
    )

    candidates, diagnostics = extract_finding_candidates(
        source_manifest_path=manifest_path,
        text_diagnostics_path=text_diagnostics_path,
        render_manifest_path=render_manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        mode="mock",
        mock_response_path=mock_response_path,
    )

    manifest_candidates = read_finding_candidate_manifest(output_path)
    diagnostic_payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert len(candidates) == 1
    assert manifest_candidates == candidates
    assert diagnostics.candidate_records == 1
    assert diagnostics.record_diagnostics[0].status == "extracted"
    assert candidates[0].source_pdf_sha256 == record.pdf_sha256
    assert candidates[0].text_input_sha256 == sha256(
        b"Synthetic finding text\n"
    ).hexdigest()
    assert candidates[0].prompt_input_sha256
    assert candidates[0].finding_type == "sanitation"
    assert diagnostic_payload["candidate_records"] == 1


def test_extract_findings_malformed_candidate_becomes_diagnostic(
    tmp_path: Path,
) -> None:
    record = _record("malformed")
    manifest_path = tmp_path / "download_manifest.jsonl"
    mock_response_path = tmp_path / "mock_findings.jsonl"
    output_path = tmp_path / "finding_candidates.jsonl"
    diagnostics_path = tmp_path / "finding_diagnostics.json"
    write_source_manifest(manifest_path, [record])
    _write_jsonl(
        mock_response_path,
        [
            {
                "source_document_id": record.source_document_id,
                "findings": [
                    {
                        "finding_text": "",
                        "extraction_method": "llm_text",
                        "page_number": 1,
                        "raw_excerpt": "excerpt",
                        "confidence": 0.5,
                        "validation_status": "valid",
                    }
                ],
            }
        ],
    )

    candidates, diagnostics = extract_finding_candidates(
        source_manifest_path=manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        mode="mock",
        mock_response_path=mock_response_path,
    )

    assert candidates == []
    assert output_path.read_text(encoding="utf-8") == ""
    assert diagnostics.record_diagnostics[0].status == "no_candidates"
    assert "candidate_0_validation_failed" in diagnostics.record_diagnostics[
        0
    ].warnings[0]


def test_extract_findings_non_string_finding_text_becomes_diagnostic(
    tmp_path: Path,
) -> None:
    record = _record("non-string-text")
    manifest_path = tmp_path / "download_manifest.jsonl"
    mock_response_path = tmp_path / "mock_findings.jsonl"
    output_path = tmp_path / "finding_candidates.jsonl"
    diagnostics_path = tmp_path / "finding_diagnostics.json"
    write_source_manifest(manifest_path, [record])
    _write_jsonl(
        mock_response_path,
        [
            {
                "source_document_id": record.source_document_id,
                "findings": [
                    {
                        "finding_text": {"unexpected": "object"},
                        "extraction_method": "llm_text",
                        "page_number": 1,
                        "raw_excerpt": "excerpt",
                        "confidence": 0.5,
                        "validation_status": "valid",
                    }
                ],
            }
        ],
    )

    candidates, diagnostics = extract_finding_candidates(
        source_manifest_path=manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        mode="mock",
        mock_response_path=mock_response_path,
    )

    assert candidates == []
    assert output_path.read_text(encoding="utf-8") == ""
    assert "finding_text_raw must be a non-empty string" in (
        diagnostics.record_diagnostics[0].warnings[0]
    )


def test_extract_findings_requires_source_pdf_hash(tmp_path: Path) -> None:
    record = _record("no-hash")
    record.pdf_sha256 = None
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    candidates, diagnostics = extract_finding_candidates(
        source_manifest_path=manifest_path,
        output_path=tmp_path / "finding_candidates.jsonl",
        diagnostics_path=tmp_path / "finding_diagnostics.json",
        mode="dry-run",
    )

    assert candidates == []
    assert diagnostics.failed_records == 1
    assert diagnostics.record_diagnostics[0].errors == [
        "manifest_record_has_no_pdf_sha256"
    ]


def test_extract_findings_dry_run_writes_empty_sidecars(tmp_path: Path) -> None:
    record = _record("dry-run")
    manifest_path = tmp_path / "download_manifest.jsonl"
    output_path = tmp_path / "finding_candidates.jsonl"
    diagnostics_path = tmp_path / "finding_diagnostics.json"
    write_source_manifest(manifest_path, [record])

    candidates, diagnostics = extract_finding_candidates(
        source_manifest_path=manifest_path,
        output_path=output_path,
        diagnostics_path=diagnostics_path,
        mode="dry-run",
    )

    assert candidates == []
    assert output_path.read_text(encoding="utf-8") == ""
    assert diagnostics.record_diagnostics[0].status == "dry_run"
    assert diagnostics.record_diagnostics[0].warnings == [
        "dry_run_no_provider_no_candidates"
    ]


def test_extract_findings_production_mode_fails_closed(tmp_path: Path) -> None:
    record = _record("production")
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    with pytest.raises(UnsupportedFindingProductionMode):
        extract_finding_candidates(
            source_manifest_path=manifest_path,
            output_path=tmp_path / "finding_candidates.jsonl",
            diagnostics_path=tmp_path / "finding_diagnostics.json",
            mode="production",
        )


def test_extract_findings_production_mode_rejects_injected_provider(
    tmp_path: Path,
) -> None:
    record = _record("production-provider")
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])

    with pytest.raises(UnsupportedFindingProductionMode):
        extract_finding_candidates(
            source_manifest_path=manifest_path,
            output_path=tmp_path / "finding_candidates.jsonl",
            diagnostics_path=tmp_path / "finding_diagnostics.json",
            mode="production",
            provider=SimpleProvider(),
        )


def test_extract_findings_rejects_builder_repo_tracked_output_path(
    tmp_path: Path,
) -> None:
    record = _record("bad-output")
    manifest_path = tmp_path / "download_manifest.jsonl"
    write_source_manifest(manifest_path, [record])
    repo_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="outputs/"):
        extract_finding_candidates(
            source_manifest_path=manifest_path,
            output_path=repo_root / "schemas" / "finding_candidates.jsonl",
            diagnostics_path=tmp_path / "finding_diagnostics.json",
            mode="dry-run",
        )


def test_cli_extract_findings_invokes_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_extract_finding_candidates(**kwargs: object) -> object:
        calls.append(kwargs)
        return [], SimpleFindingDiagnostics()

    monkeypatch.setattr(
        cli,
        "extract_finding_candidates",
        fake_extract_finding_candidates,
    )

    cli.extract_findings(
        source_manifest=tmp_path / "download.jsonl",
        text_diagnostics=tmp_path / "text.json",
        render_manifest=tmp_path / "rendered.jsonl",
        output=tmp_path / "findings.jsonl",
        diagnostics=tmp_path / "diagnostics.json",
        mode="mock",
        mock_response_path=tmp_path / "mock.jsonl",
    )

    assert calls[0]["source_manifest_path"] == tmp_path / "download.jsonl"
    assert calls[0]["mode"] == "mock"
    assert "finding_candidates=0" in capsys.readouterr().out


def test_cli_extract_findings_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "extract-findings", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "finding extraction" in result.stdout


def test_finding_schema_contracts_include_runtime_invariants() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_schema = json.loads(
        (repo_root / "schemas/finding_candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )
    diagnostics_schema = json.loads(
        (repo_root / "schemas/finding_extraction_diagnostics.schema.json").read_text(
            encoding="utf-8"
        )
    )
    inspection_schema = json.loads(
        (repo_root / "schemas/inspection.schema.json").read_text(encoding="utf-8")
    )

    assert "evidence" in candidate_schema["required"]
    assert any(
        rule["if"]["properties"]["extraction_method"]["const"] == "llm_text"
        for rule in candidate_schema["allOf"]
    )
    assert any(
        rule["if"]["properties"]["extraction_method"]["const"] == "llm_multimodal"
        for rule in candidate_schema["allOf"]
    )
    assert "record_diagnostics" in diagnostics_schema["properties"]
    assert inspection_schema["properties"]["validation_status"]["enum"] == [
        "valid",
        "invalid",
        "needs_review",
    ]


def test_finding_schema_rejects_null_only_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_schema = json.loads(
        (repo_root / "schemas/finding_candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_item_schema = candidate_schema["properties"]["evidence"]["items"]
    raw_excerpt_rule = evidence_item_schema["anyOf"][0]["properties"][
        "raw_excerpt"
    ]
    visual_locator_rule = evidence_item_schema["anyOf"][1]["properties"][
        "visual_locator"
    ]

    assert raw_excerpt_rule == {"type": "string", "minLength": 1}
    assert visual_locator_rule == {"type": "object"}


def _candidate_payload() -> dict[str, object]:
    return {
        "candidate_id": "finding-candidate-x",
        "source_document_id": "source-doc-x",
        "finding_index": 1,
        "finding_type": "sanitation",
        "severity": "medium",
        "finding_text_raw": "ליקוי תברואה נמצא במטבח",
        "finding_text_normalized": "ליקוי תברואה נמצא במטבח",
        "extraction_method": "llm_text",
        "extractor_version": "finding-candidate-v1",
        "source_pdf_sha256": _sha("pdf"),
        "text_input_sha256": _sha("text"),
        "prompt_id": "prompt",
        "prompt_version": "1",
        "prompt_input_sha256": _sha("prompt"),
        "model_name": "mock",
        "model_version": "1",
        "evidence": [
            {
                "page_number": 1,
                "raw_excerpt": "ליקוי תברואה נמצא במטבח",
            }
        ],
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
    text_path.write_text("Synthetic finding text\n", encoding="utf-8")
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
                    page_count=2,
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
                local_path=str(tmp_path / "rendered-page-x.png"),
            )
        ],
    )
    return path


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class SimpleFindingDiagnostics:
    total_records = 1
    failed_records = 0
    warning_records = 0


class SimpleProvider:
    model_name = "test-provider"
    model_version = "test"

    def extract_findings(self, **kwargs: object) -> list[dict[str, object]]:
        return []
