# Roadmap

## PR 1: Docs, Specs, Agent Instructions, CI Skeleton

Establish architecture, schema, extraction methodology, privacy/publication
policy, operations, roadmap, implementation plan, agent instructions, minimal
package skeleton, placeholder schemas, and CI.

## PR 2: Source Discovery Prototype

Investigate the Gov.il dynamic collector, especially `skip=0` pagination and
any structured data endpoint. Produce a source manifest JSONL without
downloading PDFs.

## PR 3: PDF Download, Checksum, Manifest Layer

Download discovered public PDFs with conservative request rates, compute
SHA-256, and write resumable manifests.

## PR 4: Embedded Text Extraction and Hebrew Normalization

Extract text with PyMuPDF, inspect structure with pypdf/pdfplumber where useful,
and add Hebrew canonical text normalization.

## PR 5: Top-Level Metadata Parser

Parse report-level metadata such as facility name, facility type, district,
administration, visit type, visit date, publication date, and page count.

## PR 6: Schema Validation and Dataset Exports

Implement canonical schema validation and export CSV/JSONL outputs locally.

## Optional Manual v0 Preview Dataset Publication

Before automation, the project may publish a report-metadata-first `v0 preview`
manually into the paired data repository. Real PDF inspection showed that
deterministic embedded-text parsing alone is not publication-quality, so the v0
preview should wait for required LLM extraction and reconciliation unless it is
explicitly framed as a source inventory only. Publication must use a data-repo
PR, include provenance and caveats, avoid downloaded PDFs and unreviewed large
artifacts, and stop if local diagnostics show validation, coverage, LLM,
reconciliation, or privacy concerns.

## PR 7: LLM Extraction Contracts and Page Rendering

Add PDF page rendering plus required schema-bound text and multimodal LLM
candidate extraction. Define immutable rendered-page/input provenance and add
offline LLM evaluation reporting. Keep CI offline with mocked LLM responses.
Implemented as local `render-pages` and `extract-llm` commands, sidecar
contracts, mocked provider plumbing, and an offline evaluator stub. Live LLM
provider calls, reconciliation, backfill, OCR, finding-level extraction, and
publication remain later roadmap items.

## PR 8: Candidate Reconciliation and Backfill

Merge deterministic, LLM, OCR if present, and existing canonical candidates into
validated canonical rows. Add explicit backfill routines for versioned
historical reprocessing. Material conflicts remain `needs_review` unless
deterministic rules or explicit agreement thresholds resolve them.

## PR 9: Weekly Workflow and Artifact Upload

Add safe scheduled incremental automation and upload artifacts for review. The
weekly job should process new/changed reports and should not hide historical
backfills.

## PR 10: Publish PR Flow Into Data Repo

Implement publication automation that opens a PR into the paired data repository
instead of pushing directly to main.

## PR 11+: Detailed Findings Extraction, OCR, Quality Dashboards

Expand finding-level extraction, optional OCR candidate generation, quality
reports, parse warning dashboards, broader fixture coverage, and model/prompt
evaluation sets.
