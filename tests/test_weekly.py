from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from welfare_inspections.collect.weekly import (
    UnsupportedWeeklyProductionMode,
    WeeklyRunPlan,
    create_weekly_run_plan,
)


def test_weekly_plan_builds_safe_dry_run_commands(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "weekly"

    plan = create_weekly_run_plan(
        output_dir=output_dir,
        mode="dry-run",
        max_pages=2,
        request_delay_seconds=0,
    )

    assert plan.mode == "dry-run"
    assert plan.allow_backfill is False
    assert plan.publishes_data is False
    assert plan.production_supported is False
    assert plan.incremental_status == "planned_not_enforced"
    stages = [command.stage for command in plan.commands]
    assert stages == [
        "discover",
        "download",
        "parse",
        "parse-metadata",
        "render-pages",
        "extract-llm",
        "reconcile",
        "backfill-summary",
    ]
    llm_command = next(
        command for command in plan.commands if command.stage == "extract-llm"
    )
    assert llm_command.command[-2:] == ["--mode", "dry-run"]
    assert not any(
        "llm_metadata_candidates.jsonl" in path
        for path in llm_command.upload_artifacts
    )
    reconcile_command = next(
        command for command in plan.commands if command.stage == "reconcile"
    )
    assert reconcile_command.upload_artifacts == [
        str(output_dir / "reconciliation_diagnostics.json")
    ]
    assert "--max-pages" in plan.commands[0].command
    assert "2" in plan.commands[0].command

    plan_path = output_dir / "weekly_run_plan.json"
    summary_path = output_dir / "weekly_run_summary.json"
    artifact_manifest_path = output_dir / "weekly_artifact_manifest.json"
    assert plan_path.exists()
    assert summary_path.exists()
    assert artifact_manifest_path.exists()
    assert json.loads(summary_path.read_text())["status"] == "planned"
    artifact_manifest = json.loads(artifact_manifest_path.read_text())
    assert "downloaded PDFs" in artifact_manifest["intentionally_excluded"]
    assert "prompt payloads" in artifact_manifest["intentionally_excluded"]
    assert any(
        "llm_eval_report.json" in path
        for path in artifact_manifest["upload_paths"]
    )
    assert not any("reports.csv" in path for path in artifact_manifest["upload_paths"])
    assert not any(
        "report_metadata.jsonl" in path for path in artifact_manifest["upload_paths"]
    )
    assert not any(
        "llm_metadata_candidates.jsonl" in path
        for path in artifact_manifest["upload_paths"]
    )


def test_weekly_plan_blocks_production_mode(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedWeeklyProductionMode, match="not supported"):
        create_weekly_run_plan(
            output_dir=tmp_path / "outputs" / "weekly",
            mode="production",
        )


def test_weekly_plan_rejects_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode must be dry-run"):
        create_weekly_run_plan(
            output_dir=tmp_path / "outputs" / "weekly",
            mode="mock",
        )


def test_weekly_plan_rejects_invalid_limits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_pages"):
        create_weekly_run_plan(
            output_dir=tmp_path / "outputs" / "weekly",
            max_pages=0,
        )
    with pytest.raises(ValueError, match="request_delay_seconds"):
        create_weekly_run_plan(
            output_dir=tmp_path / "outputs" / "weekly",
            request_delay_seconds=-1,
        )


def test_weekly_plan_contract_rejects_backfills_and_publication() -> None:
    base_payload = {
        "mode": "dry-run",
        "output_dir": "outputs/weekly",
        "artifact_dir": "outputs/weekly/review_artifacts",
        "max_pages": 1,
        "request_delay_seconds": 0,
        "unchanged_document_policy": "not enforced",
        "artifact_manifest_path": "outputs/weekly/weekly_artifact_manifest.json",
        "summary_path": "outputs/weekly/weekly_run_summary.json",
    }
    with pytest.raises(ValueError, match="historical backfills"):
        WeeklyRunPlan.model_validate({**base_payload, "allow_backfill": True})
    with pytest.raises(ValueError, match="publish data"):
        WeeklyRunPlan.model_validate({**base_payload, "publishes_data": True})


def test_weekly_plan_rejects_repo_local_non_outputs_path() -> None:
    with pytest.raises(ValueError, match="outputs"):
        create_weekly_run_plan(
            output_dir=Path("not-ignored-weekly"),
            mode="dry-run",
        )


def test_cli_weekly_plan_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "weekly-plan", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "weekly dry-run" in result.stdout


def test_cli_weekly_plan_production_mode_fails() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "welfare_inspections.cli",
            "weekly-plan",
            "--mode",
            "production",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "not supported" in result.stderr
