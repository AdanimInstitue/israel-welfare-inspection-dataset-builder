# Operations

PR 2 adds a manual source discovery prototype. PR 3 adds a separate manual PDF
download/checksum layer that reads the PR 2 source manifest. Both commands are
inert by default and write ignored local outputs. CI remains offline and uses
mocked responses only.

## Future CLI

The future CLI should be exposed as `welfare-inspections`.

Current manual commands:

- `welfare-inspections discover`
- `welfare-inspections download`

Planned future commands:

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

Current PR 2 discovery command:

```bash
welfare-inspections discover \
  --output outputs/source_manifest.jsonl \
  --diagnostics outputs/discovery_diagnostics.json
```

The command starts at the canonical `skip=0` URL, iterates conservatively, and
stops on empty, repeated, blocked, or exhausted pages. It records HTTP and parser
diagnostics, including structured endpoint requests. It does not download PDFs.

Current PR 3 download command:

```bash
welfare-inspections download \
  --source-manifest outputs/source_manifest.jsonl \
  --output-manifest outputs/download_manifest.jsonl \
  --diagnostics outputs/download_diagnostics.json \
  --download-dir downloads/pdfs
```

The download command reads only manifest records, downloads only each
`pdf_url`, computes SHA-256, and writes an updated JSONL manifest plus a
diagnostics sidecar. Existing files with a matching checksum are skipped without
network access unless `--force` is used. Existing files with a recorded checksum
mismatch are diagnosed and left untouched by default. Downloaded PDFs,
manifests, and diagnostics are local ignored outputs.

## Project Management

Use Python 3.11+ or 3.12. Prefer uv-based project management.

Current PR 2/PR 3 runtime dependencies:

- `httpx`
- `beautifulsoup4`
- `lxml`
- `pydantic`
- `pydantic-settings`
- `typer`
- `rich`
- `structlog`
- `tenacity`

Recommended future runtime dependencies:

- `playwright`
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
