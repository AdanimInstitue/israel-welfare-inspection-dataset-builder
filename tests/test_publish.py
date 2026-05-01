from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from welfare_inspections.collect import publish as publish_module
from welfare_inspections.collect.publish import (
    PublicationGateError,
    create_publication_plan,
)


def test_publish_plan_builds_data_repo_pr_metadata(tmp_path: Path) -> None:
    reviewed_dir = _write_reviewed_artifacts(tmp_path)

    plan = create_publication_plan(
        reviewed_artifact_dir=reviewed_dir,
        output_dir=tmp_path / "outputs" / "publication",
        release_id="2026-05-01",
        approved_for_publication=True,
    )

    assert plan.status == "ready"
    assert plan.data_repo == "AdanimInstitue/israel-welfare-inspection-dataset"
    assert plan.data_repo_base_branch == "main"
    assert plan.data_repo_publication_branch == (
        "codex/data-publication-2026-05-01"
    )
    assert "data/current/reports.csv" in plan.data_repo_files
    assert "data/current/reports.jsonl" in plan.data_repo_files
    assert not any(path.endswith(".pdf") for path in plan.data_repo_files)
    assert not any("rendered_pages" in path for path in plan.data_repo_files)
    open_pr_command = next(
        command for command in plan.command_plan if command.stage == "open-pr"
    )
    assert "--repo" in open_pr_command.command
    assert "AdanimInstitue/israel-welfare-inspection-dataset" in (
        open_pr_command.command
    )
    assert "--base" in open_pr_command.command
    assert "main" in open_pr_command.command

    pr_body = (tmp_path / "outputs" / "publication" / "data_repo_pr_body.md").read_text(
        encoding="utf-8"
    )
    release_notes = (
        tmp_path / "outputs" / "publication" / "release_notes.md"
    ).read_text(encoding="utf-8")
    assert "official source documents remain the Ministry of Welfare PDF" in pr_body
    assert "unofficial derived parsed data" in pr_body
    assert "Downloaded PDFs" in pr_body or "downloaded PDFs" in pr_body
    assert "Prompt payloads" in release_notes or "prompt payloads" in release_notes
    assert "gpt-test" in pr_body
    assert "prompt-v1" in release_notes


def test_publish_plan_dry_run_records_blockers_without_credentials(
    tmp_path: Path,
) -> None:
    reviewed_dir = _write_reviewed_artifacts(tmp_path, needs_review=1)

    plan = create_publication_plan(
        reviewed_artifact_dir=reviewed_dir,
        output_dir=tmp_path / "outputs" / "publication",
        release_id="2026-05-01",
    )

    assert plan.status == "blocked"
    assert any("approval" in blocker for blocker in plan.blockers)
    assert any("Reconciliation" in blocker for blocker in plan.blockers)
    diagnostics = json.loads(
        (tmp_path / "outputs" / "publication" / "publication_diagnostics.json")
        .read_text(encoding="utf-8")
    )
    assert diagnostics["status"] == "blocked"


def test_publish_plan_production_fails_closed_without_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    reviewed_dir = _write_reviewed_artifacts(tmp_path)

    with pytest.raises(PublicationGateError, match="GitHub token"):
        create_publication_plan(
            reviewed_artifact_dir=reviewed_dir,
            output_dir=tmp_path / "outputs" / "publication",
            mode="production",
            approved_for_publication=True,
        )

    assert (
        tmp_path / "outputs" / "publication" / "publication_diagnostics.json"
    ).exists()


def test_publish_plan_rejects_builder_repo_outputs_and_worktree() -> None:
    with pytest.raises(ValueError, match="outputs"):
        create_publication_plan(
            reviewed_artifact_dir=Path("outputs/weekly"),
            output_dir=publish_module.REPO_ROOT / "docs" / "publication",
        )
    with pytest.raises(ValueError, match="builder repository"):
        create_publication_plan(
            reviewed_artifact_dir=Path("outputs/weekly"),
            output_dir=Path("outputs/publication"),
            data_repo_worktree=publish_module.REPO_ROOT,
        )


def test_publish_path_guard_blocks_forbidden_artifact_classes() -> None:
    assert "binary" in publish_module._forbidden_input_reason(Path("outputs/a.pdf"))
    assert "rendered" in publish_module._forbidden_input_reason(
        Path("outputs/rendered_pages/page.png")
    )
    assert "LLM" in publish_module._forbidden_input_reason(
        Path("outputs/llm_metadata_candidates.jsonl")
    )
    assert "finding-level" in publish_module._forbidden_input_reason(
        Path("outputs/exports/inspections.csv")
    )


def test_cli_publish_plan_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "publish-plan", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "publication PR" in result.stdout


def test_cli_main_publish_plan_invokes_planner(tmp_path: Path) -> None:
    from welfare_inspections.cli import main

    reviewed_dir = _write_reviewed_artifacts(tmp_path)
    output_dir = tmp_path / "outputs" / "publication"

    assert (
        main(
            [
                "publish-plan",
                "--reviewed-artifact-dir",
                str(reviewed_dir),
                "--output-dir",
                str(output_dir),
                "--release-id",
                "2026-05-01",
                "--approved-for-publication",
            ]
        )
        == 0
    )
    assert (output_dir / "publication_plan.json").exists()


def _write_reviewed_artifacts(
    tmp_path: Path,
    *,
    needs_review: int = 0,
) -> Path:
    reviewed_dir = tmp_path / "reviewed"
    export_dir = reviewed_dir / "exports"
    export_dir.mkdir(parents=True)
    (export_dir / "reports.jsonl").write_text(
        json.dumps({"report_id": "report-1", "source_document_id": "source-doc-1"})
        + "\n",
        encoding="utf-8",
    )
    (export_dir / "reports.csv").write_text(
        "report_id,source_document_id\nreport-1,source-doc-1\n",
        encoding="utf-8",
    )
    _write_json(
        export_dir / "export_diagnostics.json",
        {
            "exported_records": 1,
            "validation_failed_records": 0,
            "duplicate_id_records": 0,
        },
    )
    (reviewed_dir / "source_manifest.jsonl").write_text(
        json.dumps({"source_document_id": "source-doc-1"}) + "\n",
        encoding="utf-8",
    )
    _write_json(
        reviewed_dir / "reconciliation_diagnostics.json",
        {
            "accepted_decisions": 8,
            "needs_review_decisions": needs_review,
            "rejected_decisions": 0,
        },
    )
    _write_json(
        reviewed_dir / "llm_eval_report.json",
        {
            "schema_version": "llm-evaluation-report-v1",
            "prompt_id": "metadata-extraction",
            "prompt_version": "prompt-v1",
            "model_name": "gpt-test",
            "model_version": "2026-04-01",
            "covered_field_count": 5,
            "correct_field_count": 5,
            "missing_field_count": 0,
            "incorrect_field_count": 0,
            "regression_count": 0,
        },
    )
    _write_json(
        reviewed_dir / "backfill_diagnostics.json",
        {
            "changed_count": 0,
            "no_baseline_count": 8,
            "unresolved_count": 0,
            "rejected_count": 0,
        },
    )
    return reviewed_dir


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
