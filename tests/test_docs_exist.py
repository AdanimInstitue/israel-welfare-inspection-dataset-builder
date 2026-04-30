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
