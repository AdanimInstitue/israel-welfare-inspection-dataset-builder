from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCS = [
    ".agent-plan.md",
    "docs/architecture.md",
    "docs/source_site_notes.md",
    "docs/schema.md",
    "docs/extraction_methodology.md",
    "docs/data_quality.md",
    "docs/privacy_and_publication_policy.md",
    "docs/operations.md",
    "docs/roadmap.md",
    "docs/implementation_plan.md",
    "AGENTS.md",
    "llms.txt",
]

REQUIRED_SCHEMAS = [
    "schemas/report.schema.json",
    "schemas/facility.schema.json",
    "schemas/inspection.schema.json",
    "schemas/datapackage.schema.json",
    "schemas/rendered_page_artifact.schema.json",
    "schemas/llm_extraction_candidate.schema.json",
    "schemas/llm_evaluation_report.schema.json",
    "schemas/extraction_candidate.schema.json",
    "schemas/reconciliation_decision.schema.json",
    "schemas/reconciliation_diagnostics.schema.json",
    "schemas/reconciled_report_metadata.schema.json",
    "schemas/backfill_diagnostics.schema.json",
]


def test_required_docs_exist() -> None:
    for path in REQUIRED_DOCS:
        assert (REPO_ROOT / path).is_file(), f"Missing required documentation: {path}"


def test_required_schemas_exist() -> None:
    for path in REQUIRED_SCHEMAS:
        assert (REPO_ROOT / path).is_file(), (
            f"Missing required schema placeholder: {path}"
        )


def test_docs_preserve_core_project_contracts() -> None:
    docs = {
        "agent_plan": (REPO_ROOT / ".agent-plan.md").read_text(),
        "agents": (REPO_ROOT / "AGENTS.md").read_text(),
        "llms": (REPO_ROOT / "llms.txt").read_text(),
        "readme": (REPO_ROOT / "README.md").read_text(),
        "source_site": (REPO_ROOT / "docs/source_site_notes.md").read_text(),
        "privacy": (
            REPO_ROOT / "docs/privacy_and_publication_policy.md"
        ).read_text(),
        "extraction": (REPO_ROOT / "docs/extraction_methodology.md").read_text(),
        "quality": (REPO_ROOT / "docs/data_quality.md").read_text(),
        "roadmap": (REPO_ROOT / "docs/roadmap.md").read_text(),
    }

    assert (
        "https://www.gov.il/he/departments/dynamiccollectors/"
        "molsa-supervision-frames-reports?skip=0"
        in docs["agents"]
    )
    assert "AdanimInstitue/israel-welfare-inspection-dataset" in docs["agents"]
    assert "Current System State" in docs["agent_plan"]
    assert "Active Task Breakdown" in docs["agent_plan"]
    assert "src/" in docs["llms"]
    assert "schemas/" in docs["llms"]
    assert "Repository Boundary" in docs["readme"]
    assert "Generated dataset artifacts belong" in docs["readme"]
    assert "skip=0" in docs["source_site"]
    assert "CC BY 4.0" in docs["privacy"]
    assert "auditable" in docs["extraction"]
    assert "LLM-based extraction" in docs["extraction"]
    assert "multimodal" in docs["extraction"]
    assert "reconciliation" in docs["extraction"]
    assert "fixtures" in docs["quality"]
    assert "Golden" in docs["quality"]
    assert "PR 2: Source Discovery Prototype" in docs["roadmap"]


def test_pr_agent_context_workflows_use_append_mode_and_coverage() -> None:
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
    refresh = (
        REPO_ROOT / ".github/workflows/pr-agent-context-refresh.yml"
    ).read_text()
    template = (REPO_ROOT / ".github/pr-agent-context-template.md").read_text()

    assert "shaypal5/pr-agent-context/.github/workflows/pr-agent-context.yml@v4" in ci
    assert "pytest --cov=welfare_inspections" in ci
    assert "pr-agent-context-coverage" in ci
    assert "publish_mode: append" in ci
    assert "debug_artifacts: true" in ci
    assert "execution_mode: refresh" in refresh
    assert "publish_mode: append" in refresh
    assert "enable_cross_run_coverage_lookup: true" in refresh
    assert "coverage_source_workflows: CI" in refresh
    assert "{{ patch_coverage_section }}" in template
