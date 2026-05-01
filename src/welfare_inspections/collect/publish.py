"""Planning-first publication flow for the paired data repository."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from welfare_inspections.collect.local_outputs import (
    REPO_ROOT,
    validate_local_output_path,
)
from welfare_inspections.collect.manifest import _atomic_write_text
from welfare_inspections.collect.models import utc_now

SCHEMA_VERSION = "publication-plan-v1"
DEFAULT_DATA_REPO = "AdanimInstitue/israel-welfare-inspection-dataset"
DEFAULT_DATA_REPO_MAIN = "main"
DEFAULT_PUBLICATION_BRANCH_PREFIX = "codex/data-publication-"
JSONL_REQUIRED_FIELDS = {
    "reports_jsonl": (
        "report_id",
        "source_document_id",
        "govil_item_url",
        "pdf_url",
    ),
    "source_manifest": (
        "source_document_id",
        "govil_item_url",
        "pdf_url",
        "collector_version",
    ),
}
SUMMARY_REQUIRED_FIELDS = {
    "export": (
        "exported_records",
        "validation_failed_records",
        "duplicate_id_records",
    ),
    "reconciliation": (
        "accepted_decisions",
        "needs_review_decisions",
        "rejected_decisions",
    ),
    "backfill": (
        "unresolved_count",
        "rejected_count",
    ),
    "llm_evaluation": (
        "schema_version",
        "prompt_id",
        "prompt_version",
        "model_name",
        "covered_field_count",
        "correct_field_count",
        "missing_field_count",
        "incorrect_field_count",
        "regression_count",
    ),
}


class PublicationGateError(RuntimeError):
    """Raised when production publication planning is unsafe."""


class PublicationInput(BaseModel):
    """One reviewed input artifact considered by the publication planner."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    required: bool = True
    present: bool = False
    publishable_payload: bool = False
    notes: list[str] = Field(default_factory=list)


class PublicationGate(BaseModel):
    """One publication gate and its current status."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    required_for_production: bool = True
    detail: str


class PublicationCommandPlan(BaseModel):
    """A command a human or future executor can run against the data repo."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    command: list[str] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class PublicationPlan(BaseModel):
    """Reviewable publication plan and data-repo PR metadata."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utc_now)
    mode: str = Field(pattern="^(dry-run|production)$")
    status: str
    data_repo: str
    data_repo_base_branch: str
    data_repo_publication_branch: str
    release_id: str
    output_dir: str
    reviewed_artifact_dir: str
    publication_inputs: list[PublicationInput] = Field(default_factory=list)
    gates: list[PublicationGate] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    data_repo_files: list[str] = Field(default_factory=list)
    excluded_artifact_classes: list[str] = Field(default_factory=list)
    command_plan: list[PublicationCommandPlan] = Field(default_factory=list)
    pr_title: str
    pr_body_path: str
    release_notes_path: str
    diagnostics_path: str
    summaries: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_never_main(self) -> PublicationPlan:
        if self.data_repo_publication_branch == self.data_repo_base_branch:
            msg = "publication branch must not be the data repo base branch"
            raise ValueError(msg)
        if self.data_repo_publication_branch == "main":
            msg = "publication branch must never be main"
            raise ValueError(msg)
        return self


class PublicationDiagnostics(BaseModel):
    """Diagnostics sidecar for publication planning."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utc_now)
    status: str
    mode: str
    blockers: list[str] = Field(default_factory=list)
    gates: list[PublicationGate] = Field(default_factory=list)
    publication_inputs: list[PublicationInput] = Field(default_factory=list)
    summaries: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def create_publication_plan(
    *,
    reviewed_artifact_dir: Path = Path("outputs/weekly"),
    output_dir: Path = Path("outputs/publication"),
    mode: str = "dry-run",
    approved_for_publication: bool = False,
    data_repo: str = DEFAULT_DATA_REPO,
    data_repo_base_branch: str = DEFAULT_DATA_REPO_MAIN,
    data_repo_publication_branch: str | None = None,
    release_id: str | None = None,
    data_repo_worktree: Path | None = None,
) -> PublicationPlan:
    """Write publication planning sidecars without touching the data repo."""
    if mode not in {"dry-run", "production"}:
        msg = "mode must be dry-run or production"
        raise ValueError(msg)
    validate_local_output_path(output_dir, label="Publication output directory")
    _validate_data_repo_target(data_repo, data_repo_base_branch)
    if data_repo_worktree is not None:
        _validate_data_repo_worktree(data_repo_worktree)

    release_id = release_id or date.today().isoformat()
    data_repo_publication_branch = (
        data_repo_publication_branch
        or f"{DEFAULT_PUBLICATION_BRANCH_PREFIX}{release_id}"
    )
    paths = _publication_paths(output_dir)
    publication_inputs = _publication_inputs(reviewed_artifact_dir)
    summaries = _load_summaries(publication_inputs)
    blockers = _publication_blockers(
        publication_inputs=publication_inputs,
        summaries=summaries,
        approved_for_publication=approved_for_publication,
        mode=mode,
    )
    gates = _publication_gates(
        publication_inputs=publication_inputs,
        summaries=summaries,
        approved_for_publication=approved_for_publication,
        mode=mode,
        blockers=blockers,
    )
    status = "ready" if not blockers else "blocked"
    if mode == "production" and blockers:
        _write_diagnostics(
            paths["diagnostics"],
            PublicationDiagnostics(
                status=status,
                mode=mode,
                blockers=blockers,
                gates=gates,
                publication_inputs=publication_inputs,
                summaries=summaries,
                notes=[
                    "Production publication planning failed closed before any "
                    "data-repo branch, push, or PR action."
                ],
            ),
        )
        msg = "Production publication gates failed: " + "; ".join(blockers)
        raise PublicationGateError(msg)

    pr_title = f"Publish welfare inspection dataset {release_id}"
    data_repo_files = _planned_data_repo_files(release_id)
    command_plan = _command_plan(
        data_repo=data_repo,
        data_repo_base_branch=data_repo_base_branch,
        data_repo_publication_branch=data_repo_publication_branch,
        data_repo_worktree=data_repo_worktree,
        data_repo_files=data_repo_files,
        pr_title=pr_title,
        pr_body_path=paths["pr_body"],
    )
    plan = PublicationPlan(
        mode=mode,
        status=status,
        data_repo=data_repo,
        data_repo_base_branch=data_repo_base_branch,
        data_repo_publication_branch=data_repo_publication_branch,
        release_id=release_id,
        output_dir=str(output_dir),
        reviewed_artifact_dir=str(reviewed_artifact_dir),
        publication_inputs=publication_inputs,
        gates=gates,
        blockers=blockers,
        data_repo_files=data_repo_files,
        excluded_artifact_classes=_excluded_artifact_classes(),
        command_plan=command_plan,
        pr_title=pr_title,
        pr_body_path=str(paths["pr_body"]),
        release_notes_path=str(paths["release_notes"]),
        diagnostics_path=str(paths["diagnostics"]),
        summaries=summaries,
        notes=[
            "This builder command prepares reviewable publication metadata only.",
            "It must never push directly to the data repository main branch.",
            "Generated dataset files and publication artifacts stay out of this "
            "builder repository.",
        ],
    )
    _write_model_json(paths["plan"], plan)
    _atomic_write_text(paths["pr_body"], render_data_repo_pr_body(plan))
    _atomic_write_text(paths["release_notes"], render_release_notes(plan))
    _write_diagnostics(
        paths["diagnostics"],
        PublicationDiagnostics(
            status=status,
            mode=mode,
            blockers=blockers,
            gates=gates,
            publication_inputs=publication_inputs,
            summaries=summaries,
            notes=plan.notes,
        ),
    )
    return plan


def render_data_repo_pr_body(plan: PublicationPlan) -> str:
    """Render the proposed paired data-repo PR body."""
    summary = plan.summaries
    llm = summary.get("llm_evaluation", {})
    reconciliation = summary.get("reconciliation", {})
    export = summary.get("export", {})
    backfill = summary.get("backfill", {})
    blockers = "\n".join(f"- {blocker}" for blocker in plan.blockers) or "- None"
    files = "\n".join(f"- `{path}`" for path in plan.data_repo_files)
    excluded = "\n".join(f"- {item}" for item in plan.excluded_artifact_classes)
    gates = "\n".join(
        f"- [{'x' if gate.passed else ' '}] {gate.name}: {gate.detail}"
        for gate in plan.gates
    )
    return (
        f"## Publication\n\n"
        f"Release: `{plan.release_id}`\n\n"
        "This PR publishes unofficial derived parsed data generated by the "
        "Adanim/Taub welfare inspection builder pipeline. The official source "
        "documents remain the Ministry of Welfare PDF publications; this PR "
        "does not make the parsed dataset an official Ministry dataset.\n\n"
        "## Planned Data-Repo Files\n\n"
        f"{files}\n\n"
        "## Source Attribution and License\n\n"
        "- Source documents: Israeli Ministry of Welfare public inspection PDFs.\n"
        "- Derived data: Adanim Institute / Taub Institute builder pipeline.\n"
        "- Target license for derived dataset artifacts: CC BY 4.0.\n\n"
        "## Quality and Diagnostics\n\n"
        f"- Exported records: {export.get('exported_records', 'unknown')}.\n"
        f"- Export validation failures: "
        f"{export.get('validation_failed_records', 'unknown')}.\n"
        f"- Reconciliation accepted decisions: "
        f"{reconciliation.get('accepted_decisions', 'unknown')}.\n"
        f"- Reconciliation decisions needing review: "
        f"{reconciliation.get('needs_review_decisions', 'unknown')}.\n"
        f"- Backfill unresolved fields: "
        f"{backfill.get('unresolved_count', 'unknown')}.\n"
        f"- LLM model: {llm.get('model_name') or 'not recorded'} "
        f"{llm.get('model_version') or ''}.\n"
        f"- LLM prompt: {llm.get('prompt_id') or 'not recorded'} "
        f"{llm.get('prompt_version') or ''}.\n"
        f"- LLM evaluation: covered={llm.get('covered_field_count', 'unknown')}, "
        f"correct={llm.get('correct_field_count', 'unknown')}, "
        f"missing={llm.get('missing_field_count', 'unknown')}, "
        f"incorrect={llm.get('incorrect_field_count', 'unknown')}, "
        f"regressions={llm.get('regression_count', 'unknown')}.\n\n"
        "## Publication Gates\n\n"
        f"{gates}\n\n"
        "## Blockers\n\n"
        f"{blockers}\n\n"
        "## Excluded From Publication\n\n"
        f"{excluded}\n\n"
        "## Disclaimer\n\n"
        "Parsed fields may contain extraction, reconciliation, OCR, or LLM "
        "errors. Do not treat finding-level rows, suspected sensitive personal "
        "data, prompt payloads, raw LLM responses, rendered page images, or "
        "downloaded PDFs as publishable dataset artifacts in this PR.\n"
    )


def render_release_notes(plan: PublicationPlan) -> str:
    """Render release notes for the paired data repository."""
    llm = plan.summaries.get("llm_evaluation", {})
    return (
        f"# Release {plan.release_id}\n\n"
        "This release contains reviewed, unofficial derived report-level "
        "welfare inspection data. The Ministry of Welfare remains the source "
        "publisher for the official PDF documents; parsed outputs are produced "
        "by the Adanim/Taub builder pipeline and may contain errors.\n\n"
        "## Included\n\n"
        "- Report-level dataset files and schema/datapackage metadata.\n"
        "- Diagnostics summaries and source attribution.\n"
        "- LLM evaluation references where LLM-derived values are in scope.\n\n"
        "## LLM and Review Metadata\n\n"
        f"- Model: {llm.get('model_name') or 'not recorded'} "
        f"{llm.get('model_version') or ''}\n"
        f"- Prompt: {llm.get('prompt_id') or 'not recorded'} "
        f"{llm.get('prompt_version') or ''}\n"
        f"- Evaluation report path: "
        f"{_input_path_by_name(plan.publication_inputs, 'llm_evaluation_report')}\n\n"
        "## Not Included\n\n"
        "- Downloaded PDFs or rendered page images.\n"
        "- Prompt payloads or raw LLM responses.\n"
        "- Finding-level rows or suspected sensitive personal data.\n"
    )


def _publication_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "plan": output_dir / "publication_plan.json",
        "pr_body": output_dir / "data_repo_pr_body.md",
        "release_notes": output_dir / "release_notes.md",
        "diagnostics": output_dir / "publication_diagnostics.json",
    }


def _publication_inputs(reviewed_artifact_dir: Path) -> list[PublicationInput]:
    return [
        PublicationInput(
            name="reports_jsonl",
            path=str(reviewed_artifact_dir / "exports" / "reports.jsonl"),
            publishable_payload=True,
        ),
        PublicationInput(
            name="reports_csv",
            path=str(reviewed_artifact_dir / "exports" / "reports.csv"),
            publishable_payload=True,
        ),
        PublicationInput(
            name="export_diagnostics",
            path=str(reviewed_artifact_dir / "exports" / "export_diagnostics.json"),
        ),
        PublicationInput(
            name="source_manifest",
            path=str(reviewed_artifact_dir / "source_manifest.jsonl"),
        ),
        PublicationInput(
            name="reconciliation_diagnostics",
            path=str(reviewed_artifact_dir / "reconciliation_diagnostics.json"),
        ),
        PublicationInput(
            name="llm_evaluation_report",
            path=str(reviewed_artifact_dir / "llm_eval_report.json"),
        ),
        PublicationInput(
            name="backfill_diagnostics",
            path=str(reviewed_artifact_dir / "backfill_diagnostics.json"),
        ),
    ]


def _load_summaries(inputs: list[PublicationInput]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for publication_input in inputs:
        path = Path(publication_input.path)
        summary_key = _summary_key(publication_input.name)
        publication_input.present = path.exists()
        forbidden_reason = _forbidden_input_reason(path)
        if forbidden_reason:
            publication_input.notes.append(forbidden_reason)
        if not path.exists() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        if path.suffix.lower() == ".jsonl":
            summaries[summary_key] = _load_jsonl_summary(
                path,
                required_fields=JSONL_REQUIRED_FIELDS.get(publication_input.name, ()),
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summaries[summary_key] = {"error": str(exc)}
            continue
        summaries[summary_key] = _compact_summary(payload)
    return summaries


def _publication_blockers(
    *,
    publication_inputs: list[PublicationInput],
    summaries: dict[str, Any],
    approved_for_publication: bool,
    mode: str,
) -> list[str]:
    blockers: list[str] = []
    missing = [
        item.name for item in publication_inputs if item.required and not item.present
    ]
    if missing:
        blockers.append("Missing reviewed input artifacts: " + ", ".join(missing))
    forbidden = [
        f"{item.name}: {', '.join(item.notes)}"
        for item in publication_inputs
        if item.notes
    ]
    if forbidden:
        blockers.append("Forbidden publication inputs: " + "; ".join(forbidden))
    if not approved_for_publication:
        blockers.append("Human publication approval flag was not provided")
    if mode == "production" and not _github_token_present():
        blockers.append("GitHub token is required for production publication planning")

    for summary_key, summary in sorted(summaries.items()):
        if summary.get("error"):
            blockers.append(f"Reviewed artifact could not be parsed: {summary_key}")
        if summary.get("error_count", 0):
            blockers.append(f"Reviewed JSONL artifact is invalid: {summary_key}")
        if summary.get("record_count") == 0:
            blockers.append(f"Reviewed JSONL artifact is empty: {summary_key}")

    for summary_key, required_fields in SUMMARY_REQUIRED_FIELDS.items():
        summary = summaries.get(summary_key, {})
        missing_fields = [
            field
            for field in required_fields
            if field not in summary and "error" not in summary
        ]
        if missing_fields:
            blockers.append(
                f"Reviewed artifact missing required summary fields: "
                f"{summary_key} ({', '.join(missing_fields)})"
            )

    export = summaries.get("export", {})
    if export.get("validation_failed_records", 0) or export.get(
        "duplicate_id_records",
        0,
    ):
        blockers.append("Export diagnostics contain validation failures or duplicates")
    reconciliation = summaries.get("reconciliation", {})
    if reconciliation.get("needs_review_decisions", 0) or reconciliation.get(
        "rejected_decisions",
        0,
    ):
        blockers.append(
            "Reconciliation diagnostics contain unresolved review decisions"
        )
    backfill = summaries.get("backfill", {})
    if backfill.get("unresolved_count", 0) or backfill.get("rejected_count", 0):
        blockers.append("Backfill diagnostics contain unresolved or rejected fields")
    llm = summaries.get("llm_evaluation", {})
    if not llm:
        blockers.append("LLM evaluation report is missing or unreadable")
    elif any(
        llm.get(field, 0)
        for field in (
            "missing_field_count",
            "incorrect_field_count",
            "regression_count",
        )
    ):
        blockers.append(
            "LLM evaluation report contains missing, incorrect, or regressed fields"
        )
    return list(dict.fromkeys(blockers))


def _publication_gates(
    *,
    publication_inputs: list[PublicationInput],
    summaries: dict[str, Any],
    approved_for_publication: bool,
    mode: str,
    blockers: list[str],
) -> list[PublicationGate]:
    return [
        PublicationGate(
            name="reviewed_inputs_present",
            passed=all(item.present for item in publication_inputs if item.required),
            detail="All required reviewed artifacts must be present.",
        ),
        PublicationGate(
            name="human_publication_approval",
            passed=approved_for_publication,
            detail="Publication requires explicit human approval.",
        ),
        PublicationGate(
            name="credential_available",
            passed=mode == "dry-run" or _github_token_present(),
            detail="Production mode requires a GitHub token; dry-run does not.",
        ),
        PublicationGate(
            name="artifact_path_guard",
            passed=not any(item.notes for item in publication_inputs),
            detail=(
                "Inputs must exclude PDFs, images, prompt/raw LLM payloads, "
                "and findings."
            ),
        ),
        PublicationGate(
            name="quality_diagnostics_clear",
            passed=not any("diagnostics" in blocker.lower() for blocker in blockers),
            detail="Export, reconciliation, and backfill diagnostics must be clear.",
        ),
        PublicationGate(
            name="llm_evaluation_clear",
            passed="llm_evaluation" in summaries
            and not any("LLM evaluation" in blocker for blocker in blockers),
            detail="LLM evaluation report must be present and pass release thresholds.",
        ),
    ]


def _command_plan(
    *,
    data_repo: str,
    data_repo_base_branch: str,
    data_repo_publication_branch: str,
    data_repo_worktree: Path | None,
    data_repo_files: list[str],
    pr_title: str,
    pr_body_path: Path,
) -> list[PublicationCommandPlan]:
    owner, repo = data_repo.split("/", 1)
    worktree_note = (
        str(data_repo_worktree)
        if data_repo_worktree is not None
        else "a clean checkout of the paired data repo"
    )
    return [
        PublicationCommandPlan(
            stage="prepare-branch",
            command=[
                "git",
                "-C",
                str(data_repo_worktree or Path("<data-repo-worktree>")),
                "switch",
                "-c",
                data_repo_publication_branch,
                f"origin/{data_repo_base_branch}",
            ],
            notes=[f"Run only in {worktree_note}; never branch from data repo main."],
        ),
        PublicationCommandPlan(
            stage="copy-reviewed-files",
            command=[
                "copy-reviewed-publication-files",
                "--only",
                ",".join(data_repo_files),
            ],
            notes=[
                "Placeholder for a future executor; this PR only plans the file set."
            ],
        ),
        PublicationCommandPlan(
            stage="open-pr",
            command=[
                "gh",
                "pr",
                "create",
                "--repo",
                f"{owner}/{repo}",
                "--base",
                data_repo_base_branch,
                "--head",
                data_repo_publication_branch,
                "--title",
                pr_title,
                "--body-file",
                str(pr_body_path),
            ],
            notes=["Open a human-reviewable PR into the paired data repository."],
        ),
    ]


def _planned_data_repo_files(release_id: str) -> list[str]:
    release_dir = f"data/releases/{release_id}"
    return [
        "README.md",
        "NOTICE.md",
        "DISCLAIMER.md",
        "datapackage.json",
        "metadata/source_attribution.md",
        "metadata/diagnostics_summary.json",
        "metadata/llm_evaluation_summary.json",
        "data/current/reports.csv",
        "data/current/reports.jsonl",
        f"{release_dir}/reports.csv",
        f"{release_dir}/reports.jsonl",
        f"{release_dir}/RELEASE_NOTES.md",
    ]


def _excluded_artifact_classes() -> list[str]:
    return [
        "downloaded PDFs",
        "rendered page images",
        "prompt payloads",
        "raw LLM provider responses",
        "unreviewed large artifacts",
        "finding-level rows",
        "suspected sensitive personal data",
        "builder-repository generated publication outputs",
    ]


def _validate_data_repo_target(data_repo: str, base_branch: str) -> None:
    if data_repo != DEFAULT_DATA_REPO:
        msg = f"data repo must be {DEFAULT_DATA_REPO}"
        raise ValueError(msg)
    if base_branch != DEFAULT_DATA_REPO_MAIN:
        msg = "data repo PRs must target main unless policy changes"
        raise ValueError(msg)


def _validate_data_repo_worktree(data_repo_worktree: Path) -> None:
    resolved = data_repo_worktree.resolve()
    if resolved == REPO_ROOT.resolve():
        msg = "data repo worktree must not be the builder repository"
        raise ValueError(msg)
    if REPO_ROOT.resolve() in resolved.parents:
        msg = "data repo worktree must not be inside the builder repository"
        raise ValueError(msg)


def _forbidden_input_reason(path: Path) -> str | None:
    lowered_parts = {part.lower() for part in path.parts}
    lowered_name = path.name.lower()
    if path.suffix.lower() in {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".tif",
        ".tiff",
    }:
        return "binary source/rendered artifact is not publishable"
    if {"downloads", "pdfs"} <= lowered_parts:
        return "downloaded PDF directory is not publishable"
    if "rendered_pages" in lowered_parts:
        return "rendered page images are not publishable"
    if lowered_name in {"llm_metadata_candidates.jsonl", "mock_llm_responses.jsonl"}:
        return "candidate payloads or raw/mock LLM responses are not publishable"
    if "prompt_payloads" in lowered_parts or "raw_responses" in lowered_parts:
        return "prompt payloads and raw LLM responses are not publishable"
    if lowered_name in {
        "inspections.csv",
        "inspections.jsonl",
        "findings.csv",
        "findings.jsonl",
    }:
        return "finding-level rows are outside PR 10 publication scope"
    return None


def _compact_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "exported_records",
        "validation_failed_records",
        "duplicate_id_records",
        "accepted_decisions",
        "needs_review_decisions",
        "rejected_decisions",
        "unresolved_count",
        "rejected_count",
        "changed_count",
        "no_baseline_count",
        "schema_version",
        "prompt_id",
        "prompt_version",
        "model_name",
        "model_version",
        "renderer_name",
        "renderer_version",
        "render_profile_id",
        "render_profile_version",
        "expected_field_count",
        "observed_field_count",
        "covered_field_count",
        "correct_field_count",
        "missing_field_count",
        "incorrect_field_count",
        "regression_count",
    }
    return {key: payload.get(key) for key in keys if key in payload}


def _summary_key(name: str) -> str:
    return {
        "export_diagnostics": "export",
        "reconciliation_diagnostics": "reconciliation",
        "llm_evaluation_report": "llm_evaluation",
        "backfill_diagnostics": "backfill",
    }.get(name, name)


def _load_jsonl_summary(
    path: Path,
    *,
    required_fields: tuple[str, ...],
) -> dict[str, Any]:
    errors: list[str] = []
    record_count = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {"record_count": 0, "error_count": 1, "errors": [str(exc)]}

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        record_count += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path}:{line_number}: expected JSON object")
            continue
        missing_fields = [
            field
            for field in required_fields
            if field not in payload
            or payload[field] is None
            or payload[field] == ""
        ]
        if missing_fields:
            errors.append(
                f"{path}:{line_number}: missing required fields: "
                f"{', '.join(missing_fields)}"
            )

    return {
        "record_count": record_count,
        "error_count": len(errors),
        "errors": errors[:10],
    }


def _github_token_present() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


def _input_path_by_name(inputs: list[PublicationInput], name: str) -> str:
    for item in inputs:
        if item.name == name:
            return item.path
    return "not recorded"


def _write_model_json(path: Path, model: BaseModel) -> None:
    _atomic_write_text(path, model.model_dump_json(indent=2) + "\n")


def _write_diagnostics(path: Path, diagnostics: PublicationDiagnostics) -> None:
    _write_model_json(path, diagnostics)
