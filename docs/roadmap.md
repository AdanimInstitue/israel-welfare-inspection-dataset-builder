# Roadmap

## PR 1: Docs, Specs, Agent Instructions, CI Skeleton

Establish architecture, schema, extraction methodology, privacy/publication
policy, operations, roadmap, implementation plan, agent instructions, minimal
package skeleton, placeholder schemas, and CI.

## Layered Dataset Strategy

The project now treats public outputs as progressive dataset layers rather than
a single PDF-first ETL product:

1. Report index layer: a source-observed CSV/JSONL inventory of every report
   visible on the Gov.il listing page, without PDF content.
2. Source document layer: PDF URLs, downloaded file identity, checksums,
   manifests, and download diagnostics.
3. Raw text layer: extracted text and extraction diagnostics per
   report/document.
4. Processed canonical layer: cleaned, normalized, reconciled, schema-improved
   tables built from source metadata and extracted content.
5. Advanced analytics layer: derived insights and whole-dataset analyses built
   on top of reviewed canonical data.

The first layer is useful and publishable in principle without downloading or
parsing PDFs. Later PR 7-11 extraction, rendering, reconciliation, publication,
and finding-contract work remains valid as downstream infrastructure for the
source document, raw text, processed canonical, and analytics layers.

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

Implemented as offline PR 8 plumbing for report-level metadata: deterministic
PR 5 metadata fields are converted into candidate records, PR 7 LLM candidate
manifests are compared when present, deterministic-only and deterministic/LLM
agreement decisions can be accepted, and material deterministic/LLM conflicts
remain `needs_review`. The `backfill` command is diagnostics-first and dry-run
only; it records input hashes and change counters without collecting,
publishing, or overwriting historical canonical outputs.

## PR 9: Weekly Workflow and Artifact Upload

Add safe scheduled incremental automation and upload artifacts for review. The
weekly job should process new/changed reports and should not hide historical
backfills.

Implemented as PR 9 dry-run review-artifact plumbing: `weekly-plan` writes the
run plan, artifact manifest, and summary under ignored outputs, and
`.github/workflows/weekly-artifacts.yml` runs the existing review stages with
conservative defaults. The plan records the identity and version fields needed
for future incremental reuse, but PR 9 does not enforce cache reuse or
new/changed/unchanged classification yet. Scheduled/manual runs are dry-run
only; production weekly execution is blocked until live LLM provider calls and
real incremental reuse exist. The workflow uploads explicit diagnostics/review
artifacts only and does not publish to the paired data repository.

## PR 10: Publish PR Flow Into Data Repo

Implement publication automation that opens a PR into the paired data repository
instead of pushing directly to main.

Implemented as PR 10 planning-first publication plumbing. The
`publish-plan` command reads reviewed local artifacts, evaluates publication
gates, and writes ignored planning sidecars, data-repo PR body text, release
notes, and diagnostics. Dry-run mode is reviewable without credentials.
Production mode fails closed unless reviewed inputs exist, explicit human
approval is provided, diagnostics and LLM evaluation gates pass, and GitHub
credentials are available. The planned data-repo branch targets
`AdanimInstitue/israel-welfare-inspection-dataset` through a PR and never
pushes to `main`. Publication remains separate from the weekly artifact
workflow.

## PR 11: Finding-Level Extraction Contracts

Add the first narrow finding-level extraction slice: schema-bound candidate
contracts, diagnostics, and offline review plumbing. The `extract-findings`
command reads local manifests/diagnostics and optional mock responses, writes
ignored sidecars, and keeps findings as candidates only. It does not publish
finding rows, add canonical exports, call live providers, OCR PDFs, build
dashboards, or change scheduled workflows.

## PR 12: Layered Dataset Redesign

Reframe the project docs and agent instructions around layered public data
products. Define the report index layer as the first implementation target with
source-observed Hebrew CSV columns:

- `שם מסגרת`
- `סוג מסגרת`
- `סמל מסגרת`
- `מינהל`
- `מחוז`
- `תאריך ביצוע`

Use `administration` as the English translation for `מינהל` and `district` for
`מחוז`. Keep this PR docs-only: no runtime code, schema implementation,
generated datasets, or publication workflow changes.

## PR 13: Report Index Layer Implementation

Implement the first layer only. Collect Gov.il listing-page metadata, validate
the six Hebrew source-observed fields, preserve stable IDs and provenance, and
export ignored local `reports_index.csv` and JSONL preview artifacts. Do not
download PDFs except to capture visible/download-link metadata, parse PDF text,
run LLM/OCR extraction, publish to the data repository, or infer values that
are not visible on the listing page.

Implemented as the manual `welfare-inspections collect-report-index` command.
It writes ignored local `outputs/report_index/reports_index.csv`,
`reports_index.jsonl`, and `report_index_diagnostics.json`; uses the structured
Gov.il DynamicCollector response only when all six visible card fields are
present; falls back to browser-rendered public DOM collection when structured
records are incomplete; and records source-path, field-coverage, pagination,
duplicate-ID, missing-field, malformed source-date-text, run, and output-path
diagnostics. Tests remain mocked/offline only.

## Optional Manual v0 Report Index Publication

After PR 13 exists and its local report-index artifacts have been reviewed, the
project may publish a `v0 report index` manually into the paired data
repository. This preview is explicitly a source inventory built from
listing-page facts only. It does not need PDF text extraction, LLM extraction,
OCR, reconciliation, or finding extraction because it does not claim to
represent report contents. Publication must use a data-repo PR, include
provenance and caveats, avoid downloaded PDFs and unreviewed large artifacts,
and stop if local index validation or source coverage diagnostics show
structural problems.

## PR 14+: Downstream Layers, Findings, OCR, Quality Dashboards

Expand finding-level extraction, optional OCR candidate generation, quality
reports, parse warning dashboards, broader fixture coverage, model/prompt
evaluation sets, raw-text exports, processed canonical exports, and advanced
analytics after the report index layer is implemented.
