"""Schema-bound LLM extraction plumbing with offline deterministic modes."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import structlog
from pydantic import ValidationError

from welfare_inspections.collect.local_outputs import validate_local_output_path
from welfare_inspections.collect.manifest import (
    read_rendered_page_manifest,
    read_source_manifest,
    read_text_extraction_diagnostics,
    write_llm_candidate_manifest,
    write_llm_evaluation_report,
    write_llm_extraction_diagnostics,
)
from welfare_inspections.collect.models import (
    EvaluationExpectedField,
    EvaluationFieldResult,
    FieldEvidence,
    LLMEvaluationReport,
    LLMExtractionCandidate,
    LLMExtractionRecordDiagnostic,
    LLMExtractionRunDiagnostics,
    RenderedPageArtifact,
    SourceDocumentRecord,
    TextExtractionRecordDiagnostic,
    utc_now,
)

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = "llm-candidate-v1"
DEFAULT_PROMPT_ID = "report-metadata-extraction"
DEFAULT_PROMPT_VERSION = "1"


class MissingProviderConfiguration(RuntimeError):
    """Raised when production LLM extraction lacks provider configuration."""


class LLMProvider(Protocol):
    """Provider interface for schema-bound LLM candidate extraction."""

    model_name: str | None
    model_version: str | None

    def extract_candidates(
        self,
        *,
        record: SourceDocumentRecord,
        text: str | None,
        rendered_artifacts: list[RenderedPageArtifact],
        prompt_input_sha256: str,
    ) -> list[dict[str, object]]:
        """Return provider-shaped candidate dictionaries."""


class ConfiguredLLMProvider:
    """Production provider placeholder that fails closed before live calls."""

    def __init__(self) -> None:
        self.provider_name = os.getenv("WELFARE_INSPECTIONS_LLM_PROVIDER")
        self.model_name = os.getenv("WELFARE_INSPECTIONS_LLM_MODEL")
        self.model_version = os.getenv("WELFARE_INSPECTIONS_LLM_MODEL_VERSION")
        if not self.provider_name or not self.model_name:
            msg = (
                "Production LLM extraction requires "
                "WELFARE_INSPECTIONS_LLM_PROVIDER and "
                "WELFARE_INSPECTIONS_LLM_MODEL."
            )
            raise MissingProviderConfiguration(msg)

    def extract_candidates(
        self,
        *,
        record: SourceDocumentRecord,
        text: str | None,
        rendered_artifacts: list[RenderedPageArtifact],
        prompt_input_sha256: str,
    ) -> list[dict[str, object]]:
        msg = (
            "Live LLM provider calls are not implemented in PR 7; use dry-run "
            "or mock mode for local contract testing."
        )
        raise NotImplementedError(msg)


class MockLLMProvider:
    """Offline provider backed by a local JSON/JSONL fixture file."""

    def __init__(
        self,
        *,
        responses: dict[str, list[dict[str, object]]],
        model_name: str = "mock-llm",
        model_version: str = "offline-v1",
    ) -> None:
        self.responses = responses
        self.model_name = model_name
        self.model_version = model_version

    def extract_candidates(
        self,
        *,
        record: SourceDocumentRecord,
        text: str | None,
        rendered_artifacts: list[RenderedPageArtifact],
        prompt_input_sha256: str,
    ) -> list[dict[str, object]]:
        return self.responses.get(record.source_document_id, [])


def extract_llm_candidates(
    *,
    source_manifest_path: Path,
    output_path: Path,
    diagnostics_path: Path,
    text_diagnostics_path: Path | None = None,
    render_manifest_path: Path | None = None,
    eval_fixtures_path: Path | None = None,
    eval_report_path: Path | None = None,
    mode: str = "dry-run",
    mock_response_path: Path | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    provider: LLMProvider | None = None,
) -> tuple[list[LLMExtractionCandidate], LLMExtractionRunDiagnostics]:
    """Validate schema-bound LLM candidate extraction without CI network calls."""
    if mode not in {"dry-run", "mock", "production"}:
        msg = "mode must be one of: dry-run, mock, production"
        raise ValueError(msg)
    validate_local_output_path(output_path, label="LLM candidate output")
    validate_local_output_path(diagnostics_path, label="LLM diagnostics")
    if eval_report_path:
        validate_local_output_path(eval_report_path, label="LLM eval_report")

    records = read_source_manifest(source_manifest_path)
    text_by_source = _text_diagnostics_by_source(text_diagnostics_path)
    rendered_by_source = _rendered_artifacts_by_source(render_manifest_path)
    llm_provider = _provider_for_mode(
        mode=mode,
        mock_response_path=mock_response_path,
        provider=provider,
    )
    diagnostics = LLMExtractionRunDiagnostics(
        mode=mode,
        source_manifest_path=str(source_manifest_path),
        text_diagnostics_path=(
            str(text_diagnostics_path) if text_diagnostics_path else None
        ),
        render_manifest_path=str(render_manifest_path)
        if render_manifest_path
        else None,
        output_path=str(output_path),
        diagnostics_path=str(diagnostics_path),
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        model_name=llm_provider.model_name if llm_provider else None,
        model_version=llm_provider.model_version if llm_provider else None,
        total_records=len(records),
    )
    candidates: list[LLMExtractionCandidate] = []

    for record in records:
        record_candidates, record_diagnostic = _extract_record_candidates(
            record=record,
            text_diagnostic=text_by_source.get(record.source_document_id),
            rendered_artifacts=rendered_by_source.get(record.source_document_id, []),
            provider=llm_provider,
            mode=mode,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
        )
        candidates.extend(record_candidates)
        diagnostics.record_diagnostics.append(record_diagnostic)
        diagnostics.candidate_records += len(record_candidates)
        if record_diagnostic.status == "failed":
            diagnostics.failed_records += 1
        if record_diagnostic.warnings or record_diagnostic.errors:
            diagnostics.warning_records += 1

    diagnostics.finished_at = utc_now()
    write_llm_candidate_manifest(output_path, candidates)
    write_llm_extraction_diagnostics(diagnostics_path, diagnostics)
    if eval_report_path:
        report = evaluate_llm_candidates(
            candidates=candidates,
            candidate_manifest_path=output_path,
            fixture_path=eval_fixtures_path,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_name=diagnostics.model_name,
            model_version=diagnostics.model_version,
            rendered_artifacts=[
                artifact
                for artifacts in rendered_by_source.values()
                for artifact in artifacts
            ],
        )
        write_llm_evaluation_report(eval_report_path, report)
    logger.info(
        "llm_extraction_complete",
        mode=mode,
        records=diagnostics.total_records,
        candidates=diagnostics.candidate_records,
        failed=diagnostics.failed_records,
    )
    return candidates, diagnostics


def evaluate_llm_candidates(
    *,
    candidates: list[LLMExtractionCandidate],
    candidate_manifest_path: Path,
    fixture_path: Path | None,
    prompt_id: str,
    prompt_version: str,
    model_name: str | None,
    model_version: str | None,
    rendered_artifacts: list[RenderedPageArtifact] | None = None,
) -> LLMEvaluationReport:
    """Compare candidate manifests to reviewed expected values offline."""
    expected_fields = _read_evaluation_fixtures(fixture_path)
    candidates_by_key: dict[tuple[str, str], list[LLMExtractionCandidate]] = {}
    for candidate in candidates:
        if candidate.validation_status == "valid":
            candidates_by_key.setdefault(
                (candidate.source_document_id, candidate.field_name),
                [],
            ).append(candidate)
    field_results: list[EvaluationFieldResult] = []
    for expected in expected_fields:
        field_candidates = candidates_by_key.get(
            (expected.source_document_id, expected.field_name),
            [],
        )
        matching_candidates = [
            candidate
            for candidate in field_candidates
            if _comparable(candidate.normalized_value)
            == _comparable(expected.expected_normalized_value)
        ]
        observed_values = {
            json.dumps(
                _comparable(candidate.normalized_value),
                ensure_ascii=False,
                sort_keys=True,
            )
            for candidate in field_candidates
        }
        candidate = field_candidates[0] if field_candidates else None
        observed = candidate.normalized_value if candidate else None
        if not field_candidates:
            status = "missing" if expected.required else "not_observed"
        elif len(observed_values) > 1:
            status = "ambiguous"
        elif matching_candidates:
            status = "correct"
        else:
            status = "incorrect"
        field_results.append(
            EvaluationFieldResult(
                source_document_id=expected.source_document_id,
                field_name=expected.field_name,
                expected_normalized_value=expected.expected_normalized_value,
                observed_normalized_value=observed,
                status=status,
                candidate_id=candidate.candidate_id if candidate else None,
                candidate_ids=[
                    field_candidate.candidate_id
                    for field_candidate in field_candidates
                ],
                observed_candidate_count=len(field_candidates),
            )
        )

    rendered = rendered_artifacts or []
    first_rendered = rendered[0] if rendered else None
    report = LLMEvaluationReport(
        candidate_manifest_path=str(candidate_manifest_path),
        fixture_path=str(fixture_path) if fixture_path else None,
        schema_version=SCHEMA_VERSION,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        model_name=model_name,
        model_version=model_version,
        renderer_name=first_rendered.renderer_name if first_rendered else None,
        renderer_version=first_rendered.renderer_version if first_rendered else None,
        render_profile_id=first_rendered.render_profile_id if first_rendered else None,
        render_profile_version=(
            first_rendered.render_profile_version if first_rendered else None
        ),
        expected_field_count=len(expected_fields),
        observed_field_count=sum(len(values) for values in candidates_by_key.values()),
        covered_field_count=sum(
            1 for result in field_results if result.status in {"correct", "incorrect"}
        ),
        correct_field_count=sum(
            1 for result in field_results if result.status == "correct"
        ),
        missing_field_count=sum(
            1 for result in field_results if result.status == "missing"
        ),
        incorrect_field_count=sum(
            1
            for result in field_results
            if result.status in {"incorrect", "ambiguous"}
        ),
        regression_count=0,
        field_results=field_results,
        finished_at=utc_now(),
    )
    if fixture_path is None:
        report.notes.append(
            "No evaluation fixtures supplied; report has no field checks."
        )
    return report


def _extract_record_candidates(
    *,
    record: SourceDocumentRecord,
    text_diagnostic: TextExtractionRecordDiagnostic | None,
    rendered_artifacts: list[RenderedPageArtifact],
    provider: LLMProvider | None,
    mode: str,
    prompt_id: str,
    prompt_version: str,
) -> tuple[list[LLMExtractionCandidate], LLMExtractionRecordDiagnostic]:
    diagnostic = LLMExtractionRecordDiagnostic(
        source_document_id=record.source_document_id,
        status="pending",
    )
    if not record.pdf_sha256:
        diagnostic.status = "failed"
        diagnostic.errors.append("manifest_record_has_no_pdf_sha256")
        return [], diagnostic

    text = _read_text(text_diagnostic)
    text_sha256 = sha256(text.encode("utf-8")).hexdigest() if text else None
    prompt_input_sha256 = _prompt_input_sha256(
        record=record,
        text_sha256=text_sha256,
        rendered_artifacts=rendered_artifacts,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
    )
    if provider is None:
        diagnostic.status = "dry_run"
        diagnostic.warnings.append("dry_run_no_provider_no_candidates")
        return [], diagnostic

    try:
        raw_candidates = provider.extract_candidates(
            record=record,
            text=text,
            rendered_artifacts=rendered_artifacts,
            prompt_input_sha256=prompt_input_sha256,
        )
    except Exception as exc:
        if mode == "production":
            raise
        diagnostic.status = "failed"
        diagnostic.errors.append(str(exc))
        return [], diagnostic

    candidates: list[LLMExtractionCandidate] = []
    for index, raw_candidate in enumerate(raw_candidates):
        try:
            candidate = _candidate_from_provider_payload(
                raw_candidate,
                record=record,
                rendered_artifacts=rendered_artifacts,
                text_sha256=text_sha256,
                prompt_input_sha256=prompt_input_sha256,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                provider=provider,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            diagnostic.warnings.append(f"candidate_{index}_validation_failed:{exc}")
            continue
        candidates.append(candidate)

    diagnostic.status = "extracted" if candidates else "no_candidates"
    diagnostic.extraction_methods = sorted(
        {candidate.extraction_method for candidate in candidates}
    )
    diagnostic.candidate_ids = [candidate.candidate_id for candidate in candidates]
    return candidates, diagnostic


def _candidate_from_provider_payload(
    payload: dict[str, object],
    *,
    record: SourceDocumentRecord,
    rendered_artifacts: list[RenderedPageArtifact],
    text_sha256: str | None,
    prompt_input_sha256: str,
    prompt_id: str,
    prompt_version: str,
    provider: LLMProvider,
) -> LLMExtractionCandidate:
    extraction_method = str(payload.get("extraction_method") or "llm_text")
    rendered_ids: list[str] = []
    rendered_hashes: list[str] = []
    if extraction_method == "llm_multimodal":
        rendered_ids = [
            artifact.rendered_artifact_id for artifact in rendered_artifacts
        ]
        rendered_hashes = [artifact.image_sha256 for artifact in rendered_artifacts]
    field_name = str(payload.get("field_name") or "")
    raw_value = payload.get("raw_value")
    normalized_value = payload.get("normalized_value")
    evidence_payload = payload.get("field_evidence")
    if isinstance(evidence_payload, dict):
        evidence = FieldEvidence.model_validate(evidence_payload)
    else:
        page_number = payload.get("page_number") if "page_number" in payload else None
        evidence = FieldEvidence(
            page_number=page_number,
            raw_excerpt=payload.get("raw_excerpt")
            if isinstance(payload.get("raw_excerpt"), str)
            else None,
        )
    if extraction_method == "llm_multimodal":
        _validate_multimodal_evidence(
            evidence=evidence,
            rendered_artifacts=rendered_artifacts,
        )
    candidate_id = _candidate_id(
        record=record,
        field_name=field_name,
        extraction_method=extraction_method,
        normalized_value=normalized_value,
        prompt_input_sha256=prompt_input_sha256,
    )
    return LLMExtractionCandidate(
        candidate_id=candidate_id,
        source_document_id=record.source_document_id,
        report_id=payload.get("report_id")
        if isinstance(payload.get("report_id"), str)
        else None,
        field_name=field_name,
        raw_value=raw_value if isinstance(raw_value, str) else None,
        normalized_value=normalized_value,
        extraction_method=extraction_method,
        extractor_version=SCHEMA_VERSION,
        source_pdf_sha256=record.pdf_sha256 or "",
        text_input_sha256=text_sha256,
        rendered_artifact_ids=rendered_ids,
        rendered_artifact_sha256s=rendered_hashes,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        prompt_input_sha256=prompt_input_sha256,
        model_name=provider.model_name,
        model_version=provider.model_version,
        field_evidence=evidence,
        confidence=float(payload.get("confidence", 0.0)),
        warnings=[
            str(warning)
            for warning in payload.get("warnings", [])
            if isinstance(warning, str)
        ]
        if isinstance(payload.get("warnings", []), list)
        else [],
        validation_status=str(payload.get("validation_status") or "valid"),
    )


def _validate_multimodal_evidence(
    *,
    evidence: FieldEvidence,
    rendered_artifacts: list[RenderedPageArtifact],
) -> None:
    if evidence.visual_locator is None:
        return
    artifacts_by_id = {
        artifact.rendered_artifact_id: artifact for artifact in rendered_artifacts
    }
    artifact = artifacts_by_id.get(evidence.visual_locator.rendered_artifact_id)
    if artifact is None:
        msg = "visual_locator references a rendered artifact that was not an input"
        raise ValueError(msg)
    if evidence.visual_locator.coordinate_system != artifact.coordinate_system:
        msg = "visual_locator coordinate_system does not match rendered artifact"
        raise ValueError(msg)


def _provider_for_mode(
    *,
    mode: str,
    mock_response_path: Path | None,
    provider: LLMProvider | None,
) -> LLMProvider | None:
    if provider:
        return provider
    if mode == "production":
        return ConfiguredLLMProvider()
    if mode == "mock":
        if mock_response_path is None:
            msg = "mock mode requires --mock-response-path."
            raise ValueError(msg)
        return MockLLMProvider(responses=_read_mock_responses(mock_response_path))
    return None


def _read_mock_responses(path: Path) -> dict[str, list[dict[str, object]]]:
    responses: dict[str, list[dict[str, object]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        source_document_id = payload["source_document_id"]
        candidates = payload.get("candidates", [])
        if not isinstance(source_document_id, str) or not isinstance(candidates, list):
            msg = f"Invalid mock response record in {path}"
            raise ValueError(msg)
        responses[source_document_id] = [
            candidate for candidate in candidates if isinstance(candidate, dict)
        ]
    return responses


def _read_evaluation_fixtures(path: Path | None) -> list[EvaluationExpectedField]:
    if path is None:
        return []
    expected: list[EvaluationExpectedField] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            expected.append(EvaluationExpectedField.model_validate_json(line))
        except ValueError as exc:
            msg = f"Invalid LLM evaluation fixture JSONL at {path}:{line_number}"
            raise ValueError(msg) from exc
    return expected


def _text_diagnostics_by_source(
    path: Path | None,
) -> dict[str, TextExtractionRecordDiagnostic]:
    if path is None:
        return {}
    diagnostics = read_text_extraction_diagnostics(path)
    return {
        diagnostic.source_document_id: diagnostic
        for diagnostic in diagnostics.record_diagnostics
    }


def _rendered_artifacts_by_source(
    path: Path | None,
) -> dict[str, list[RenderedPageArtifact]]:
    if path is None:
        return {}
    artifacts_by_source: dict[str, list[RenderedPageArtifact]] = {}
    for artifact in read_rendered_page_manifest(path):
        artifacts_by_source.setdefault(artifact.source_document_id, []).append(artifact)
    return artifacts_by_source


def _read_text(diagnostic: TextExtractionRecordDiagnostic | None) -> str | None:
    if diagnostic is None or not diagnostic.text_path:
        return None
    path = Path(diagnostic.text_path)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _prompt_input_sha256(
    *,
    record: SourceDocumentRecord,
    text_sha256: str | None,
    rendered_artifacts: list[RenderedPageArtifact],
    prompt_id: str,
    prompt_version: str,
) -> str:
    payload = {
        "source_document_id": record.source_document_id,
        "source_pdf_sha256": record.pdf_sha256,
        "text_input_sha256": text_sha256,
        "rendered_artifacts": [
            {
                "rendered_artifact_id": artifact.rendered_artifact_id,
                "image_sha256": artifact.image_sha256,
            }
            for artifact in rendered_artifacts
        ],
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _candidate_id(
    *,
    record: SourceDocumentRecord,
    field_name: str,
    extraction_method: str,
    normalized_value: object,
    prompt_input_sha256: str,
) -> str:
    payload = {
        "source_document_id": record.source_document_id,
        "field_name": field_name,
        "extraction_method": extraction_method,
        "normalized_value": _comparable(normalized_value),
        "prompt_input_sha256": prompt_input_sha256,
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"llm-candidate-{digest}"


def _comparable(value: object) -> object:
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return value
