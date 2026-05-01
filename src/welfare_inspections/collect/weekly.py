"""Weekly review-artifact workflow planning contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from welfare_inspections.collect.local_outputs import validate_local_output_path
from welfare_inspections.collect.models import utc_now

SCHEMA_VERSION = "weekly-run-plan-v1"
class UnsupportedWeeklyProductionMode(RuntimeError):
    """Raised when production weekly execution is requested before it exists."""


class WeeklyCommandPlan(BaseModel):
    """One CLI stage planned for a weekly dry-run review."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    command: list[str] = Field(min_length=1)
    outputs: list[str] = Field(default_factory=list)
    upload_artifacts: list[str] = Field(default_factory=list)
    network_required: bool = False
    notes: list[str] = Field(default_factory=list)


class WeeklyArtifactManifest(BaseModel):
    """Review artifacts expected from a weekly run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utc_now)
    artifact_root: str
    upload_paths: list[str] = Field(default_factory=list)
    required_review_artifacts: list[str] = Field(default_factory=list)
    intentionally_excluded: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WeeklyRunPlan(BaseModel):
    """Dry-run plan for GitHub Actions review artifact generation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utc_now)
    mode: str = Field(pattern="^dry-run$")
    output_dir: str
    artifact_dir: str
    max_pages: int = Field(ge=1)
    request_delay_seconds: float = Field(ge=0)
    allow_backfill: bool = False
    publishes_data: bool = False
    production_supported: bool = False
    incremental_status: str = "planned_not_enforced"
    version_contract: dict[str, str] = Field(default_factory=dict)
    unchanged_document_policy: str
    commands: list[WeeklyCommandPlan] = Field(default_factory=list)
    artifact_manifest_path: str
    summary_path: str
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_safe_weekly_contract(self) -> WeeklyRunPlan:
        if self.allow_backfill:
            msg = "weekly runs must not enable historical backfills"
            raise ValueError(msg)
        if self.publishes_data:
            msg = "weekly artifact runs must not publish data"
            raise ValueError(msg)
        return self


class WeeklyRunSummary(BaseModel):
    """Status sidecar written before a weekly workflow executes stages."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utc_now)
    status: str
    mode: str
    output_dir: str
    artifact_dir: str
    plan_path: str
    production_supported: bool = False
    incremental_status: str = "planned_not_enforced"
    notes: list[str] = Field(default_factory=list)


def create_weekly_run_plan(
    *,
    output_dir: Path = Path("outputs/weekly"),
    artifact_dir: Path | None = None,
    mode: str = "dry-run",
    max_pages: int = 1,
    request_delay_seconds: float = 2.0,
) -> WeeklyRunPlan:
    """Write the weekly plan, artifact manifest, and summary sidecars."""
    if mode == "production":
        msg = (
            "Production weekly runs are not supported until live LLM provider "
            "calls and incremental reuse are implemented. Use --mode dry-run."
        )
        raise UnsupportedWeeklyProductionMode(msg)
    if mode != "dry-run":
        msg = "mode must be dry-run"
        raise ValueError(msg)
    if max_pages < 1:
        msg = "max_pages must be at least 1"
        raise ValueError(msg)
    if request_delay_seconds < 0:
        msg = "request_delay_seconds must be non-negative"
        raise ValueError(msg)

    artifact_dir = artifact_dir or output_dir / "review_artifacts"
    validate_local_output_path(output_dir, label="weekly output directory")
    validate_local_output_path(artifact_dir, label="weekly artifact directory")

    paths = _weekly_paths(output_dir)
    commands = _weekly_commands(
        paths=paths,
        mode=mode,
        max_pages=max_pages,
        request_delay_seconds=request_delay_seconds,
    )
    artifact_manifest = WeeklyArtifactManifest(
        artifact_root=str(artifact_dir),
        upload_paths=_upload_paths(paths),
        required_review_artifacts=_required_review_artifacts(paths),
        intentionally_excluded=[
            "downloaded PDFs",
            "rendered page PNGs",
            "prompt payloads",
            "raw LLM provider responses",
            "canonical data-repository publication outputs",
        ],
        notes=[
            "Upload diagnostics and review sidecars only.",
            "The weekly workflow never commits generated artifacts.",
        ],
    )
    plan = WeeklyRunPlan(
        mode=mode,
        output_dir=str(output_dir),
        artifact_dir=str(artifact_dir),
        max_pages=max_pages,
        request_delay_seconds=request_delay_seconds,
        version_contract={
            "schema": "report.schema.json and sidecar schema versions",
            "source_identity": "source_document_id plus pdf_sha256",
            "renderer": "render_profile_id and render_profile_version",
            "llm": "model, model_version, prompt_id, prompt_version",
            "reconciliation": "schema_version and reconciler_version",
        },
        unchanged_document_policy=(
            "PR 9 records the identity and version fields needed for future "
            "reuse decisions, but this dry-run workflow does not enforce "
            "new/changed/unchanged classification yet."
        ),
        commands=commands,
        artifact_manifest_path=str(paths["artifact_manifest"]),
        summary_path=str(paths["summary"]),
        notes=[
            "Scheduled and manual runs are dry-run review-artifact runs.",
            "Production weekly execution remains blocked until live LLM provider "
            "calls and incremental reuse are implemented.",
            "Historical backfills remain explicit dry-run review commands and "
            "are not launched implicitly by the weekly job.",
        ],
    )

    _write_model_json(paths["plan"], plan)
    _write_model_json(paths["artifact_manifest"], artifact_manifest)
    summary = WeeklyRunSummary(
        status="planned",
        mode=mode,
        output_dir=str(output_dir),
        artifact_dir=str(artifact_dir),
        plan_path=str(paths["plan"]),
        production_supported=False,
        incremental_status="planned_not_enforced",
        notes=[
            "Run the planned commands only after this summary has status=planned."
        ],
    )
    _write_model_json(paths["summary"], summary)
    return plan


def _weekly_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "plan": output_dir / "weekly_run_plan.json",
        "summary": output_dir / "weekly_run_summary.json",
        "artifact_manifest": output_dir / "weekly_artifact_manifest.json",
        "source_manifest": output_dir / "source_manifest.jsonl",
        "discovery_diagnostics": output_dir / "discovery_diagnostics.json",
        "download_manifest": output_dir / "download_manifest.jsonl",
        "download_diagnostics": output_dir / "download_diagnostics.json",
        "downloads": output_dir / "downloads" / "pdfs",
        "text_dir": output_dir / "extracted_text",
        "text_diagnostics": output_dir / "text_extraction_diagnostics.json",
        "metadata": output_dir / "report_metadata.jsonl",
        "metadata_diagnostics": output_dir / "metadata_parse_diagnostics.json",
        "render_manifest": output_dir / "rendered_pages_manifest.jsonl",
        "rendered_pages": output_dir / "rendered_pages",
        "render_diagnostics": output_dir / "page_render_diagnostics.json",
        "llm_candidates": output_dir / "llm_metadata_candidates.jsonl",
        "llm_diagnostics": output_dir / "llm_extraction_diagnostics.json",
        "llm_eval_report": output_dir / "llm_eval_report.json",
        "reconciled_metadata": output_dir / "reconciled_report_metadata.jsonl",
        "reconciliation_diagnostics": output_dir / "reconciliation_diagnostics.json",
        "backfill_diagnostics": output_dir / "backfill_diagnostics.json",
    }


def _weekly_commands(
    *,
    paths: dict[str, Path],
    mode: str,
    max_pages: int,
    request_delay_seconds: float,
) -> list[WeeklyCommandPlan]:
    return [
        WeeklyCommandPlan(
            stage="discover",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "discover",
                "--output",
                str(paths["source_manifest"]),
                "--diagnostics",
                str(paths["discovery_diagnostics"]),
                "--max-pages",
                str(max_pages),
                "--request-delay-seconds",
                str(request_delay_seconds),
            ],
            outputs=[
                str(paths["source_manifest"]),
                str(paths["discovery_diagnostics"]),
            ],
            upload_artifacts=[str(paths["discovery_diagnostics"])],
            network_required=True,
            notes=["Conservative source probe starting from skip=0."],
        ),
        WeeklyCommandPlan(
            stage="download",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "download",
                "--source-manifest",
                str(paths["source_manifest"]),
                "--output-manifest",
                str(paths["download_manifest"]),
                "--diagnostics",
                str(paths["download_diagnostics"]),
                "--download-dir",
                str(paths["downloads"]),
                "--request-delay-seconds",
                str(request_delay_seconds),
            ],
            outputs=[
                str(paths["download_manifest"]),
                str(paths["download_diagnostics"]),
            ],
            upload_artifacts=[
                str(paths["download_manifest"]),
                str(paths["download_diagnostics"]),
            ],
            network_required=True,
            notes=["Downloaded PDFs remain local ignored artifacts, not uploads."],
        ),
        WeeklyCommandPlan(
            stage="parse",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "parse",
                "--source-manifest",
                str(paths["download_manifest"]),
                "--text-output-dir",
                str(paths["text_dir"]),
                "--diagnostics",
                str(paths["text_diagnostics"]),
            ],
            outputs=[str(paths["text_diagnostics"])],
            upload_artifacts=[str(paths["text_diagnostics"])],
            notes=["Extracted text files remain local ignored intermediates."],
        ),
        WeeklyCommandPlan(
            stage="parse-metadata",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "parse-metadata",
                "--text-diagnostics",
                str(paths["text_diagnostics"]),
                "--output",
                str(paths["metadata"]),
                "--diagnostics",
                str(paths["metadata_diagnostics"]),
            ],
            outputs=[str(paths["metadata"]), str(paths["metadata_diagnostics"])],
            upload_artifacts=[str(paths["metadata_diagnostics"])],
        ),
        WeeklyCommandPlan(
            stage="render-pages",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "render-pages",
                "--source-manifest",
                str(paths["download_manifest"]),
                "--output-manifest",
                str(paths["render_manifest"]),
                "--page-output-dir",
                str(paths["rendered_pages"]),
                "--diagnostics",
                str(paths["render_diagnostics"]),
            ],
            outputs=[str(paths["render_manifest"]), str(paths["render_diagnostics"])],
            upload_artifacts=[
                str(paths["render_manifest"]),
                str(paths["render_diagnostics"]),
            ],
            notes=["Rendered PNG files are excluded from upload by default."],
        ),
        WeeklyCommandPlan(
            stage="extract-llm",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "extract-llm",
                "--source-manifest",
                str(paths["download_manifest"]),
                "--text-diagnostics",
                str(paths["text_diagnostics"]),
                "--render-manifest",
                str(paths["render_manifest"]),
                "--output",
                str(paths["llm_candidates"]),
                "--diagnostics",
                str(paths["llm_diagnostics"]),
                "--eval-report",
                str(paths["llm_eval_report"]),
                "--mode",
                mode,
            ],
            outputs=[
                str(paths["llm_candidates"]),
                str(paths["llm_diagnostics"]),
                str(paths["llm_eval_report"]),
            ],
            upload_artifacts=[
                str(paths["llm_diagnostics"]),
                str(paths["llm_eval_report"]),
            ],
            network_required=False,
            notes=["Dry-run mode writes empty candidates and evaluation diagnostics."],
        ),
        WeeklyCommandPlan(
            stage="reconcile",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "reconcile",
                "--metadata",
                str(paths["metadata"]),
                "--metadata-diagnostics",
                str(paths["metadata_diagnostics"]),
                "--llm-candidates",
                str(paths["llm_candidates"]),
                "--output",
                str(paths["reconciled_metadata"]),
                "--diagnostics",
                str(paths["reconciliation_diagnostics"]),
            ],
            outputs=[
                str(paths["reconciled_metadata"]),
                str(paths["reconciliation_diagnostics"]),
            ],
            upload_artifacts=[
                str(paths["reconciliation_diagnostics"]),
            ],
        ),
        WeeklyCommandPlan(
            stage="backfill-summary",
            command=[
                "python",
                "-m",
                "welfare_inspections.cli",
                "backfill",
                "--reconciled-metadata",
                str(paths["reconciled_metadata"]),
                "--output",
                str(paths["backfill_diagnostics"]),
                "--evaluation-report",
                str(paths["llm_eval_report"]),
                "--dry-run",
            ],
            outputs=[str(paths["backfill_diagnostics"])],
            upload_artifacts=[str(paths["backfill_diagnostics"])],
            notes=[
                "This is a dry-run review summary, not an implicit historical backfill."
            ],
        ),
    ]


def _required_review_artifacts(paths: dict[str, Path]) -> list[str]:
    return [
        str(paths["plan"]),
        str(paths["summary"]),
        str(paths["artifact_manifest"]),
        str(paths["discovery_diagnostics"]),
        str(paths["download_diagnostics"]),
        str(paths["text_diagnostics"]),
        str(paths["metadata_diagnostics"]),
        str(paths["render_manifest"]),
        str(paths["render_diagnostics"]),
        str(paths["llm_diagnostics"]),
        str(paths["llm_eval_report"]),
        str(paths["reconciliation_diagnostics"]),
        str(paths["backfill_diagnostics"]),
    ]


def _upload_paths(paths: dict[str, Path]) -> list[str]:
    return [
        str(paths["plan"]),
        str(paths["summary"]),
        str(paths["artifact_manifest"]),
        str(paths["source_manifest"]),
        str(paths["download_manifest"]),
        str(paths["render_manifest"]),
        *_required_review_artifacts(paths),
    ]


def _write_model_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)
