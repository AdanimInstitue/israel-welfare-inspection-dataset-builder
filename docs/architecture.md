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
4. Apply OCR only where embedded text is missing or poor.
5. Parse top-level report metadata and detailed findings.
6. Normalize Hebrew text, dates, facility names, facility types, districts,
   administrations, visit types, and inspection fields.
7. Validate canonical schemas.
8. Export CSV, JSON, JSONL, and Parquet outputs.
9. Preserve raw provenance, parse diagnostics, and quality warnings.
10. Open a PR into the paired data repository for publication.

## Deterministic-First Parsing

The v1 pipeline should start with deterministic, auditable extraction. PyMuPDF
is the default embedded-text extraction layer, pdfplumber supports layout and
table debugging, and pypdf supports metadata/page structural checks. OCR with
OCRmyPDF/Tesseract is a fallback, not the default. Opaque LLM extraction is out
of scope for v1 because each field needs source traceability.

## Provenance and Quality Model

Every discovered report should retain source URL, Gov.il item metadata where
available, publication/update dates, discovery time, download time, HTTP
diagnostics where relevant, PDF SHA-256, local storage path, and collector
version.

Every parsed row should retain enough context to audit it back to a source
document, page, raw excerpt, extraction method, confidence score, and parse
warning status.

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
        ocr.py
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
