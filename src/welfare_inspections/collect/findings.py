"""Offline finding-level extraction contracts and review sidecars."""

from __future__ import annotations

import json
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
    write_finding_candidate_manifest,
    write_finding_extraction_diagnostics,
)
from welfare_inspections.collect.models import (
    FieldEvidence,
    FindingExtractionCandidate,
    FindingExtractionRecordDiagnostic,
    FindingExtractionRunDiagnostics,
    RenderedPageArtifact,
    SourceDocumentRecord,
    TextExtractionRecordDiagnostic,
    utc_now,
)

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = "finding-candidate-v1"
DEFAULT_FINDING_PROMPT_ID = "finding-level-extraction"
DEFAULT_FINDING_PROMPT_VERSION = "1"


class UnsupportedFindingProductionMode(RuntimeError):
    """Raised when finding extraction is asked to run live provider work."""


class FindingProvider(Protocol):
    """Provider interface for finding-level candidate extraction."""

    model_name: str | None
    model_version: str | None

    def extract_findings(
        self,
        *,
        record: SourceDocumentRecord,
        text: str | None,
        rendered_artifacts: list[RenderedPageArtifact],
        prompt_input_sha256: str,
    ) -> list[dict[str, object]]:
        """Return provider-shaped finding candidate dictionaries."""


class MockFindingProvider:
    """Offline provider backed by local JSONL mock finding responses."""

    def __init__(
        self,
        *,
        responses: dict[str, list[dict[str, object]]],
        model_name: str = "mock-finding-provider",
        model_version: str = "offline-v1",
    ) -> None:
        self.responses = responses
        self.model_name = model_name
        self.model_version = model_version

    def extract_findings(
        self,
        *,
        record: SourceDocumentRecord,
        text: str | None,
        rendered_artifacts: list[RenderedPageArtifact],
        prompt_input_sha256: str,
    ) -> list[dict[str, object]]:
        return self.responses.get(record.source_document_id, [])


def extract_finding_candidates(
    *,
    source_manifest_path: Path,
    output_path: Path,
    diagnostics_path: Path,
    text_diagnostics_path: Path | None = None,
    render_manifest_path: Path | None = None,
    mode: str = "dry-run",
    mock_response_path: Path | None = None,
    prompt_id: str = DEFAULT_FINDING_PROMPT_ID,
    prompt_version: str = DEFAULT_FINDING_PROMPT_VERSION,
    provider: FindingProvider | None = None,
) -> tuple[list[FindingExtractionCandidate], FindingExtractionRunDiagnostics]:
    """Write review-only finding candidate sidecars from offline inputs."""
    if mode not in {"dry-run", "mock", "production"}:
        msg = "mode must be one of: dry-run, mock, production"
        raise ValueError(msg)
    if mode == "production" and provider is None:
        msg = (
            "Live finding extraction is not supported yet; use dry-run or mock "
            "mode with local fixtures."
        )
        raise UnsupportedFindingProductionMode(msg)
    validate_local_output_path(output_path, label="finding candidate output")
    validate_local_output_path(diagnostics_path, label="finding diagnostics")

    records = read_source_manifest(source_manifest_path)
    text_by_source = _text_diagnostics_by_source(text_diagnostics_path)
    rendered_by_source = _rendered_artifacts_by_source(render_manifest_path)
    finding_provider = _provider_for_mode(
        mode=mode,
        mock_response_path=mock_response_path,
        provider=provider,
    )
    diagnostics = FindingExtractionRunDiagnostics(
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
        model_name=finding_provider.model_name if finding_provider else None,
        model_version=finding_provider.model_version if finding_provider else None,
        total_records=len(records),
    )
    candidates: list[FindingExtractionCandidate] = []
    for record in records:
        record_candidates, record_diagnostic = _extract_record_findings(
            record=record,
            text_diagnostic=text_by_source.get(record.source_document_id),
            rendered_artifacts=rendered_by_source.get(record.source_document_id, []),
            provider=finding_provider,
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
    write_finding_candidate_manifest(output_path, candidates)
    write_finding_extraction_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "finding_extraction_complete",
        mode=mode,
        records=diagnostics.total_records,
        candidates=diagnostics.candidate_records,
        failed=diagnostics.failed_records,
    )
    return candidates, diagnostics


def _extract_record_findings(
    *,
    record: SourceDocumentRecord,
    text_diagnostic: TextExtractionRecordDiagnostic | None,
    rendered_artifacts: list[RenderedPageArtifact],
    provider: FindingProvider | None,
    prompt_id: str,
    prompt_version: str,
) -> tuple[list[FindingExtractionCandidate], FindingExtractionRecordDiagnostic]:
    diagnostic = FindingExtractionRecordDiagnostic(
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

    raw_findings = provider.extract_findings(
        record=record,
        text=text,
        rendered_artifacts=rendered_artifacts,
        prompt_input_sha256=prompt_input_sha256,
    )
    candidates: list[FindingExtractionCandidate] = []
    for index, raw_finding in enumerate(raw_findings):
        try:
            candidate = _candidate_from_provider_payload(
                raw_finding,
                record=record,
                rendered_artifacts=rendered_artifacts,
                text_sha256=text_sha256,
                prompt_input_sha256=prompt_input_sha256,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                provider=provider,
                fallback_index=index + 1,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            diagnostic.warnings.append(f"candidate_{index}_validation_failed:{exc}")
            continue
        candidates.append(candidate)

    diagnostic.status = "extracted" if candidates else "no_candidates"
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
    provider: FindingProvider,
    fallback_index: int,
) -> FindingExtractionCandidate:
    extraction_method = str(payload.get("extraction_method") or "llm_text")
    evidence = _evidence_from_payload(payload)
    if extraction_method == "llm_multimodal":
        _validate_multimodal_evidence(evidence, rendered_artifacts)
    rendered_ids: list[str] = []
    rendered_hashes: list[str] = []
    if extraction_method == "llm_multimodal":
        rendered_ids = [
            artifact.rendered_artifact_id for artifact in rendered_artifacts
        ]
        rendered_hashes = [artifact.image_sha256 for artifact in rendered_artifacts]
    raw_finding_text = payload.get("finding_text_raw") or payload.get("finding_text")
    finding_text = str(raw_finding_text) if raw_finding_text else ""
    finding_index = payload.get("finding_index", fallback_index)
    report_id = payload.get("report_id")
    finding_type = payload.get("finding_type")
    severity = payload.get("severity")
    finding_text_normalized = payload.get("finding_text_normalized")
    recommendation_raw = payload.get("recommendation_raw")
    recommendation_normalized = payload.get("recommendation_normalized")
    legal_refs_raw = payload.get("legal_refs", [])
    warnings_raw = payload.get("warnings", [])
    return FindingExtractionCandidate(
        candidate_id=_candidate_id(
            record=record,
            finding_text=finding_text,
            finding_index=finding_index if isinstance(finding_index, int) else None,
            prompt_input_sha256=prompt_input_sha256,
        ),
        source_document_id=record.source_document_id,
        report_id=report_id if isinstance(report_id, str) else None,
        finding_index=finding_index if isinstance(finding_index, int) else None,
        finding_type=finding_type if isinstance(finding_type, str) else None,
        severity=severity if isinstance(severity, str) else None,
        finding_text_raw=finding_text,
        finding_text_normalized=finding_text_normalized
        if isinstance(finding_text_normalized, str)
        else None,
        recommendation_raw=recommendation_raw
        if isinstance(recommendation_raw, str)
        else None,
        recommendation_normalized=recommendation_normalized
        if isinstance(recommendation_normalized, str)
        else None,
        legal_refs=[str(ref) for ref in legal_refs_raw if isinstance(ref, str)]
        if isinstance(legal_refs_raw, list)
        else [],
        extraction_method=extraction_method,
        extractor_version=SCHEMA_VERSION,
        source_pdf_sha256=record.pdf_sha256,
        text_input_sha256=text_sha256,
        rendered_artifact_ids=rendered_ids,
        rendered_artifact_sha256s=rendered_hashes,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        prompt_input_sha256=prompt_input_sha256,
        model_name=provider.model_name,
        model_version=provider.model_version,
        evidence=evidence,
        confidence=float(payload.get("confidence", 0.0)),
        warnings=[str(w) for w in warnings_raw if isinstance(w, str)]
        if isinstance(warnings_raw, list)
        else [],
        validation_status=str(payload.get("validation_status") or "valid"),
    )


def _evidence_from_payload(payload: dict[str, object]) -> list[FieldEvidence]:
    evidence_payload = payload.get("evidence")
    if isinstance(evidence_payload, list):
        return [
            FieldEvidence.model_validate(evidence)
            for evidence in evidence_payload
            if isinstance(evidence, dict)
        ]
    field_evidence = payload.get("field_evidence")
    if isinstance(field_evidence, dict):
        return [FieldEvidence.model_validate(field_evidence)]
    return [
        FieldEvidence(
            page_number=payload.get("page_number")
            if isinstance(payload.get("page_number"), int)
            else None,
            raw_excerpt=payload.get("raw_excerpt")
            if isinstance(payload.get("raw_excerpt"), str)
            else None,
        )
    ]


def _validate_multimodal_evidence(
    evidence: list[FieldEvidence],
    rendered_artifacts: list[RenderedPageArtifact],
) -> None:
    artifacts_by_id = {
        artifact.rendered_artifact_id: artifact for artifact in rendered_artifacts
    }
    for item in evidence:
        locator = item.visual_locator
        if locator is None:
            continue
        artifact = artifacts_by_id.get(locator.rendered_artifact_id)
        if artifact is None:
            msg = "visual_locator references a rendered artifact that was not an input"
            raise ValueError(msg)
        if locator.coordinate_system != artifact.coordinate_system:
            msg = "visual_locator coordinate_system does not match rendered artifact"
            raise ValueError(msg)


def _provider_for_mode(
    *,
    mode: str,
    mock_response_path: Path | None,
    provider: FindingProvider | None,
) -> FindingProvider | None:
    if provider:
        return provider
    if mode == "mock":
        if mock_response_path is None:
            msg = "mock mode requires --mock-response-path."
            raise ValueError(msg)
        return MockFindingProvider(responses=_read_mock_responses(mock_response_path))
    return None


def _read_mock_responses(path: Path) -> dict[str, list[dict[str, object]]]:
    responses: dict[str, list[dict[str, object]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        source_document_id = payload["source_document_id"]
        findings = payload.get("findings", payload.get("candidates", []))
        if not isinstance(source_document_id, str) or not isinstance(findings, list):
            msg = f"Invalid mock finding response record in {path}"
            raise ValueError(msg)
        responses[source_document_id] = [
            finding for finding in findings if isinstance(finding, dict)
        ]
    return responses


def _text_diagnostics_by_source(
    path: Path | None,
) -> dict[str, TextExtractionRecordDiagnostic]:
    if path is None or not path.exists():
        return {}
    diagnostics = read_text_extraction_diagnostics(path)
    return {
        diagnostic.source_document_id: diagnostic
        for diagnostic in diagnostics.record_diagnostics
    }


def _rendered_artifacts_by_source(
    path: Path | None,
) -> dict[str, list[RenderedPageArtifact]]:
    if path is None or not path.exists():
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
            for artifact in sorted(
                rendered_artifacts,
                key=lambda artifact: (
                    artifact.source_document_id,
                    artifact.page_number,
                    artifact.rendered_artifact_id,
                ),
            )
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
    finding_text: str,
    finding_index: int | None,
    prompt_input_sha256: str,
) -> str:
    payload = {
        "source_document_id": record.source_document_id,
        "finding_index": finding_index,
        "finding_text": finding_text,
        "prompt_input_sha256": prompt_input_sha256,
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"finding-candidate-{digest}"
