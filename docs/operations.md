# Operations

PR 1 provides documentation, a minimal package skeleton, and local validation.
It does not run a live collector or publish data.

## Future CLI

The future CLI should be exposed as `welfare-inspections`.

Planned commands:

- `welfare-inspections discover`
- `welfare-inspections download`
- `welfare-inspections parse`
- `welfare-inspections build`
- `welfare-inspections publish`
- `welfare-inspections run-all`

Expected behavior:

- `discover` writes a source manifest JSONL.
- `download` reads a manifest and downloads/checksums PDFs.
- `parse` extracts text and top-level metadata from downloaded PDFs.
- `build` emits CSV/JSONL outputs into a local output directory.
- `publish` opens a PR into the data repository, not a direct push to main.
- `run-all` chains the local non-publishing steps.

## Project Management

Use Python 3.11+ or 3.12. Prefer uv-based project management.

Recommended future runtime dependencies:

- `httpx`
- `playwright`
- `beautifulsoup4`
- `lxml`
- `pydantic`
- `pydantic-settings`
- `typer`
- `rich`
- `structlog`
- `tenacity`
- `pymupdf`
- `pdfplumber`
- `pypdf`
- `ocrmypdf`
- `pytesseract`
- `pillow`
- `opencv-python`
- `polars`
- `pyarrow`
- `orjson`
- `jsonschema`
- `frictionless`
- `pandera`
- `regex`
- `dateparser`
- `rapidfuzz`
- `python-dotenv`

Recommended future dev dependencies:

- `pytest`
- `pytest-cov`
- `ruff`
- `mypy` or `pyright`
- `pre-commit`
- `types-*` packages where useful

## GitHub Actions Plan

The initial CI workflow installs the package with dev dependencies, runs Ruff,
and runs pytest. It does not depend on network access, external credentials, or
the live Gov.il portal.

Future workflows should include:

- weekly build workflow for discovery/download/parse/build
- artifact upload for inspection before publication
- publish-to-data-repo workflow that opens a PR into the data repository

Scheduled and publishing workflows should be added only when they are safe,
credential-aware, and cannot fail solely because live external access is absent.
