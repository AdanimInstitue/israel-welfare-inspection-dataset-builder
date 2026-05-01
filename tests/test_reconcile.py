from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from welfare_inspections import cli
from welfare_inspections.collect import reconcile as reconcile_module
from welfare_inspections.collect.manifest import (
    read_reconciled_metadata_manifest,
    write_reconciled_metadata_manifest,
)
from welfare_inspections.collect.models import (
    BackfillFieldChange,
    BackfillRunDiagnostics,
    ExtractionCandidate,
    MetadataField,
    MetadataParseRunDiagnostics,
    MetadataParseWarning,
    ReconciliationDecision,
    ReconciliationRecordDiagnostic,
    ReconciliationRunDiagnostics,
    ReportMetadataRecord,
)
from welfare_inspections.collect.reconcile import (
    RECONCILER_VERSION,
    RECONCILIATION_SCHEMA_VERSION,
    _backfill_status,
    _candidate_by_id,
    _comparable,
    _count_decision,
    _decision_for_field,
    _extract_optional_id,
    _read_required_metadata_diagnostics,
    _validation_errors,
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


def test_extraction_candidate_requires_method_specific_llm_identity() -> None:
    missing_pdf = _extraction_candidate_payload(extraction_method="llm_text")
    missing_pdf.pop("source_pdf_sha256")
    with pytest.raises(ValidationError, match="source_pdf_sha256"):
        ExtractionCandidate.model_validate(missing_pdf)

    missing_prompt_hash = _extraction_candidate_payload(extraction_method="llm_text")
    missing_prompt_hash.pop("prompt_input_sha256")
    with pytest.raises(ValidationError, match="prompt_input_sha256"):
        ExtractionCandidate.model_validate(missing_prompt_hash)

    missing_prompt_id = _extraction_candidate_payload(extraction_method="llm_text")
    missing_prompt_id["prompt_id"] = None
    with pytest.raises(ValidationError, match="prompt_id"):
        ExtractionCandidate.model_validate(missing_prompt_id)

    missing_prompt_version = _extraction_candidate_payload(extraction_method="llm_text")
    missing_prompt_version["prompt_version"] = None
    with pytest.raises(ValidationError, match="prompt_version"):
        ExtractionCandidate.model_validate(missing_prompt_version)

    llm_text = _extraction_candidate_payload(extraction_method="llm_text")
    llm_text.pop("text_input_sha256")

    with pytest.raises(ValidationError, match="text_input_sha256"):
        ExtractionCandidate.model_validate(llm_text)

    multimodal = _extraction_candidate_payload(
        extraction_method="llm_multimodal",
    )
    multimodal["text_input_sha256"] = None
    multimodal["rendered_artifact_ids"] = []

    with pytest.raises(ValidationError, match="rendered_artifact_ids"):
        ExtractionCandidate.model_validate(multimodal)

    mismatched = _extraction_candidate_payload(
        extraction_method="llm_multimodal",
    )
    mismatched["text_input_sha256"] = None
    mismatched["rendered_artifact_sha256s"] = [_sha("rendered-a"), _sha("rendered-b")]

    with pytest.raises(ValidationError, match="Rendered artifact ID"):
        ExtractionCandidate.model_validate(mismatched)


def test_extraction_candidate_allows_reconciler_llm_method() -> None:
    candidate = ExtractionCandidate.model_validate(
        _extraction_candidate_payload(extraction_method="reconciler_llm")
    )

    assert candidate.extraction_method == "reconciler_llm"


def test_extraction_candidate_records_missing_evidence_warning() -> None:
    payload = _extraction_candidate_payload(extraction_method="deterministic")
    payload["raw_excerpt"] = None

    candidate = ExtractionCandidate.model_validate(payload)

    assert "candidate_has_no_field_evidence" in candidate.warnings


def test_extraction_candidate_rejects_malformed_date_normalization() -> None:
    payload = _extraction_candidate_payload(
        extraction_method="deterministic",
        field_name="visit_date",
        normalized_value="2026-99-99",
    )

    with pytest.raises(ValidationError, match="ISO date"):
        ExtractionCandidate.model_validate(payload)


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


def test_reconcile_records_malformed_metadata_rows_as_diagnostics(
    tmp_path: Path,
) -> None:
    payload = _metadata_record("source-doc-malformed", "report-malformed").model_dump(
        mode="json"
    )
    del payload["report_id"]

    _, diagnostics = reconcile_report_metadata(
        metadata_path=_write_jsonl(tmp_path / "metadata.jsonl", [payload]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.validation_failed_records == 1
    assert diagnostics.record_diagnostics[0].status == "validation_failed"
    assert any(
        "report_id" in error
        for error in diagnostics.record_diagnostics[0].errors
    )


def test_reconciled_metadata_manifest_round_trip_and_invalid_rows(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-manifest", "report-manifest")
    reconciled, _ = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )
    round_trip_path = tmp_path / "round-trip.jsonl"
    write_reconciled_metadata_manifest(round_trip_path, reconciled)
    round_trip_path.write_text(
        "\n" + round_trip_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert read_reconciled_metadata_manifest(round_trip_path) == reconciled

    invalid_path = tmp_path / "invalid-reconciled.jsonl"
    invalid_path.write_text("{\"report_id\": 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid reconciled metadata JSONL"):
        read_reconciled_metadata_manifest(invalid_path)


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


def test_backfill_dry_run_counts_rejected_and_unresolved_decisions(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-backfill-status", "report-backfill-status")
    reconciled, _ = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )
    reconciled_record = reconciled[0]
    reconciled_record.decisions = [
        ReconciliationDecision(
            decision_id="decision-rejected",
            report_id=reconciled_record.report_id,
            source_document_id=reconciled_record.source_document_id,
            field_name="facility_name",
            decision_status="rejected",
            decision_method="test_rejection",
            schema_version="reconciliation-v1",
            reconciler_version="reconciler-v1",
        ),
        ReconciliationDecision(
            decision_id="decision-unresolved",
            report_id=reconciled_record.report_id,
            source_document_id=reconciled_record.source_document_id,
            field_name="visit_date",
            decision_status="unresolved",
            decision_method="test_unresolved",
            schema_version="reconciliation-v1",
            reconciler_version="reconciler-v1",
        ),
    ]
    write_reconciled_metadata_manifest(tmp_path / "reconciled.jsonl", reconciled)

    diagnostics = run_backfill_dry_run(
        reconciled_metadata_path=tmp_path / "reconciled.jsonl",
        output_path=tmp_path / "backfill.json",
    )

    assert diagnostics.rejected_count == 1
    assert diagnostics.unresolved_count == 1
    assert {change.status for change in diagnostics.field_changes} == {
        "rejected",
        "unresolved",
    }


def test_backfill_dry_run_counts_changed_and_unchanged_when_baseline_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _metadata_record("source-doc-backfill-baseline", "report-backfill-base")
    reconciled, _ = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )
    statuses = iter(["changed", "unchanged"])

    monkeypatch.setattr(
        reconcile_module,
        "_backfill_status",
        lambda decision: next(statuses),
    )

    diagnostics = run_backfill_dry_run(
        reconciled_metadata_path=tmp_path / "reconciled.jsonl",
        output_path=tmp_path / "backfill.json",
    )

    assert len(reconciled) == 1
    assert diagnostics.changed_count == 1
    assert diagnostics.unchanged_count == 1


def test_backfill_diagnostics_accepts_unchanged_status() -> None:
    diagnostics = BackfillRunDiagnostics(
        reconciled_metadata_path="outputs/reconciled.jsonl",
        output_path="outputs/backfill.json",
        schema_version="reconciliation-v1",
        reconciler_version="reconciler-v1",
        unchanged_count=1,
        field_changes=[
            BackfillFieldChange(
                report_id="report-unchanged",
                source_document_id="source-doc-unchanged",
                field_name="facility_name",
                before_value="בית חם",
                after_value="בית חם",
                status="unchanged",
            )
        ],
    )

    assert diagnostics.unchanged_count == 1


def test_reconcile_keeps_llm_only_candidates_as_needs_review(
    tmp_path: Path,
) -> None:
    record = _metadata_record("source-doc-llm-only", "report-llm-only")
    record.fields = {}
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
    assert diagnostics.needs_review_decisions == 1
    assert decision.decision_method == "llm_only_requires_review"
    assert "facility_name" not in reconciled[0].reconciled_fields


def test_reconcile_handles_empty_report_as_unresolved(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-empty", "report-empty")
    record.fields = {}

    reconciled, diagnostics = reconcile_report_metadata(
        metadata_path=_write_metadata(tmp_path, [record]),
        metadata_diagnostics_path=_write_metadata_diagnostics(tmp_path),
        output_path=tmp_path / "reconciled.jsonl",
        diagnostics_path=tmp_path / "reconciliation.json",
    )

    assert diagnostics.reconciled_records == 1
    assert reconciled[0].reconciliation_status == "unresolved"


def test_reconciliation_private_helpers_cover_error_branches(tmp_path: Path) -> None:
    record = _metadata_record("source-doc-private", "report-private")
    rejected_decision = ReconciliationDecision(
        decision_id="decision-rejected",
        report_id=record.report_id,
        source_document_id=record.source_document_id,
        field_name="facility_name",
        decision_status="rejected",
        decision_method="test",
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        reconciler_version=RECONCILER_VERSION,
    )
    run_diagnostics = ReconciliationRunDiagnostics(
        metadata_path="outputs/metadata.jsonl",
        metadata_diagnostics_path="outputs/metadata.json",
        output_path="outputs/reconciled.jsonl",
        diagnostics_path="outputs/reconciliation.json",
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        reconciler_version=RECONCILER_VERSION,
    )
    record_diagnostic = ReconciliationRecordDiagnostic(status="pending")

    _count_decision(run_diagnostics, record_diagnostic, rejected_decision)

    assert run_diagnostics.rejected_decisions == 1
    assert record_diagnostic.rejected_count == 1
    assert _backfill_status(rejected_decision) == "rejected"
    assert _extract_optional_id("{not-json", "report_id") is None
    assert _validation_errors(RuntimeError("plain error")) == ["plain error"]
    assert _comparable(date(2026, 5, 1)) == "2026-05-01"

    with pytest.raises(ValueError, match="not compared"):
        _candidate_by_id([], "missing-candidate")

    missing_diagnostics = tmp_path / "missing-diagnostics.json"
    with pytest.raises(ValueError, match="Metadata diagnostics"):
        _read_required_metadata_diagnostics(missing_diagnostics)


def test_decision_for_field_reports_no_schema_compatible_candidate() -> None:
    record = _metadata_record("source-doc-no-candidate", "report-no-candidate")

    decision = _decision_for_field(
        metadata_record=record,
        field_name="facility_name",
        candidates=[],
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        reconciler_version=RECONCILER_VERSION,
    )

    assert decision.decision_status == "unresolved"
    assert decision.decision_method == "no_schema_compatible_candidate"


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


def test_cli_backfill_rejects_non_dry_run() -> None:
    with pytest.raises(Exception, match="dry-run"):
        cli.backfill(dry_run=False)


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

    candidate_schema = json.loads(
        (repo_root / "schemas/extraction_candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )
    method_pattern = candidate_schema["properties"]["extraction_method"]["pattern"]
    assert "reconciler_llm" in method_pattern


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


def _extraction_candidate_payload(
    *,
    extraction_method: str,
    field_name: str = "facility_name",
    normalized_value: str = "בית חם",
) -> dict[str, object]:
    return {
        "candidate_id": f"candidate-{extraction_method}-{field_name}",
        "source_document_id": "source-doc-candidate",
        "report_id": "report-candidate",
        "field_name": field_name,
        "raw_value": str(normalized_value),
        "normalized_value": normalized_value,
        "page_number": 1,
        "raw_excerpt": str(normalized_value),
        "extraction_method": extraction_method,
        "extractor_version": "test-v1",
        "source_pdf_sha256": _sha("pdf-candidate"),
        "text_input_sha256": _sha("text-candidate"),
        "rendered_artifact_ids": ["rendered-page-1"],
        "rendered_artifact_sha256s": [_sha("rendered-page-1")],
        "prompt_id": "prompt",
        "prompt_version": "1",
        "prompt_input_sha256": _sha("prompt-candidate"),
        "confidence": 0.8,
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
