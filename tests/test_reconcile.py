from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from welfare_inspections import cli
from welfare_inspections.collect.models import (
    MetadataField,
    MetadataParseRunDiagnostics,
    MetadataParseWarning,
    ReportMetadataRecord,
)
from welfare_inspections.collect.reconcile import (
    reconcile_report_metadata,
    run_backfill_dry_run,
)


def test_reconcile_accepts_deterministic_only_candidates(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-det", "report-det")
    metadata_path = _write_metadata(tmp_path, [record])

    reconciled, diagnostics = reconcile_report_metadata(
        metadata_path=metadata_path,
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.accepted_decisions == len(record.fields)
    assert diagnostics.needs_review_decisions == 0
    assert reconciled[0].reconciliation_status == "accepted"
    assert reconciled[0].reconciled_fields["facility_name"] == "בית חם"
    decision = _decision(reconciled[0], "facility_name")
    assert decision.decision_status == "accepted"
    assert decision.decision_method == "deterministic_only"
    assert decision.accepted_candidate_id
    assert decision.candidate_ids == [decision.accepted_candidate_id]


def test_reconcile_accepts_when_deterministic_and_llm_agree(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-agree", "report-agree")
    llm_path = _write_llm_candidates(
        tmp_path,
        [
            _llm_candidate(
                source_document_id=record.source_document_id,
                report_id=record.report_id,
                field_name="facility_name",
                value="בית חם",
            )
        ],
    )

    reconciled, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        llm_candidates_path=llm_path,
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    decision = _decision(reconciled[0], "facility_name")
    assert diagnostics.needs_review_decisions == 0
    assert decision.decision_status == "accepted"
    assert decision.decision_method == "deterministic_llm_agreement"
    assert set(reconciled[0].accepted_extraction_methods["facility_name"]) == {
        "deterministic",
        "llm_text",
    }
    assert reconciled[0].llm_candidate_ids["facility_name"] == [
        "llm-candidate-facility_name"
    ]


def test_reconcile_keeps_conflicts_as_needs_review(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-conflict", "report-conflict")
    llm_path = _write_llm_candidates(
        tmp_path,
        [
            _llm_candidate(
                source_document_id=record.source_document_id,
                report_id=record.report_id,
                field_name="facility_name",
                value="בית אחר",
            )
        ],
    )

    reconciled, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        llm_candidates_path=llm_path,
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    decision = _decision(reconciled[0], "facility_name")
    assert diagnostics.needs_review_decisions == 1
    assert decision.decision_status == "needs_review"
    assert decision.accepted_candidate_id is None
    assert len(decision.candidate_ids) == 2
    assert "facility_name" not in reconciled[0].reconciled_fields


def test_reconcile_records_malformed_llm_candidate_provenance(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-bad-llm", "report-bad-llm")
    bad = _llm_candidate(
        source_document_id=record.source_document_id,
        report_id=record.report_id,
        field_name="facility_name",
        value="בית חם",
    )
    bad.pop("prompt_input_sha256")
    llm_path = _write_jsonl(tmp_path / "llm.jsonl", [bad])

    _, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        llm_candidates_path=llm_path,
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.validation_failed_records == 1
    assert diagnostics.record_diagnostics[0].status == (
        "llm_candidate_validation_failed"
    )
    assert any(
        "prompt_input_sha256" in error
        for error in diagnostics.record_diagnostics[0].errors
    )


def test_reconcile_fails_when_explicit_llm_manifest_is_missing(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-missing-llm", "report-missing-llm")

    with pytest.raises(ValueError, match="LLM candidate manifest does not exist"):
        reconcile_report_metadata(
            metadata_path=_write_metadata(tmp_path, [record]),
            metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
            llm_candidates_path=tmp_path / "missing-llm.jsonl",
            output_path=tmp_path / "reconciled.jsonl",
            diagnostics_path=tmp_path / "reconciliation.json",
        )


def test_reconcile_matches_llm_candidates_by_source_when_report_id_is_stale(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-stale-report", "report-current")
    llm_path = _write_llm_candidates(
        tmp_path,
        [
            _llm_candidate(
                source_document_id=record.source_document_id,
                report_id="report-stale",
                field_name="facility_name",
                value="בית חם",
            )
        ],
    )

    reconciled, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        llm_candidates_path=llm_path,
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    decision = _decision(reconciled[0], "facility_name")
    assert diagnostics.needs_review_decisions == 0
    assert decision.decision_method == "deterministic_llm_agreement"
    assert decision.candidate_ids == [
        decision.accepted_candidate_id,
        "llm-candidate-facility_name",
    ]


def test_reconcile_records_duplicate_candidate_ids(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-duplicate-candidate", "report-dup-cand")
    candidate = _llm_candidate(
        source_document_id=record.source_document_id,
        report_id=record.report_id,
        field_name="facility_name",
        value="בית חם",
    )
    llm_path = _write_jsonl(tmp_path / "llm.jsonl", [candidate, candidate])

    _, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        llm_candidates_path=llm_path,
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.duplicate_candidate_id_records == 1
    assert diagnostics.record_diagnostics[-1].warnings


def test_reconcile_records_duplicate_decision_ids_for_duplicate_reports(
    tmp_path: Path,
) -> None:
    first = _metadata_record("source-doc-first", "report-duplicate")
    second = _metadata_record("source-doc-second", "report-duplicate")

    _, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [first, second]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.reconciled_records == 1
    assert diagnostics.duplicate_decision_id_records == len(second.fields)
    assert diagnostics.record_diagnostics[-1].status == "duplicate_report_id"


def test_backfill_dry_run_writes_diagnostics(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-backfill", "report-backfill")
    reconciled, _ = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )
    eval_report = tmp_path / "eval.json"
    eval_report.write_text(
        json.dumps(
            {
                "model_version": "offline-v1",
                "prompt_version": "1",
                "renderer_version": "pymupdf-1",
                "render_profile_version": "1",
            }
        ),
        encoding="utf-8",
    )

    diagnostics = run_backfill_dry_run(
        reconciled_metadata_path=tmp_path / "reconciled.jsonl",
        output_path=tmp_path / "backfill.json",
        evaluation_report_path=eval_report,
    )

    payload = json.loads((tmp_path / "backfill.json").read_text(encoding="utf-8"))
    assert len(reconciled) == 1
    assert diagnostics.changed_count == 0
    assert diagnostics.no_baseline_count == len(record.fields)
    assert diagnostics.unresolved_count == 0
    assert diagnostics.input_hashes["reconciled_metadata_sha256"]
    assert diagnostics.prompt_versions["prompt_version"] == "1"
    assert payload["field_changes"][0]["before_value"] is None
    assert payload["field_changes"][0]["status"] == "no_baseline"


def test_reconcile_and_backfill_reject_tracked_repo_output_paths(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-guard", "report-guard")
    repo_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="outputs/"):
        reconcile_report_metadata(
            metadata_path=_write_metadata(tmp_path, [record]),
            metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
            output_path=repo_root / "docs" / "bad-reconciled.jsonl",
            diagnostics_path=tmp_path / "reconciliation.json",
        )

    with pytest.raises(ValueError, match="outputs/"):
        run_backfill_dry_run(
            reconciled_metadata_path=tmp_path / "missing.jsonl",
            output_path=repo_root / "docs" / "bad-backfill.json",
        )


def test_cli_reconcile_and_backfill_invoke_plumbing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reconcile_calls: list[dict[str, object]] = []
    backfill_calls: list[dict[str, object]] = []

    def fake_reconcile_report_metadata(**kwargs: object) -> object:
        reconcile_calls.append(kwargs)
        return [object()], SimpleReconciliationDiagnostics()

    def fake_run_backfill_dry_run(**kwargs: object) -> object:
        backfill_calls.append(kwargs)
        return SimpleBackfillDiagnostics()

    monkeypatch.setattr(
        cli,
        "reconcile_report_metadata",
        fake_reconcile_report_metadata,
    )
    monkeypatch.setattr(cli, "run_backfill_dry_run", fake_run_backfill_dry_run)

    cli.reconcile(
        metadata=tmp_path / "metadata.jsonl",
        metadata_diagnostics=tmp_path / "metadata-diagnostics.json",
        llm_candidates=tmp_path / "llm.jsonl",
        output=tmp_path / "reconciled.jsonl",
        diagnostics=tmp_path / "reconciliation.json",
    )
    cli.backfill(
        reconciled_metadata=tmp_path / "reconciled.jsonl",
        output=tmp_path / "backfill.json",
        evaluation_report=tmp_path / "eval.json",
        dry_run=True,
    )

    assert reconcile_calls[0]["metadata_path"] == tmp_path / "metadata.jsonl"
    assert backfill_calls[0]["reconciled_metadata_path"] == (
        tmp_path / "reconciled.jsonl"
    )
    output = capsys.readouterr().out
    assert "reconciled=1" in output
    assert "Backfill dry-run" in output
    assert "no_baseline=1" in output


def test_cli_reconcile_and_backfill_help_works() -> None:
    for command, expected in [
        ("reconcile", "reconcile deterministic"),
        ("backfill", "dry-run backfill"),
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "welfare_inspections.cli", command, "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert expected in result.stdout


def test_reconciliation_schema_files_exist_and_name_core_fields() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    decision_schema = json.loads(
        (repo_root / "schemas/reconciliation_decision.schema.json").read_text(
            encoding="utf-8"
        )
    )
    diagnostics_schema = json.loads(
        (repo_root / "schemas/backfill_diagnostics.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert "accepted_candidate_id" in decision_schema["properties"]
    assert "candidate_ids" in decision_schema["properties"]
    assert "input_hashes" in diagnostics_schema["properties"]
    assert "no_baseline_count" in diagnostics_schema["properties"]
    assert "field_changes" in diagnostics_schema["properties"]


def _metadata_record(source_document_id: str, report_id: str) -> ReportMetadataRecord:
    return ReportMetadataRecord(
        report_id=report_id,
        source_document_id=source_document_id,
        govil_item_url=f"https://www.gov.il/item/{source_document_id}",
        pdf_url=f"https://www.gov.il/{source_document_id}.pdf",
        pdf_sha256=_sha(f"pdf-{source_document_id}"),
        extraction_status="extracted",
        extraction_confidence=0.95,
        fields={
            "facility_name": MetadataField(
                field_name="facility_name",
                raw_value="בית חם",
                normalized_value="בית חם",
                raw_excerpt="שם המסגרת: בית חם",
                page_number=1,
                confidence=0.9,
            ),
            "visit_date": MetadataField(
                field_name="visit_date",
                raw_value="01/02/2024",
                normalized_value=date(2024, 2, 1),
                raw_excerpt="תאריך ביקור: 01/02/2024",
                page_number=1,
                confidence=0.9,
            ),
        },
        warnings=[
            MetadataParseWarning(
                warning_id=f"warning-{report_id}",
                source_document_id=source_document_id,
                report_id=report_id,
                message="synthetic warning",
            )
        ],
    )


def _llm_candidate(
    *,
    source_document_id: str,
    report_id: str,
    field_name: str,
    value: str,
) -> dict[str, object]:
    return {
        "candidate_id": f"llm-candidate-{field_name}",
        "source_document_id": source_document_id,
        "report_id": report_id,
        "field_name": field_name,
        "raw_value": value,
        "normalized_value": value,
        "extraction_method": "llm_text",
        "extractor_version": "llm-candidate-v1",
        "source_pdf_sha256": _sha(f"pdf-{source_document_id}"),
        "text_input_sha256": _sha(f"text-{source_document_id}"),
        "rendered_artifact_ids": [],
        "rendered_artifact_sha256s": [],
        "prompt_id": "report-metadata-extraction",
        "prompt_version": "1",
        "prompt_input_sha256": _sha(f"prompt-{source_document_id}-{field_name}"),
        "model_name": "mock-llm",
        "model_version": "offline-v1",
        "field_evidence": {
            "page_number": 1,
            "raw_excerpt": value,
        },
        "confidence": 0.91,
        "validation_status": "valid",
        "validation_errors": [],
    }


def _write_metadata(tmp_path: Path, records: list[ReportMetadataRecord]) -> Path:
    path = tmp_path / "metadata.jsonl"
    _write_jsonl(path, [record.model_dump(mode="json") for record in records])
    return path


def _write_metadata_diagnostics(tmp_path: Path) -> Path:
    path = tmp_path / "metadata-diagnostics.json"
    diagnostics = MetadataParseRunDiagnostics(
        text_diagnostics_path=str(tmp_path / "text-diagnostics.json"),
        output_path=str(tmp_path / "metadata.jsonl"),
    )
    path.write_text(diagnostics.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _write_llm_candidates(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    return _write_jsonl(tmp_path / "llm.jsonl", records)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _decision(record: object, field_name: str) -> object:
    return next(
        decision
        for decision in record.decisions
        if decision.field_name == field_name
    )


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class SimpleReconciliationDiagnostics:
    total_records = 1
    accepted_decisions = 1
    needs_review_decisions = 0


class SimpleBackfillDiagnostics:
    field_changes = [object()]
    changed_count = 0
    no_baseline_count = 1
    unresolved_count = 0
    rejected_count = 0
