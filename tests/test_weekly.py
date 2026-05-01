from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from welfare_inspections.collect.weekly import (
    MissingWeeklyCredentials,
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
    stages = [command.stage for command in plan.commands]
    assert stages == [
        "discover",
        "download",
        "parse",
        "parse-metadata",
        "render-pages",
        "extract-llm",
        "reconcile",
        "export",
        "backfill-summary",
    ]
    llm_command = next(
        command for command in plan.commands if command.stage == "extract-llm"
    )
    assert llm_command.command[-2:] == ["--mode", "dry-run"]
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
    assert any(
        "llm_eval_report.json" in path
        for path in artifact_manifest["upload_paths"]
    )


def test_weekly_plan_fails_closed_without_production_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WELFARE_INSPECTIONS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("WELFARE_INSPECTIONS_LLM_MODEL", raising=False)

    with pytest.raises(MissingWeeklyCredentials, match="WELFARE_INSPECTIONS_LLM"):
        create_weekly_run_plan(
            output_dir=tmp_path / "outputs" / "weekly",
            mode="production",
        )

    summary = json.loads(
        (tmp_path / "outputs" / "weekly" / "weekly_run_summary.json").read_text()
    )
    assert summary["status"] == "blocked_missing_credentials"
    assert summary["missing_production_env"] == [
        "WELFARE_INSPECTIONS_LLM_PROVIDER",
        "WELFARE_INSPECTIONS_LLM_MODEL",
    ]


def test_weekly_plan_can_record_missing_credentials_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WELFARE_INSPECTIONS_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("WELFARE_INSPECTIONS_LLM_MODEL", "test-model")

    plan = create_weekly_run_plan(
        output_dir=tmp_path / "outputs" / "weekly",
        mode="production",
        fail_on_missing_credentials=False,
    )

    assert plan.missing_production_env == ["WELFARE_INSPECTIONS_LLM_PROVIDER"]
    llm_command = next(
        command for command in plan.commands if command.stage == "extract-llm"
    )
    assert llm_command.command[-2:] == ["--mode", "production"]


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
    assert "weekly incremental" in result.stdout
