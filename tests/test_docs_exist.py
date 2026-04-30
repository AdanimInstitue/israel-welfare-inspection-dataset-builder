from __future__ import annotations

from pathlib import Path

REQUIRED_DOCS = [
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
]

REQUIRED_SCHEMAS = [
    "schemas/report.schema.json",
    "schemas/facility.schema.json",
    "schemas/inspection.schema.json",
    "schemas/datapackage.schema.json",
]


def test_required_docs_exist() -> None:
    for path in REQUIRED_DOCS:
        assert Path(path).is_file(), f"Missing required documentation: {path}"


def test_required_schemas_exist() -> None:
    for path in REQUIRED_SCHEMAS:
        assert Path(path).is_file(), f"Missing required schema placeholder: {path}"


def test_docs_preserve_core_project_contracts() -> None:
    docs = {
        "agents": Path("AGENTS.md").read_text(),
        "readme": Path("README.md").read_text(),
        "source_site": Path("docs/source_site_notes.md").read_text(),
        "privacy": Path("docs/privacy_and_publication_policy.md").read_text(),
        "extraction": Path("docs/extraction_methodology.md").read_text(),
        "quality": Path("docs/data_quality.md").read_text(),
        "roadmap": Path("docs/roadmap.md").read_text(),
    }

    assert (
        "https://www.gov.il/he/departments/dynamiccollectors/"
        "molsa-supervision-frames-reports?skip=0"
        in docs["agents"]
    )
    assert "AdanimInstitue/israel-welfare-inspection-dataset" in docs["agents"]
    assert "Repository Boundary" in docs["readme"]
    assert "Generated dataset artifacts belong" in docs["readme"]
    assert "skip=0" in docs["source_site"]
    assert "CC BY 4.0" in docs["privacy"]
    assert "deterministic" in docs["extraction"]
    assert "auditable" in docs["extraction"]
    assert "opaque" in docs["extraction"]
    assert "LLM-based extraction" in docs["extraction"]
    assert "fixtures" in docs["quality"]
    assert "Golden" in docs["quality"]
    assert "PR 2: Source Discovery Prototype" in docs["roadmap"]
