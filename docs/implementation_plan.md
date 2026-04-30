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

- Parse report-level fields from extracted text.
- Return structured values plus raw excerpts, page numbers, confidence, and
  warnings.
- Add golden tests for representative synthetic examples.

Acceptance criteria:

- Parser failures create warnings rather than crashing the full parse.
- Raw and normalized fields remain distinct.
- Docs/schema contracts are updated if fields change.

## PR 6: Schema Validation and Local Exports

Tasks:

- Expand JSON Schema and Pydantic contracts.
- Validate canonical rows.
- Export local CSV and JSONL outputs.
- Add tests for duplicate IDs, required fields, and malformed dates.

Acceptance criteria:

- Outputs are generated only into local ignored output directories.
- Builder repo still contains no generated dataset artifacts.
- Exported rows retain source provenance and parse diagnostics.
