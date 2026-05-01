"""Conservative candidate reconciliation and backfill diagnostics."""

from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from welfare_inspections.collect.local_outputs import validate_local_output_path
from welfare_inspections.collect.manifest import (
    read_reconciled_metadata_manifest,
    write_backfill_diagnostics,
    write_reconciled_metadata_manifest,
    write_reconciliation_diagnostics,
)
from welfare_inspections.collect.models import (
    BackfillFieldChange,
    BackfillRunDiagnostics,
    ExtractionCandidate,
    LLMExtractionCandidate,
    MetadataField,
    MetadataParseRunDiagnostics,
    ReconciledReportMetadata,
    ReconciliationDecision,
    ReconciliationRecordDiagnostic,
    ReconciliationRunDiagnostics,
    ReportMetadataRecord,
    utc_now,
)

logger = structlog.get_logger(__name__)

RECONCILIATION_SCHEMA_VERSION = "reconciliation-v1"
RECONCILER_VERSION = "reconciler-v1"
DETERMINISTIC_CANDIDATE_VERSION = "metadata-parser-candidate-v1"


def reconcile_report_metadata(
    *,
    metadata_path: Path,
    metadata_diagnostics_path: Path,
    output_path: Path,
    diagnostics_path: Path,
    llm_candidates_path: Path | None = None,
    schema_version: str = RECONCILIATION_SCHEMA_VERSION,
    reconciler_version: str = RECONCILER_VERSION,
) -> tuple[list[ReconciledReportMetadata], ReconciliationRunDiagnostics]:
    """Reconcile PR 5 deterministic metadata and PR 7 LLM candidates offline."""
    validate_local_output_path(output_path, label="Reconciliation output")
    validate_local_output_path(diagnostics_path, label="Reconciliation diagnostics")
    _read_required_metadata_diagnostics(metadata_diagnostics_path)

    diagnostics = ReconciliationRunDiagnostics(
        metadata_path=str(metadata_path),
        metadata_diagnostics_path=str(metadata_diagnostics_path),
        llm_candidates_path=str(llm_candidates_path) if llm_candidates_path else None,
        output_path=str(output_path),
        diagnostics_path=str(diagnostics_path),
        schema_version=schema_version,
        reconciler_version=reconciler_version,
    )
    llm_candidates = _read_llm_candidates(llm_candidates_path, diagnostics)
    llm_by_key = _llm_candidates_by_key(llm_candidates)
    seen_candidate_ids: set[str] = set()
    seen_decision_ids: set[str] = set()
    seen_report_ids: set[str] = set()
    output_records: list[ReconciledReportMetadata] = []

    for line_number, line in _iter_jsonl_lines(metadata_path):
        diagnostics.total_records += 1
        record_diagnostic = ReconciliationRecordDiagnostic(
            line_number=line_number,
            report_id=_extract_optional_id(line, "report_id"),
            source_document_id=_extract_optional_id(line, "source_document_id"),
            status="pending",
        )
        try:
            metadata_record = ReportMetadataRecord.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            record_diagnostic.status = "validation_failed"
            record_diagnostic.errors.extend(_validation_errors(exc))
            diagnostics.validation_failed_records += 1
            diagnostics.record_diagnostics.append(record_diagnostic)
            continue
        if metadata_record.report_id in seen_report_ids:
            record_diagnostic.status = "duplicate_report_id"
            record_diagnostic.errors.append(
                f"Duplicate report_id {metadata_record.report_id!r}."
            )
            diagnostics.duplicate_decision_id_records += len(metadata_record.fields)
            diagnostics.record_diagnostics.append(record_diagnostic)
            continue
        seen_report_ids.add(metadata_record.report_id)

        record = _reconcile_one_report(
            metadata_record=metadata_record,
            llm_candidates=llm_by_key,
            seen_candidate_ids=seen_candidate_ids,
            seen_decision_ids=seen_decision_ids,
            diagnostics=diagnostics,
            record_diagnostic=record_diagnostic,
            schema_version=schema_version,
            reconciler_version=reconciler_version,
        )
        output_records.append(record)
        diagnostics.reconciled_records += 1
        diagnostics.record_diagnostics.append(record_diagnostic)

    diagnostics.finished_at = utc_now()
    write_reconciled_metadata_manifest(output_path, output_records)
    write_reconciliation_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "reconciliation_complete",
        records=diagnostics.total_records,
        reconciled=diagnostics.reconciled_records,
        accepted=diagnostics.accepted_decisions,
        needs_review=diagnostics.needs_review_decisions,
    )
    return output_records, diagnostics


def run_backfill_dry_run(
    *,
    reconciled_metadata_path: Path,
    output_path: Path,
    evaluation_report_path: Path | None = None,
    schema_version: str = RECONCILIATION_SCHEMA_VERSION,
    reconciler_version: str = RECONCILER_VERSION,
) -> BackfillRunDiagnostics:
    """Summarize reconciled metadata as a dry-run backfill diagnostics artifact."""
    validate_local_output_path(output_path, label="Backfill diagnostics")
    records = read_reconciled_metadata_manifest(reconciled_metadata_path)
    diagnostics = BackfillRunDiagnostics(
        reconciled_metadata_path=str(reconciled_metadata_path),
        output_path=str(output_path),
        evaluation_report_path=(
            str(evaluation_report_path) if evaluation_report_path else None
        ),
        schema_version=schema_version,
        reconciler_version=reconciler_version,
        input_hashes={
            "reconciled_metadata_sha256": _file_sha256(reconciled_metadata_path),
        },
    )
    if evaluation_report_path and evaluation_report_path.exists():
        diagnostics.input_hashes["evaluation_report_sha256"] = _file_sha256(
            evaluation_report_path
        )
        _merge_evaluation_versions(diagnostics, evaluation_report_path)

    for record in records:
        for decision in record.decisions:
            after_value = record.reconciled_fields.get(decision.field_name)
            status = _backfill_status(decision)
            diagnostics.field_changes.append(
                BackfillFieldChange(
                    report_id=record.report_id,
                    source_document_id=record.source_document_id,
                    field_name=decision.field_name,
                    before_value=None,
                    after_value=after_value,
                    status=status,
                    accepted_candidate_id=decision.accepted_candidate_id,
                    candidate_ids=decision.candidate_ids,
                    decision_id=decision.decision_id,
                )
            )
            if status == "changed":
                diagnostics.changed_count += 1
            elif status == "unchanged":
                diagnostics.unchanged_count += 1
            elif status == "rejected":
                diagnostics.rejected_count += 1
            else:
                diagnostics.unresolved_count += 1
    diagnostics.notes.append(
        "Dry-run backfill diagnostics only; no canonical artifacts were overwritten."
    )
    diagnostics.finished_at = utc_now()
    write_backfill_diagnostics(output_path, diagnostics)
    return diagnostics


def _reconcile_one_report(
    *,
    metadata_record: ReportMetadataRecord,
    llm_candidates: dict[tuple[str, str], list[ExtractionCandidate]],
    seen_candidate_ids: set[str],
    seen_decision_ids: set[str],
    diagnostics: ReconciliationRunDiagnostics,
    record_diagnostic: ReconciliationRecordDiagnostic,
    schema_version: str,
    reconciler_version: str,
) -> ReconciledReportMetadata:
    deterministic_candidates = [
        deterministic_candidate_from_metadata_field(metadata_record, field)
        for field in metadata_record.fields.values()
    ]
    field_names = sorted(
        {
            candidate.field_name
            for candidate in deterministic_candidates
        }
        | {
            candidate.field_name
            for key, values in llm_candidates.items()
            for candidate in values
            if key[0] in {metadata_record.report_id, metadata_record.source_document_id}
        }
    )
    decisions: list[ReconciliationDecision] = []
    reconciled_fields: dict[str, str | date | int | float | None] = {}
    raw_fields: dict[str, str | None] = {}
    accepted_methods: dict[str, list[str]] = {}
    llm_candidate_ids: dict[str, list[str]] = {}

    deterministic_by_field = {
        candidate.field_name: candidate for candidate in deterministic_candidates
    }
    for field_name in field_names:
        candidates = []
        deterministic_candidate = deterministic_by_field.get(field_name)
        if deterministic_candidate:
            candidates.append(deterministic_candidate)
        candidates.extend(
            llm_candidates.get((metadata_record.report_id, field_name), [])
        )
        candidates.extend(
            llm_candidates.get((metadata_record.source_document_id, field_name), [])
        )
        unique_candidates = _deduplicate_candidates(
            candidates,
            diagnostics=diagnostics,
            record_diagnostic=record_diagnostic,
            seen_candidate_ids=seen_candidate_ids,
        )
        decision = _decision_for_field(
            metadata_record=metadata_record,
            field_name=field_name,
            candidates=unique_candidates,
            schema_version=schema_version,
            reconciler_version=reconciler_version,
        )
        if decision.decision_id in seen_decision_ids:
            diagnostics.duplicate_decision_id_records += 1
            record_diagnostic.errors.append(
                f"Duplicate decision_id {decision.decision_id!r}."
            )
            continue
        seen_decision_ids.add(decision.decision_id)
        decisions.append(decision)
        record_diagnostic.decision_ids.append(decision.decision_id)
        _count_decision(diagnostics, record_diagnostic, decision)
        field_llm_ids = [
            candidate.candidate_id
            for candidate in unique_candidates
            if candidate.extraction_method.startswith("llm_")
        ]
        if field_llm_ids:
            llm_candidate_ids[field_name] = field_llm_ids
        if decision.accepted_candidate_id:
            accepted = _candidate_by_id(
                unique_candidates,
                decision.accepted_candidate_id,
            )
            reconciled_fields[field_name] = accepted.normalized_value
            raw_fields[field_name] = accepted.raw_value
            accepted_methods[field_name] = sorted(
                {candidate.extraction_method for candidate in unique_candidates}
            )

    statuses = {decision.decision_status for decision in decisions}
    reconciliation_status = "needs_review" if "needs_review" in statuses else "accepted"
    if not decisions:
        reconciliation_status = "unresolved"
    record_diagnostic.status = reconciliation_status
    return ReconciledReportMetadata(
        report_id=metadata_record.report_id,
        source_document_id=metadata_record.source_document_id,
        base_metadata=metadata_record,
        reconciled_fields=reconciled_fields,
        raw_fields=raw_fields,
        accepted_extraction_methods=accepted_methods,
        llm_candidate_ids=llm_candidate_ids,
        reconciliation_status=reconciliation_status,
        decisions=decisions,
        warnings=record_diagnostic.warnings,
        schema_version=schema_version,
        reconciler_version=reconciler_version,
    )


def deterministic_candidate_from_metadata_field(
    metadata_record: ReportMetadataRecord,
    field: MetadataField,
) -> ExtractionCandidate:
    """Convert a PR 5 metadata field into the common candidate contract."""
    candidate_id = _candidate_id(
        source_document_id=metadata_record.source_document_id,
        report_id=metadata_record.report_id,
        field_name=field.field_name,
        extraction_method="deterministic",
        normalized_value=field.normalized_value,
    )
    source_pdf_sha256 = (
        metadata_record.pdf_sha256
        if metadata_record.pdf_sha256 and len(metadata_record.pdf_sha256) == 64
        else None
    )
    return ExtractionCandidate(
        candidate_id=candidate_id,
        source_document_id=metadata_record.source_document_id,
        report_id=metadata_record.report_id,
        field_name=field.field_name,
        raw_value=field.raw_value,
        normalized_value=field.normalized_value,
        page_number=field.page_number,
        raw_excerpt=field.raw_excerpt,
        extraction_method="deterministic",
        extractor_version=DETERMINISTIC_CANDIDATE_VERSION,
        source_pdf_sha256=source_pdf_sha256,
        confidence=field.confidence,
        warnings=list(field.warnings),
    )


def llm_candidate_to_extraction_candidate(
    candidate: LLMExtractionCandidate,
) -> ExtractionCandidate:
    evidence = candidate.field_evidence
    return ExtractionCandidate(
        candidate_id=candidate.candidate_id,
        source_document_id=candidate.source_document_id,
        report_id=candidate.report_id,
        field_name=candidate.field_name,
        raw_value=candidate.raw_value,
        normalized_value=candidate.normalized_value,
        page_number=evidence.page_number,
        raw_excerpt=evidence.raw_excerpt,
        visual_locator=evidence.visual_locator,
        extraction_method=candidate.extraction_method,
        extractor_version=candidate.extractor_version,
        model_name=candidate.model_name,
        model_version=candidate.model_version,
        prompt_id=candidate.prompt_id,
        prompt_version=candidate.prompt_version,
        prompt_input_sha256=candidate.prompt_input_sha256,
        source_pdf_sha256=candidate.source_pdf_sha256,
        text_input_sha256=candidate.text_input_sha256,
        rendered_artifact_ids=candidate.rendered_artifact_ids,
        rendered_artifact_sha256s=candidate.rendered_artifact_sha256s,
        input_artifact_refs=[
            *candidate.rendered_artifact_ids,
            *candidate.rendered_artifact_sha256s,
        ],
        confidence=candidate.confidence,
        warnings=candidate.warnings,
        created_at=candidate.created_at,
    )


def _decision_for_field(
    *,
    metadata_record: ReportMetadataRecord,
    field_name: str,
    candidates: list[ExtractionCandidate],
    schema_version: str,
    reconciler_version: str,
) -> ReconciliationDecision:
    decision_id = _decision_id(metadata_record.report_id, field_name)
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    deterministic = [
        candidate
        for candidate in candidates
        if candidate.extraction_method == "deterministic"
    ]
    valid_llm = [
        candidate
        for candidate in candidates
        if candidate.extraction_method.startswith("llm_")
    ]
    if deterministic and not valid_llm:
        return _accepted_decision(
            decision_id,
            metadata_record,
            field_name,
            deterministic[0].candidate_id,
            candidate_ids,
            "deterministic_only",
            "Accepted deterministic candidate; no LLM candidate was present.",
            schema_version,
            reconciler_version,
        )
    if deterministic and valid_llm:
        deterministic_value = _comparable(deterministic[0].normalized_value)
        llm_values = {_json_key(candidate.normalized_value) for candidate in valid_llm}
        if len(llm_values) == 1 and _json_key(deterministic_value) in llm_values:
            return _accepted_decision(
                decision_id,
                metadata_record,
                field_name,
                deterministic[0].candidate_id,
                candidate_ids,
                "deterministic_llm_agreement",
                "Accepted deterministic candidate because valid LLM candidates agree.",
                schema_version,
                reconciler_version,
            )
        return ReconciliationDecision(
            decision_id=decision_id,
            report_id=metadata_record.report_id,
            source_document_id=metadata_record.source_document_id,
            field_name=field_name,
            candidate_ids=candidate_ids,
            decision_status="needs_review",
            decision_method="material_conflict",
            reason=(
                "Deterministic and LLM candidates disagree; preserving all "
                "candidates for review."
            ),
            warnings=["material_conflict_needs_review"],
            schema_version=schema_version,
            reconciler_version=reconciler_version,
        )
    if valid_llm:
        return ReconciliationDecision(
            decision_id=decision_id,
            report_id=metadata_record.report_id,
            source_document_id=metadata_record.source_document_id,
            field_name=field_name,
            candidate_ids=candidate_ids,
            decision_status="needs_review",
            decision_method="llm_only_requires_review",
            reason="LLM-only candidate requires review before canonical acceptance.",
            warnings=["llm_only_candidate_not_auto_accepted"],
            schema_version=schema_version,
            reconciler_version=reconciler_version,
        )
    return ReconciliationDecision(
        decision_id=decision_id,
        report_id=metadata_record.report_id,
        source_document_id=metadata_record.source_document_id,
        field_name=field_name,
        candidate_ids=candidate_ids,
        decision_status="unresolved",
        decision_method="no_schema_compatible_candidate",
        reason="No schema-compatible candidate was available.",
        warnings=["no_schema_compatible_candidate"],
        schema_version=schema_version,
        reconciler_version=reconciler_version,
    )


def _accepted_decision(
    decision_id: str,
    metadata_record: ReportMetadataRecord,
    field_name: str,
    accepted_candidate_id: str,
    candidate_ids: list[str],
    decision_method: str,
    reason: str,
    schema_version: str,
    reconciler_version: str,
) -> ReconciliationDecision:
    return ReconciliationDecision(
        decision_id=decision_id,
        report_id=metadata_record.report_id,
        source_document_id=metadata_record.source_document_id,
        field_name=field_name,
        accepted_candidate_id=accepted_candidate_id,
        candidate_ids=candidate_ids,
        decision_status="accepted",
        decision_method=decision_method,
        reason=reason,
        schema_version=schema_version,
        reconciler_version=reconciler_version,
    )


def _read_required_metadata_diagnostics(path: Path) -> None:
    try:
        MetadataParseRunDiagnostics.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        msg = f"Metadata diagnostics could not be read or validated: {path}"
        raise ValueError(msg) from exc


def _read_llm_candidates(
    path: Path | None,
    diagnostics: ReconciliationRunDiagnostics,
) -> list[ExtractionCandidate]:
    if path is None or not path.exists():
        return []
    candidates: list[ExtractionCandidate] = []
    for line_number, line in _iter_jsonl_lines(path):
        try:
            llm_candidate = LLMExtractionCandidate.model_validate_json(line)
            candidates.append(llm_candidate_to_extraction_candidate(llm_candidate))
        except (ValidationError, ValueError) as exc:
            diagnostics.validation_failed_records += 1
            diagnostics.record_diagnostics.append(
                ReconciliationRecordDiagnostic(
                    line_number=line_number,
                    status="llm_candidate_validation_failed",
                    errors=_validation_errors(exc),
                )
            )
    return candidates


def _llm_candidates_by_key(
    candidates: list[ExtractionCandidate],
) -> dict[tuple[str, str], list[ExtractionCandidate]]:
    by_key: dict[tuple[str, str], list[ExtractionCandidate]] = {}
    for candidate in candidates:
        if candidate.report_id:
            by_key.setdefault((candidate.report_id, candidate.field_name), []).append(
                candidate
            )
        else:
            by_key.setdefault(
                (candidate.source_document_id, candidate.field_name),
                [],
            ).append(candidate)
    return by_key


def _deduplicate_candidates(
    candidates: list[ExtractionCandidate],
    *,
    diagnostics: ReconciliationRunDiagnostics,
    record_diagnostic: ReconciliationRecordDiagnostic,
    seen_candidate_ids: set[str],
) -> list[ExtractionCandidate]:
    unique: list[ExtractionCandidate] = []
    local_seen: set[str] = set()
    for candidate in candidates:
        if (
            candidate.candidate_id in local_seen
            or candidate.candidate_id in seen_candidate_ids
        ):
            diagnostics.duplicate_candidate_id_records += 1
            record_diagnostic.warnings.append(
                f"Duplicate candidate_id {candidate.candidate_id!r} ignored."
            )
            continue
        local_seen.add(candidate.candidate_id)
        seen_candidate_ids.add(candidate.candidate_id)
        unique.append(candidate)
    return unique


def _count_decision(
    diagnostics: ReconciliationRunDiagnostics,
    record_diagnostic: ReconciliationRecordDiagnostic,
    decision: ReconciliationDecision,
) -> None:
    if decision.decision_status == "accepted":
        diagnostics.accepted_decisions += 1
        record_diagnostic.accepted_count += 1
    elif decision.decision_status == "needs_review":
        diagnostics.needs_review_decisions += 1
        record_diagnostic.needs_review_count += 1
    elif decision.decision_status == "rejected":
        diagnostics.rejected_decisions += 1
        record_diagnostic.rejected_count += 1


def _candidate_by_id(
    candidates: list[ExtractionCandidate],
    candidate_id: str,
) -> ExtractionCandidate:
    for candidate in candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    msg = f"Accepted candidate_id {candidate_id!r} was not compared."
    raise ValueError(msg)


def _backfill_status(decision: ReconciliationDecision) -> str:
    if decision.decision_status == "accepted":
        return "changed"
    if decision.decision_status == "rejected":
        return "rejected"
    return "unresolved"


def _merge_evaluation_versions(
    diagnostics: BackfillRunDiagnostics,
    evaluation_report_path: Path,
) -> None:
    payload = json.loads(evaluation_report_path.read_text(encoding="utf-8"))
    diagnostics.model_versions["llm_model"] = payload.get("model_version")
    diagnostics.prompt_versions["prompt_version"] = payload.get("prompt_version")
    diagnostics.render_versions["renderer_version"] = payload.get("renderer_version")
    diagnostics.render_versions["render_profile_version"] = payload.get(
        "render_profile_version"
    )


def _iter_jsonl_lines(path: Path) -> list[tuple[int, str]]:
    return [
        (line_number, line)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            1,
        )
        if line.strip()
    ]


def _extract_optional_id(line: str, key: str) -> str | None:
    try:
        value = json.loads(line).get(key)
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
    return [str(exc)]


def _candidate_id(
    *,
    source_document_id: str,
    report_id: str,
    field_name: str,
    extraction_method: str,
    normalized_value: Any,
) -> str:
    payload = {
        "source_document_id": source_document_id,
        "report_id": report_id,
        "field_name": field_name,
        "extraction_method": extraction_method,
        "normalized_value": _comparable(normalized_value),
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"candidate-{digest}"


def _decision_id(report_id: str, field_name: str) -> str:
    digest = sha256(f"{report_id}|{field_name}".encode()).hexdigest()[:24]
    return f"reconciliation-decision-{digest}"


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json_key(value: Any) -> str:
    return json.dumps(_comparable(value), ensure_ascii=False, sort_keys=True)


def _comparable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
