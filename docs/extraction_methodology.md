# Extraction Methodology

The pipeline should start deterministic and auditable. V1 should not use opaque
LLM-based extraction because every parsed field needs traceability to the source
document, page, raw excerpt, extraction method, and warning status.

## PDF Extraction Layers

1. Use PyMuPDF as the default embedded-text extraction engine. PR 4 implements
   this through the manual `welfare-inspections parse` command.
2. Use pdfplumber for layout debugging and table extraction where useful.
3. Use pypdf for metadata, page count, and structural checks. PR 4 records
   these values in extraction diagnostics.
4. Use OCR only when embedded text is missing or poor.

## OCR Fallback

OCR should use OCRmyPDF/Tesseract when needed. Hebrew language data (`heb`) is
required for Hebrew reports, and Arabic (`ara`) may be needed if Arabic source
paths or reports are included. OCR output should be marked as OCR-derived and
should carry lower default confidence than clean embedded-text extraction.

OCR is not implemented in PR 4. Missing, unreadable, or image-only PDFs are
recorded as extraction diagnostics/warnings for later handling.

## Parser Contracts

Parser functions should return structured records plus diagnostics, not only
strings. PR 5 implements this for top-level report metadata with a deterministic
manual `parse-metadata` stage. A parsed field includes:

- canonical field name
- normalized value where applicable
- raw excerpt
- page number
- extraction method
- confidence
- warning codes/messages where applicable

The PR 5 metadata parser consumes only PR 4 extracted text files and text
extraction diagnostics. It does not inspect PDFs, collect from Gov.il, OCR,
parse finding-level rows, export canonical datasets, or publish data.

PR 6 consumes only PR 5 metadata JSONL and metadata parse diagnostics. It
validates report-level canonical rows, flattens raw and normalized values for
local CSV/JSONL export, and carries forward field evidence, page numbers,
warnings, parse diagnostics, source provenance, page counts, extraction status,
and extraction confidence. Validation failures are diagnostic records where
possible so one bad document does not block unrelated valid documents.

## Hebrew Normalization

The normalization layer should handle:

- Unicode normalization, preferably NFKC where appropriate
- zero-width characters
- non-breaking spaces
- punctuation variants
- Hebrew geresh/gershayim variants
- whitespace normalization
- common date formats in Hebrew reports
- preservation of canonical logical text order

Stored canonical values must not use visual bidi transformations.
`python-bidi` may be used only for debugging/display if needed.

PR 4 normalizes embedded text only after extraction. It removes zero-width and
directional control characters, normalizes common punctuation variants,
canonicalizes Hebrew geresh/gershayim in Hebrew abbreviations, and cleans
whitespace while preserving logical-order text as emitted by the extractor.

## Confidence and Warnings

Confidence should be conservative and explainable. Parsing uncertainty should
produce warning rows where possible instead of failing the whole pipeline. Hard
failures should be reserved for broken discovery/download inputs, unreadable
files, schema corruption, or conditions that make downstream data unsafe.
