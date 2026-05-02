# Operations

The operating model is layered. The first public layer is a report index built
from Gov.il listing-page facts only. Later layers add PDF source documents, raw
extracted text, processed canonical tables, and advanced analytics. Existing
commands remain useful, but they now belong to downstream layers instead of
being prerequisites for the first usable dataset.

PR 13 adds the manual report index layer. PR 2 adds a manual source discovery
prototype. PR 3 adds a separate manual PDF
download/checksum layer that reads the PR 2 source manifest. PR 4 adds a manual
embedded-text extraction layer that reads the PR 3 download manifest. PR 5 adds
a manual top-level metadata parser that reads PR 4 extracted text and
diagnostics. PR 6 adds a manual schema validation and local export layer that
reads PR 5 metadata JSONL and diagnostics. PR 7 adds manual page rendering,
schema-bound LLM candidate plumbing, and offline evaluation reporting. PR 8 adds
manual candidate reconciliation and diagnostics-first dry-run backfill
plumbing. PR 9 adds weekly review-artifact planning and GitHub Actions
plumbing. PR 10 adds gated publication PR planning for the paired data
repository. PR 11 adds offline finding-level candidate/review sidecars. PR 12
reframes these as layered dataset infrastructure. These commands are inert by
default and write ignored local outputs. CI remains offline and uses mocked or
synthetic inputs only.

Real PDF inspection showed that embedded-text parsing alone is not sufficient
for content-derived layers. Those layers need required LLM-based extraction,
including multimodal extraction from rendered PDF pages, plus reconciliation
before publication. The report index layer does not inspect report contents and
therefore does not require PDF download, text extraction, OCR, LLM extraction,
or reconciliation.

## Future CLI

The future CLI should be exposed as `welfare-inspections`.

Current manual commands:

- `welfare-inspections collect-report-index`
- `welfare-inspections discover`
- `welfare-inspections download`
- `welfare-inspections parse`
- `welfare-inspections parse-metadata`
- `welfare-inspections render-pages`
- `welfare-inspections extract-llm`
- `welfare-inspections extract-findings`
- `welfare-inspections reconcile`
- `welfare-inspections backfill`
- `welfare-inspections weekly-plan`
- `welfare-inspections publish-plan`
- `welfare-inspections export`

Planned future commands:

- `welfare-inspections build`
- `welfare-inspections publish`
- `welfare-inspections run-all`

Expected behavior:

- `collect-report-index` writes the first-layer report index CSV/JSONL and
  diagnostics from Gov.il listing-page facts only.
- `discover` writes a source manifest JSONL.
- `download` reads a manifest and downloads/checksums PDFs.
- `parse` extracts embedded text and PDF diagnostics from downloaded PDFs.
- `parse-metadata` parses report-level metadata from extracted text and text
  diagnostics.
- `render-pages` renders PDFs into ignored page images/crops for multimodal
  extraction using a versioned render profile and records per-artifact hashes.
- `extract-llm` runs required schema-bound LLM extraction and writes candidate
  manifests plus diagnostics.
- `extract-findings` writes finding-level candidate and diagnostics sidecars
  for offline review only.
- `reconcile` merges deterministic, text-LLM, multimodal-LLM, OCR, and existing
  candidates into canonical rows while leaving unresolved material conflicts as
  `needs_review`.
- `backfill` reprocesses historical documents when model, prompt, schema,
  renderer, parser, or reconciliation versions change.
- `weekly-plan` writes a safe dry-run review-artifact plan, run summary, and
  artifact manifest for scheduled/manual review-artifact workflows.
- `publish-plan` writes a gated publication plan, diagnostics, proposed
  data-repo PR body, and release notes without touching the paired data repo.
- `export` validates parsed report metadata and emits local CSV/JSONL outputs.
- `build` will later chain selected layered dataset outputs into a local output
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

Current PR 13 report index command:

```bash
welfare-inspections collect-report-index \
  --output-csv outputs/report_index/reports_index.csv \
  --output-jsonl outputs/report_index/reports_index.jsonl \
  --diagnostics outputs/report_index/report_index_diagnostics.json
```

The command collects only Gov.il listing-page facts visible in the source
cards. `reports_index.csv` must contain exactly the Hebrew source columns
`שם מסגרת`, `סוג מסגרת`, `סמל מסגרת`, `מינהל`, `מחוז`, and `תאריך ביצוע`.
`reports_index.jsonl` must contain those same values plus visible item/PDF
links and provenance. Internal aliases may use `institution_name`,
`institution_type`, `institution_symbol`, `administration`, `district`, and
`survey_date`.

The primary source path is the Gov.il structured DynamicCollector response when
it contains all six visible card fields. If that response omits a required
visible field or returns incomplete records, the command falls back to
browser-rendered public DOM collection for the run. The fallback uses optional
local Playwright support when available and is injectable for offline tests.
Diagnostics record the source path used, attempted source paths, per-field
coverage by path, pagination/source coverage, duplicate IDs, missing visible
fields, malformed date-like source text, HTTP/block diagnostics, and output
paths. The command must not download PDFs, parse PDF text, run OCR, call LLM
providers, extract findings, normalize facility names, or infer values not
visible on the listing page.

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

Current PR 7 page rendering, LLM extraction, and PR 8 reconciliation flow:

```bash
welfare-inspections render-pages \
  --source-manifest outputs/download_manifest.jsonl \
  --output-manifest outputs/rendered_pages_manifest.jsonl \
  --page-output-dir outputs/rendered_pages \
  --diagnostics outputs/page_render_diagnostics.json

welfare-inspections extract-llm \
  --source-manifest outputs/download_manifest.jsonl \
  --text-diagnostics outputs/text_extraction_diagnostics.json \
  --render-manifest outputs/rendered_pages_manifest.jsonl \
  --eval-fixtures data_samples/expected_outputs/llm_eval.jsonl \
  --output outputs/llm_metadata_candidates.jsonl \
  --diagnostics outputs/llm_extraction_diagnostics.json \
  --eval-report outputs/llm_eval_report.json \
  --mode mock \
  --mock-response-path outputs/mock_llm_responses.jsonl

welfare-inspections reconcile \
  --metadata outputs/report_metadata.jsonl \
  --metadata-diagnostics outputs/metadata_parse_diagnostics.json \
  --llm-candidates outputs/llm_metadata_candidates.jsonl \
  --output outputs/reconciled_report_metadata.jsonl \
  --diagnostics outputs/reconciliation_diagnostics.json

welfare-inspections backfill \
  --reconciled-metadata outputs/reconciled_report_metadata.jsonl \
  --output outputs/backfill_diagnostics.json \
  --evaluation-report outputs/llm_eval_report.json \
  --dry-run
```

The PR 7 `render-pages` command reads only PR 3 download manifests and local PDF
paths. It renders full-page PNGs with PyMuPDF using `default-v1`, records image
dimensions and SHA-256 hashes, writes
`outputs/rendered_pages_manifest.jsonl`, and preserves per-document diagnostics.
It does not collect from Gov.il, download PDFs, OCR, parse findings, publish, or
contact the network.

The PR 7 `extract-llm` command defaults to `--mode dry-run`, which validates the
plumbing and writes empty candidate outputs plus diagnostics. `--mode mock`
uses local JSONL mock responses for deterministic offline tests. `--mode
production` fails closed unless `WELFARE_INSPECTIONS_LLM_PROVIDER` and
`WELFARE_INSPECTIONS_LLM_MODEL` are configured; live provider calls are not
implemented in PR 7.

LLM extraction is expected in production runs. It should be disabled only for
offline tests or explicit dry-run/development scenarios. Provider configuration
failures should fail production extraction before export rather than silently
publishing deterministic-only rows.

LLM outputs must remain local ignored artifacts until reviewed and reconciled.
They must record model, prompt/template version, immutable input artifact hashes,
source document ID, page evidence, confidence, warnings, and schema validation
status.

Rendered page artifacts must record source PDF SHA-256, renderer version, render
profile, DPI, colorspace, image format, crop coordinates, coordinate system,
image dimensions, image SHA-256, and local ignored paths. The `visual_locator`
evidence emitted by LLM extraction must use that coordinate system.

Production publication must include an LLM evaluation report. Mocked provider
tests remain required for CI, but they are not enough to publish data. The eval
report should summarize field-level coverage, field-level correctness, and
regressions by model, prompt, renderer, schema, and reconciler version.

The PR 8 `reconcile` command reads only local PR 5 metadata outputs/diagnostics
and optional PR 7 LLM candidate manifests. It writes
`outputs/reconciled_report_metadata.jsonl` and
`outputs/reconciliation_diagnostics.json` by default. Deterministic-only values
and deterministic/LLM agreements can be accepted; material conflicts remain
`needs_review` with all candidate IDs preserved.

The PR 8 `backfill` command is dry-run-only. It reads reconciled metadata,
optionally references an LLM evaluation report, records input hashes and change
counts, and writes `outputs/backfill_diagnostics.json`. It does not perform
historical live collection, publication, or canonical overwrite.

Current PR 11 finding extraction command:

```bash
welfare-inspections extract-findings \
  --source-manifest outputs/download_manifest.jsonl \
  --text-diagnostics outputs/text_extraction_diagnostics.json \
  --render-manifest outputs/rendered_pages_manifest.jsonl \
  --output outputs/finding_candidates.jsonl \
  --diagnostics outputs/finding_extraction_diagnostics.json \
  --mode dry-run
```

The command is manual and review-only. `--mode dry-run` validates plumbing and
writes empty candidate output plus diagnostics. `--mode mock` validates local
JSONL mock finding responses with no network or provider calls.
`--mode production` fails closed because live finding providers are not
supported yet. Candidate rows preserve provenance, source/page evidence,
input hashes where available, prompt/model metadata where applicable,
confidence, warnings, and validation status. Malformed payloads become
diagnostics instead of emitted valid rows.

PR 11 does not OCR PDFs, call live providers, publish finding rows, add finding
rows to canonical exports, build dashboards, or change scheduled workflows.

Current PR 9 weekly plan command:

```bash
welfare-inspections weekly-plan \
  --output-dir outputs/weekly \
  --artifact-dir outputs/weekly/review_artifacts \
  --mode dry-run \
  --max-pages 1 \
  --request-delay-seconds 2
```

The command writes `weekly_run_plan.json`, `weekly_run_summary.json`, and
`weekly_artifact_manifest.json` under ignored local outputs. The plan records
the stage commands for `discover`, `download`, `parse`, `parse-metadata`,
`render-pages`, `extract-llm`, `reconcile`, and a dry-run `backfill` summary.
It also records the identity/version fields future incremental reuse needs:
`source_document_id`, `pdf_sha256`, schema versions, model/prompt versions,
render profile, and reconciler version. PR 9 does not enforce cache reuse or
classify documents as new, changed, or unchanged; those behaviors remain future
work. Production weekly mode is blocked until live LLM provider calls and real
incremental reuse exist, so scheduled/manual review runs stay in dry-run mode.

Current PR 10 publication plan command:

```bash
welfare-inspections publish-plan \
  --reviewed-artifact-dir outputs/weekly \
  --output-dir outputs/publication \
  --release-id YYYY-MM-DD \
  --approved-for-publication
```

The command writes `publication_plan.json`, `publication_diagnostics.json`,
`data_repo_pr_body.md`, and `release_notes.md` under ignored local outputs. It
does not push, open a PR, copy data-repo files, or connect publication to the
weekly workflow. Dry-run mode records blockers and planned commands for review
without requiring credentials. Production mode fails closed before any real
data-repo PR action unless reviewed input artifacts are present, explicit human
approval is provided, export/reconciliation/backfill diagnostics are clear, the
LLM evaluation report is present and passes release thresholds, and GitHub
credentials are configured.

Reviewed inputs currently expected under `--reviewed-artifact-dir`:

- `exports/reports.jsonl`
- `exports/reports.csv`
- `exports/export_diagnostics.json`
- `source_manifest.jsonl`
- `reconciliation_diagnostics.json`
- `llm_eval_report.json`
- `backfill_diagnostics.json`

The planned paired data-repo PR targets
`AdanimInstitue/israel-welfare-inspection-dataset` and uses a separate
publication branch such as `codex/data-publication-YYYY-MM-DD`. It never plans
to push directly to `main`. The generated PR body and release notes distinguish
official Ministry source documents from unofficial derived parsed data, include
diagnostics and LLM/model/prompt metadata where available, and exclude
downloaded PDFs, rendered page images, prompt payloads, raw LLM responses,
candidate payload manifests, finding-level rows, suspected sensitive personal
data, and generated publication artifacts in this builder repository.

## Weekly Incremental Jobs and Backfills

Future weekly incremental jobs:

- discover new or changed Gov.il source documents
- download/checksum only new or changed PDFs
- reuse existing deterministic and LLM candidate artifacts when the PDF
  checksum, schema, renderer, model, prompt, and reconciler versions are
  unchanged
- run required LLM extraction for new or changed documents
- export review artifacts and leave data-repo PR publication to a separate
  explicit publication workflow after validation, reconciliation, privacy, and
  LLM evaluation gates pass

The PR 9 workflow is `.github/workflows/weekly-artifacts.yml`. It runs on a
weekly schedule and by manual dispatch, uploads only explicit diagnostics and
review manifests from `outputs/weekly`, retains artifacts for short-term
review, and never commits generated outputs. Downloaded PDFs, rendered images,
prompt payloads, raw provider responses, generated report exports, candidate
payload manifests, and publication artifacts are intentionally excluded from
uploads.

Backfill jobs:

- intentionally reprocess historical documents when schema, prompt, model,
  renderer, deterministic parser, normalization, privacy policy, or
  reconciliation logic changes
- are resumable and idempotent
- compare previous canonical values with new candidates
- emit before/after diagnostics and change summaries
- include the new LLM evaluation report and immutable input hashes
- publish only through a data-repo PR

Backfills should not be hidden in weekly jobs. Weekly jobs keep current data
fresh; backfills improve historical data under explicit versioned changes.

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

- report index collection and validation workflow/artifact upload
- weekly build workflow for discovery/download/parse/render/LLM
  extraction/reconcile/build
- artifact upload for inspection before publication
- explicit backfill workflow for versioned reprocessing
- publish-to-data-repo workflow that opens a PR into the data repository
- LLM evaluation artifact upload and publication gate checks

Scheduled and publishing workflows should be added only when they are safe,
credential-aware, and cannot fail solely because live external access is absent.

## Manual v0 Report Index Publication Runbook

The project may do a one-time manual `v0 report index` publication before
weekly and publication automation. This preview is a source inventory from the
Gov.il listing page, not a parsed report-content dataset. This runbook is a
checkpointed plan; do not start live collection or data-repo publication until
the plan has been reviewed.

Step 1: run the report index layer manually against public Gov.il data.

```bash
welfare-inspections collect-report-index \
  --output-csv outputs/report_index/reports_index.csv \
  --output-jsonl outputs/report_index/reports_index.jsonl \
  --diagnostics outputs/report_index/report_index_diagnostics.json
```

Step 2: review generated local outputs and diagnostics.

- Confirm `outputs/report_index/reports_index.csv`,
  `outputs/report_index/reports_index.jsonl`, and
  `outputs/report_index/report_index_diagnostics.json` exist.
- Review report index diagnostics before publication.
- Stop if required provenance is missing, row validation failures are
  structural, source coverage is unexpectedly low, source access appears
  blocked or incomplete, duplicate IDs exist, or any privacy risk is detected.

Step 3: prepare a data-repo branch for a v0 report-index-only preview.

- Use `AdanimInstitue/israel-welfare-inspection-dataset`.
- Include only reviewed report index artifacts, diagnostics summaries,
  `README`/schema metadata, `NOTICE`, `DISCLAIMER`, and release notes.
- Do not copy downloaded PDFs, builder-local caches, unreviewed large
  artifacts, or generated files back into this builder repository.

Step 4: open a PR into the data repository.

- Publication must be PR-based.
- Do not push directly to the data repo `main`.
- The PR should be non-draft only after local artifacts and diagnostics have
  been reviewed.

Step 5: include publication context.

- Use clear `v0 report index` language.
- State that outputs are listing-page metadata only and do not contain PDF
  contents, extracted text, finding rows, OCR, LLM-derived fields, or advanced
  analytics.
- Include source provenance, run dates, diagnostics summary, caveats, known
  limitations, CC BY 4.0
  target license notice, source attribution to the Ministry of Welfare, and
  derived-data pipeline attribution.
- State that the index is unofficial derived data from the public Gov.il listing
  and may contain collection or source-site interpretation errors.
