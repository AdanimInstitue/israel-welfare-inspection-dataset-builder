# Architecture

This is an authorized public-data transparency project conducted by Adanim
Institute, a semi-governmental public-policy research institute, in
collaboration with the Israeli Ministry of Welfare and the Taub Institute.

The builder converts publicly published Ministry welfare inspection reports from
PDF documents into reproducible, auditable open dataset artifacts. The first PR
only documents the design and adds a lightweight validation scaffold.

## Builder/Data Repository Split

The builder repository is for:

- ETL source code
- parser logic
- source discovery and collection logic
- tests
- schemas
- configs
- documentation
- CI/workflows
- small fixtures only

The paired data repository is for generated dataset outputs:

```text
israel-welfare-inspection-dataset/
  README.md
  LICENSE
  NOTICE.md
  DISCLAIMER.md
  datapackage.json
  data/
    current/
      reports.csv
      reports.jsonl
      facilities.csv
      inspections.csv
      source_documents.csv
      parse_warnings.csv
    releases/
      YYYY-MM-DD/
  metadata/
    schema/
    source_manifest.json
    extraction_run_manifest.json
```

Generated dataset artifacts must not be committed to the builder repository.

## Intended ETL Stages

1. Discover newly published PDF reports from the Gov.il portal.
2. Download PDFs and record checksums.
3. Extract embedded text and document metadata.
4. Render PDF pages/images for multimodal extraction.
5. Run LLM-based extraction for every report, using embedded text, rendered
   pages, and source provenance as inputs.
6. Parse deterministic top-level report metadata and detailed findings where
   reliable rules exist.
7. Reconcile deterministic and LLM-derived candidates into canonical rows.
8. Run LLM evaluation and quality gates against reviewed fixtures and active
   release thresholds.
9. Normalize Hebrew text, dates, facility names, facility types, districts,
   administrations, visit types, and inspection fields.
10. Validate canonical schemas.
11. Export CSV, JSON, JSONL, and Parquet outputs.
12. Preserve raw provenance, model diagnostics, parse diagnostics, and quality
    warnings.
13. Open a PR into the paired data repository for publication.

## Extraction Strategy

The real Ministry PDF reports are not reliably parseable from embedded text
alone. The Ministry is aware of the issue, but source PDF structure is not
expected to change soon enough for the dataset roadmap. V1 therefore requires
both deterministic extraction and LLM-based extraction as normal production
inputs.

Deterministic layers remain important for page counts, checksums, embedded text,
stable IDs, simple field extraction, and cheap regression signals. PyMuPDF is
the embedded-text extraction layer, pdfplumber supports layout/table debugging,
and pypdf supports metadata/page structural checks.

The LLM layer is not a loose fallback. It is a required extraction stage that
should use both embedded text and rendered PDF pages, return strict JSON, and
preserve evidence for each value. Each LLM extraction result must record model
name, prompt/template version, immutable input hashes, source document ID, page
number, evidence text or visual locator, confidence, warnings, and validation
status. Rendered page artifacts need a versioned render profile, image checksums,
and a stable coordinate system so visual locators remain reproducible.

Canonical rows are produced by a reconciliation layer. The reconciler compares
deterministic candidates, embedded-text LLM candidates, multimodal LLM
candidates, and existing canonical values during backfills. It accepts values
only when they pass schema validation and provenance requirements; conflicts are
preserved as diagnostics instead of silently overwritten. Material conflicts stay
`needs_review` unless deterministic rules or explicit agreement thresholds
resolve them; a reconciler LLM may propose, but must not be the only authority
for accepting a disputed value.

LLM quality is measured separately from mocked provider tests. Release planning
requires an evaluation report with field-level coverage, correctness, and
regressions for the active schema, model, prompt, renderer, and reconciler
versions before publication.

PR 7 implements the first local contracts for this architecture: full-page
rendered PNG artifacts with immutable image/PDF hashes, schema-bound LLM
candidate manifests, fail-closed production provider configuration checks,
dry-run/mock offline extraction modes, and an offline evaluation report stub.
These artifacts remain local sidecars until a later reconciliation PR accepts
candidate values into canonical rows.

PR 8 adds that first reconciliation sidecar layer for report-level metadata.
The reconciler reads local deterministic metadata and LLM candidate manifests,
records field-level decisions with compared candidate IDs, and writes ignored
reconciled metadata plus diagnostics. Accepted fields retain accepted extraction
methods and LLM candidate references where available. Material conflicts stay
`needs_review`. The backfill command is versioned dry-run plumbing only and
records input hashes and change counters without live collection or canonical
overwrites.

PR 9 adds dry-run workflow orchestration plumbing without changing publication
behavior. The `weekly-plan` command writes a plan, artifact manifest, and run
summary under ignored local outputs. The plan records the identity and version
fields needed for future new/changed/unchanged reuse decisions, but PR 9 does
not enforce incremental cache reuse yet. The GitHub Actions workflow is
dry-run-only, uploads explicit diagnostics and review manifests for human
review, and blocks production weekly mode until live LLM provider calls and
real incremental reuse exist. It does not commit artifacts, publish data, run
deterministic exports, or launch historical backfills implicitly.

PR 10 adds a planning-first publication layer without connecting publication to
weekly automation. The `publish-plan` command reads reviewed local artifacts,
evaluates publication gates, and writes ignored planning sidecars for a paired
data-repo branch and PR. Dry-run mode can produce blocked diagnostics for
review. Production mode fails closed before any data-repo PR action unless
reviewed inputs exist, human approval is explicit, diagnostics and LLM
evaluation gates are clear, and GitHub credentials are available. The plan
generates proposed data-repo PR body and release notes that distinguish
official Ministry source PDFs from unofficial derived parsed data, list
diagnostics and LLM metadata, and exclude downloaded PDFs, rendered page images,
prompt payloads, raw LLM responses, finding-level rows, suspected sensitive
personal data, and builder-repository generated outputs.

PR 11 adds a narrow finding-level review layer. The `extract-findings` command
can run in dry-run or mock mode over local manifests, text diagnostics, rendered
page manifests, and mock finding responses. It writes ignored
`finding_candidates.jsonl` and `finding_extraction_diagnostics.json` sidecars
with source provenance, evidence, prompt/model metadata where applicable,
immutable input hashes where available, confidence, warnings, and validation
status. It does not feed findings into canonical exports, publication inputs,
dashboards, scheduled workflows, OCR, or live provider calls.

OCR remains optional infrastructure for future quality improvement, but it is
not the main answer to the current PDF issue. When OCR is used, it should be
treated as another candidate source and reconciled with the same provenance and
validation rules.

## Provenance and Quality Model

Every discovered report should retain source URL, Gov.il item metadata where
available, publication/update dates, discovery time, download time, HTTP
diagnostics where relevant, PDF SHA-256, local storage path, and collector
version.

Every parsed row should retain enough context to audit it back to a source
document, page, raw excerpt or visual locator, extraction method, model/prompt
version where applicable, input artifact hashes, confidence score, and warning
status.

## Weekly Incremental Jobs vs. Backfill Jobs

The project needs two distinct operating modes:

- Weekly incremental jobs discover and process only new or changed Gov.il
  reports. They should avoid re-running expensive LLM extraction for unchanged
  source document checksums and should open reviewable artifact or data-repo
  PRs.
- Backfill jobs intentionally reprocess historical documents when extraction
  prompts, schemas, models, renderers, normalization rules, or reconciliation
  logic change. Backfills must be idempotent, versioned, resumable, and able to
  compare old and new canonical values before publication.

Both modes should produce diagnostics and review artifacts before data-repo
publication, including LLM evaluation reports when LLM-derived fields are in
scope. Backfills should not be hidden inside weekly jobs.

The PR 9 weekly workflow implements the first review-artifact gate: dry-run
runs can call the existing discover, download, parse, parse-metadata,
render-pages, extract-llm, reconcile, and dry-run backfill-summary commands,
but the backfill step is only a diagnostics summary over the current run
outputs. Historical reprocessing and reconciled canonical exports remain
explicit future work.

PR 10 keeps publication as a separate manual-dispatch-friendly step after
artifact review. It prepares commands for a data-repo publication branch and PR
against `AdanimInstitue/israel-welfare-inspection-dataset`, never `main`, but
does not copy generated dataset artifacts into the builder repository and does
not perform automatic weekly publishing.

## Intended Builder Layout

```text
israel-welfare-inspection-dataset-builder/
  README.md
  LICENSE
  pyproject.toml
  uv.lock
  .python-version
  .gitignore
  .env.example
  AGENTS.md
  src/
    welfare_inspections/
      __init__.py
      cli.py
      config.py
      logging.py
      paths.py
      collect/
        __init__.py
        govil_client.py
        portal_discovery.py
        browser_discovery.py
        models.py
      download/
        __init__.py
        pdf_downloader.py
        checksum.py
        manifest.py
      parse/
        __init__.py
        pdf_text.py
        pdf_render.py
        ocr.py
        llm_extract.py
        reconcile.py
        sections.py
        fields.py
        tables.py
        quality.py
      normalize/
        __init__.py
        hebrew.py
        dates.py
        facilities.py
        geography.py
        categories.py
      dataset/
        __init__.py
        schema.py
        build.py
        export.py
        datapackage.py
      workflows/
        __init__.py
        incremental.py
        backfill.py
      publish/
        __init__.py
        github_data_repo.py
        changelog.py
  schemas/
    report.schema.json
    facility.schema.json
    inspection.schema.json
    datapackage.schema.json
  configs/
    sources.yaml
    extraction_rules.yaml
    category_mappings.yaml
  data_samples/
    raw_pdfs/
    expected_outputs/
  tests/
    test_imports.py
    test_docs_exist.py
  notebooks/
    01_source_site_probe.ipynb
    02_pdf_structure_probe.ipynb
    03_schema_design_probe.ipynb
  docs/
    architecture.md
    source_site_notes.md
    schema.md
    extraction_methodology.md
    data_quality.md
    privacy_and_publication_policy.md
    operations.md
    roadmap.md
    implementation_plan.md
  scripts/
    inspect_portal.py
    inspect_pdf.py
    build_dataset.py
  .github/
    workflows/
      ci.yml
      weekly-build.yml
      publish-to-data-repo.yml
```

PR 1 creates only the minimal subset needed for documentation and CI. The
remaining files should be added in later implementation PRs when their contracts
are ready.
