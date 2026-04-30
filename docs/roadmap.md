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

## PR 7: Weekly Workflow and Artifact Upload

Add safe scheduled build automation and upload artifacts for review.

## PR 8: Publish PR Flow Into Data Repo

Implement publication automation that opens a PR into the paired data repository
instead of pushing directly to main.

## PR 9+: Detailed Findings Extraction, OCR Fallback, Quality Dashboards

Expand finding-level extraction, OCR fallback, quality reports, parse warning
dashboards, and broader fixture coverage.
