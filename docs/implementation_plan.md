# Implementation Plan

## PR 2: Source Discovery Prototype

Tasks:

- Implement a manual source discovery command starting at the canonical `skip=0`
  URL.
- Detect whether records are available from server HTML or the public
  DynamicCollector structured endpoint.
- Document observed `skip` behavior and page size.
- Implement an inert-by-default discovery module that can write source manifest
  JSONL when run locally.
- Write a discovery diagnostics sidecar for HTTP status, block detection,
  parser counts, pagination stop reason, and run timestamps.
- Add tests with mocked HTTP/HTML responses only.

Acceptance criteria:

- No live network access in tests.
- Manifest fields match the documented source record contract.
- Source site notes are updated with observed discovery mechanism.
- Collector uses conservative defaults and clear logging.

## PR 3: PDF Download, Checksum, Manifest Layer

Tasks:

- Implement manifest reader/writer. Done in `collect.manifest`.
- Download PDFs from source manifest entries. Done via manual
  `welfare-inspections download`.
- Compute SHA-256 and record HTTP diagnostics. Done with per-record and run
  diagnostics.
- Make downloads resumable and idempotent. Done for existing valid files;
  checksum mismatches are diagnosed and left untouched unless forced.
- Add mocked download tests. Done; no live Gov.il access in tests.

Acceptance criteria:

- Existing files are not redownloaded unless checksum or policy requires it.
- Download failures produce diagnostics without corrupting manifests.
- No generated PDFs are committed.

## PR 4: Embedded Text Extraction and Hebrew Normalization

Tasks:

- Add PyMuPDF text extraction. Done via manual `welfare-inspections parse`.
- Add pypdf page count/metadata checks. Done in extraction diagnostics.
- Add Hebrew normalization helpers. Done for whitespace, zero-width/control
  removal, punctuation variants, and Hebrew geresh/gershayim handling.
- Add small synthetic fixture tests. Done without committed real PDFs.

Acceptance criteria:

- Extracted text preserves canonical logical order.
- Normalization handles spaces, zero-width characters, punctuation variants, and
  Hebrew geresh/gershayim variants.
- OCR remains documented but unimplemented unless separately scoped.
- Per-file extraction failures produce diagnostics where possible.
- Extracted text outputs, diagnostics, and downloaded PDFs remain ignored local
  artifacts.

## PR 5: Top-Level Metadata Parser

Tasks:

- Parse report-level fields from extracted text. Done via the manual
  `welfare-inspections parse-metadata` command.
- Return structured values plus raw excerpts, page numbers, confidence, and
  warnings. Done in the metadata JSONL and diagnostics sidecar.
- Add golden tests for representative synthetic examples. Done without
  committed real PDFs or live network access.

Acceptance criteria:

- Parser failures create warnings rather than crashing the full parse. Done for
  unavailable or missing text files and malformed dates.
- Raw and normalized fields remain distinct. Done in `MetadataField`.
- Docs/schema contracts are updated if fields change. Done for PR 5 metadata
  parse outputs.

## PR 6: Schema Validation and Local Exports

Tasks:

- Expand JSON Schema and Pydantic contracts. Done for canonical report-level
  local export rows.
- Validate canonical rows. Done during manual export from PR 5 metadata JSONL.
- Export local CSV and JSONL outputs. Done via inert
  `welfare-inspections export`.
- Add tests for duplicate IDs, required fields, and malformed dates. Done with
  synthetic offline metadata fixtures.

Acceptance criteria:

- Outputs are generated only into local ignored output directories. Done under
  `outputs/exports` by default.
- Builder repo still contains no generated dataset artifacts. Done.
- Exported rows retain source provenance and parse diagnostics. Done for
  report rows, field evidence, warnings, and metadata parse diagnostics.

## Manual v0 Preview Dataset Publication

This is an optional, checkpointed manual path before weekly and publication
automation. It may be used to produce a first public preview in the paired data
repository, but only after required LLM extraction and reconciliation are
represented in the local artifacts. Until those stages exist, the current
outputs are suitable for pipeline inspection, not publication as meaningful
parsed metadata.

Steps:

1. Run the local pipeline manually against public Gov.il data:
   `discover`, `download`, `parse`, future `render-pages`, future
   `extract-llm`, future `reconcile`, and `export`.
2. Review generated outputs and diagnostics locally before any publication
   work. Do not publish if diagnostics show structural validation failures,
   missing required provenance, unexpectedly low extraction coverage, missing
   required LLM stages, unresolved reconciliation conflicts, or privacy risk.
3. Prepare a data-repo branch containing only reviewed v0 report metadata
   artifacts, diagnostics summaries, schema/readme metadata, notices, and
   disclaimers. Do not copy downloaded PDFs, builder-local caches, or large
   unreviewed artifacts.
4. Open a PR into `AdanimInstitue/israel-welfare-inspection-dataset`; do not
   push directly to `main`.
5. In the data-repo PR, include provenance, caveats, diagnostics summary,
   license/disclaimer text, and clear `v0 preview` language.

Boundaries:

- Report-level metadata first; finding-level rows need separate reviewed scope.
- LLM extraction is required once implemented; deterministic-only output is not
  enough for publication.
- OCR remains optional and secondary to multimodal LLM extraction.
- No scheduled workflow or automated publication.
- No generated dataset artifacts committed to this builder repository.
- Publication remains PR-based and human-reviewed.

Pause point:

- Stop after documenting this plan and before Step 1 until the plan is reviewed.

## PR 7: LLM Extraction Contracts and Page Rendering

Tasks:

- Add ignored local page rendering outputs for downloaded PDFs. Done under
  `outputs/rendered_pages` by the inert `render-pages` command.
- Add schema/Pydantic contracts for LLM extraction candidates and diagnostics.
  Done in `collect.models`, `collect.llm_extract`, and
  `schemas/llm_extraction_candidate.schema.json`.
- Add schema/Pydantic contracts for rendered page artifacts, including render
  settings, page/crop identity, checksums, and coordinate conventions. Done in
  `collect.models`, `collect.pdf_render`, and
  `schemas/rendered_page_artifact.schema.json`.
- Add a required-but-inert-by-default `welfare-inspections extract-llm` command
  that can run in production when provider configuration is present. Done with
  default `dry-run`, explicit `mock`, and fail-closed `production` modes.
- Support embedded-text and multimodal page-image inputs. Done at the contract
  and plumbing layer through PR 4 text diagnostics and rendered artifact
  manifests.
- Store model name, prompt/template version, prompt input hash, input artifact
  hashes, page evidence, confidence, warnings, and validation status for every
  candidate. Done for valid candidate manifest records.
- Add a small reviewed LLM evaluation fixture set and an offline evaluator that
  compares candidate outputs to expected field values without calling a live
  provider. Done as a JSONL fixture contract and evaluator stub; no real
  reviewed fixture PDFs are committed.
- Add mocked/offline tests only; no live LLM calls in CI. Done with synthetic
  PDFs and JSONL mock provider responses.

Acceptance criteria:

- Production extraction fails closed if required LLM provider configuration is
  absent, unless explicitly run in dry-run/test mode. Done for missing
  `WELFARE_INSPECTIONS_LLM_PROVIDER` or `WELFARE_INSPECTIONS_LLM_MODEL`.
- LLM outputs are candidate manifests, not accepted canonical rows. Done.
- The evaluation report records model, prompt, renderer, schema, field-level
  coverage, field-level correctness, and regressions against the last accepted
  baseline. Done structurally; regression comparison is a stub with zero
  regressions until a baseline artifact exists.
- Publication and backfill planning treat failed LLM evaluation thresholds as a
  release blocker, even when schema validation passes.
- No prompt, response, image, or PDF artifacts are committed to the builder
  repository.

## PR 8: Candidate Reconciliation and Backfill

Tasks:

- Add reconciliation contracts for deterministic candidates, text-LLM
  candidates, multimodal-LLM candidates, OCR candidates if present, and
  existing canonical values.
- Add `welfare-inspections reconcile`.
- Add `welfare-inspections backfill` for versioned historical reprocessing.
- Preserve candidate conflicts and before/after canonical changes as
  diagnostics.
- Add filters such as `--source-document-id`, `--report-id`, `--since`,
  `--limit`, and `--dry-run`.

Acceptance criteria:

- Reconciliation never silently overwrites deterministic or previously
  published values.
- Material conflicts remain `needs_review` unless resolved by deterministic
  rules or explicit agreement thresholds; a reconciler LLM may propose a
  decision but must not be the only authority for auto-accepting a conflict.
- Backfills are idempotent, resumable, and produce reviewable change summaries.
- Canonical exports identify accepted extraction methods and candidate IDs.

## PR 9: Weekly Incremental Workflow and Artifact Upload

Tasks:

- Add a safe weekly workflow for discover/download/parse/render/LLM
  extraction/reconcile/export artifact generation.
- Reuse existing artifacts when source checksum and schema/model/prompt/render
  versions are unchanged.
- Upload diagnostics and review artifacts without publishing directly.
- Upload LLM evaluation reports with extraction and reconciliation artifacts.

Acceptance criteria:

- Workflow is credential-aware and fails clearly when required LLM credentials
  are missing.
- CI remains offline and deterministic.
- Weekly jobs do not run historical backfills implicitly.
- Data-repo publication remains blocked when required LLM evaluation, schema,
  reconciliation, or privacy gates fail.

## PR 10: Publish PR Flow Into Data Repo

Tasks:

- Implement publication automation that opens a PR into
  `AdanimInstitue/israel-welfare-inspection-dataset`.
- Include provenance, diagnostics summaries, LLM/model/prompt metadata,
  LLM evaluation reports, disclaimers, and release notes.
- Never push directly to data repo `main`.

Acceptance criteria:

- Publication is PR-based and human-reviewable.
- Generated artifacts remain out of the builder repository.
- Data-repo PRs clearly distinguish official source documents from unofficial
  derived data.
