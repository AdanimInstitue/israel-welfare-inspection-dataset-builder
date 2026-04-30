# Extraction Methodology

The pipeline should start deterministic and auditable. V1 should not use opaque
LLM-based extraction because every parsed field needs traceability to the source
document, page, raw excerpt, extraction method, and warning status.

## PDF Extraction Layers

1. Use PyMuPDF as the default embedded-text extraction engine.
2. Use pdfplumber for layout debugging and table extraction where useful.
3. Use pypdf for metadata, page count, and structural checks.
4. Use OCR only when embedded text is missing or poor.

## OCR Fallback

OCR should use OCRmyPDF/Tesseract when needed. Hebrew language data (`heb`) is
required for Hebrew reports, and Arabic (`ara`) may be needed if Arabic source
paths or reports are included. OCR output should be marked as OCR-derived and
should carry lower default confidence than clean embedded-text extraction.

## Parser Contracts

Future parser functions should return structured records plus diagnostics, not
only strings. A parsed field should include:

- canonical field name
- normalized value where applicable
- raw excerpt
- page number
- extraction method
- confidence
- warning codes/messages where applicable

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

## Confidence and Warnings

Confidence should be conservative and explainable. Parsing uncertainty should
produce warning rows where possible instead of failing the whole pipeline. Hard
failures should be reserved for broken discovery/download inputs, unreadable
files, schema corruption, or conditions that make downstream data unsafe.
