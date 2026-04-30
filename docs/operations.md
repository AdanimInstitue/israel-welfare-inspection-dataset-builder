# Operations

PR 2 adds a manual source discovery prototype. PR 3 adds a separate manual PDF
download/checksum layer that reads the PR 2 source manifest. PR 4 adds a manual
embedded-text extraction layer that reads the PR 3 download manifest. PR 5 adds
a manual top-level metadata parser that reads PR 4 extracted text and
diagnostics. PR 6 adds a manual schema validation and local export layer that
reads PR 5 metadata JSONL and diagnostics. These commands are inert by default
and write ignored local outputs. CI remains offline and uses mocked or synthetic
inputs only.

## Future CLI

The future CLI should be exposed as `welfare-inspections`.

Current manual commands:

- `welfare-inspections discover`
- `welfare-inspections download`
- `welfare-inspections parse`
- `welfare-inspections parse-metadata`
- `welfare-inspections export`

Planned future commands:

- `welfare-inspections build`
- `welfare-inspections publish`
- `welfare-inspections run-all`

Expected behavior:

- `discover` writes a source manifest JSONL.
- `download` reads a manifest and downloads/checksums PDFs.
- `parse` extracts embedded text and PDF diagnostics from downloaded PDFs.
- `parse-metadata` parses report-level metadata from extracted text and text
  diagnostics.
- `export` validates parsed report metadata and emits local CSV/JSONL outputs.
- `build` will later chain broader dataset outputs into a local output
  directory.
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

Current PR 4 parse command:

```bash
welfare-inspections parse \
  --source-manifest outputs/download_manifest.jsonl \
  --text-output-dir outputs/extracted_text \
  --diagnostics outputs/text_extraction_diagnostics.json
```

The parse command reads only the PR 3 download manifest and recorded local PDF
paths. It extracts embedded PDF text with PyMuPDF, records pypdf page-count and
metadata diagnostics, normalizes extracted text deterministically, and writes
per-document text files into ignored local outputs. It does not OCR, parse
report-level metadata, export datasets, publish data, or contact Gov.il.

Current PR 5 metadata parse command:

```bash
welfare-inspections parse-metadata \
  --text-diagnostics outputs/text_extraction_diagnostics.json \
  --output outputs/report_metadata.jsonl \
  --diagnostics outputs/metadata_parse_diagnostics.json
```

The metadata parser reads only PR 4 extracted text paths recorded in the text
diagnostics sidecar. It parses deterministic report-level fields, keeps raw and
normalized values separate, records excerpts and page numbers where page markers
are present, and preserves source provenance. It does not inspect PDFs, collect
from Gov.il, OCR, parse finding-level rows, export final datasets, publish data,
or contact the network.

Current PR 6 local export command:

```bash
welfare-inspections export \
  --metadata outputs/report_metadata.jsonl \
  --metadata-diagnostics outputs/metadata_parse_diagnostics.json \
  --output-dir outputs/exports
```

The export command reads only PR 5 metadata JSONL and diagnostics. It validates
each report row against the canonical Pydantic contract, writes
`reports.jsonl`, `reports.csv`, and `export_diagnostics.json` into the ignored
local output directory, and preserves provenance, raw fields, normalized fields,
field evidence, warnings, page counts, extraction status/confidence, report IDs,
and parse diagnostics. When writing inside this repository, `--output-dir` must
be under the ignored `outputs/` directory. Missing or invalid metadata parse
diagnostics fail the export before any report artifacts are written. Row
validation failures, duplicate report IDs, and malformed dates are recorded as
diagnostics where possible; valid rows continue to export. Export artifacts are
staged before promotion so a serialization failure does not leave a partial new
artifact set. It does not inspect PDFs, collect from Gov.il, OCR, parse
finding-level rows, publish data, write to the paired data repository, or
contact the network.

## Project Management

Use Python 3.11+ or 3.12. Prefer uv-based project management.

Current PR 2/PR 3/PR 4/PR 5/PR 6 runtime dependencies:

- `httpx`
- `beautifulsoup4`
- `lxml`
- `pymupdf`
- `pypdf`
- `pydantic`
- `pydantic-settings`
- `typer`
- `rich`
- `structlog`
- `tenacity`

Recommended future runtime dependencies:

- `playwright`
- `pdfplumber`
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

## Manual v0 Preview Publication Runbook

The project may do a one-time manual `v0 preview` publication before PR 7 and
PR 8 automation, but only as a report-metadata-only preview. This runbook is a
checkpointed plan; do not start live collection or data-repo publication until
the plan has been reviewed.

Step 1: run the local pipeline manually against public Gov.il data.

```bash
welfare-inspections discover \
  --output outputs/source_manifest.jsonl \
  --diagnostics outputs/discovery_diagnostics.json

welfare-inspections download \
  --source-manifest outputs/source_manifest.jsonl \
  --output-manifest outputs/download_manifest.jsonl \
  --diagnostics outputs/download_diagnostics.json \
  --download-dir downloads/pdfs

welfare-inspections parse \
  --source-manifest outputs/download_manifest.jsonl \
  --text-output-dir outputs/extracted_text \
  --diagnostics outputs/text_extraction_diagnostics.json

welfare-inspections parse-metadata \
  --text-diagnostics outputs/text_extraction_diagnostics.json \
  --output outputs/report_metadata.jsonl \
  --diagnostics outputs/metadata_parse_diagnostics.json

welfare-inspections export \
  --metadata outputs/report_metadata.jsonl \
  --metadata-diagnostics outputs/metadata_parse_diagnostics.json \
  --output-dir outputs/exports
```

Step 2: review generated local outputs and diagnostics.

- Confirm `outputs/exports/reports.jsonl`, `outputs/exports/reports.csv`, and
  `outputs/exports/export_diagnostics.json` exist.
- Review discovery, download, text extraction, metadata parse, and export
  diagnostics before publication.
- Stop if required provenance is missing, row validation failures are
  structural, extraction coverage is unexpectedly low, source access appears
  blocked or incomplete, or any privacy risk is detected.

Step 3: prepare a data-repo branch for a v0 report-metadata-only preview.

- Use `AdanimInstitue/israel-welfare-inspection-dataset`.
- Include only reviewed export artifacts, diagnostics summaries,
  `README`/schema metadata, `NOTICE`, `DISCLAIMER`, and release notes.
- Do not copy downloaded PDFs, builder-local caches, unreviewed large
  artifacts, or generated files back into this builder repository.

Step 4: open a PR into the data repository.

- Publication must be PR-based.
- Do not push directly to the data repo `main`.
- The PR should be non-draft only after local artifacts and diagnostics have
  been reviewed.

Step 5: include publication context.

- Use clear `v0 preview` language.
- State that outputs are report-level metadata only.
- Include source provenance, run dates, diagnostics summary, caveats, known
  limitations, CC BY 4.0 target license notice, source attribution to the
  Ministry of Welfare, and derived-data pipeline attribution.
- State that parsed data is unofficial and may contain parsing errors.
