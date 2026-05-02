# Source Site Notes

Canonical starting URL:

https://www.gov.il/he/departments/dynamiccollectors/molsa-supervision-frames-reports?skip=0

The source portal is a Gov.il dynamic collector page used by the Israeli
Ministry of Welfare and Social Affairs / Ministry of Welfare and Social
Security to publish public inspection and supervision reports for out-of-home
welfare facilities, including hostels, residential centers, and care facilities.

PR 2 adds an inert-by-default discovery prototype. PR 3 adds an
inert-by-default downloader that consumes the discovery manifest and downloads
only the public `pdf_url` values when manually invoked. PR 4 adds an
inert-by-default embedded-text extractor that consumes the download manifest and
local PDF paths. PR 5 adds an inert-by-default metadata parser that consumes
only PR 4 extracted text and diagnostics. PR 6 adds local schema validation and
exports. These stages are tested only with mocked or synthetic inputs.

PR 12 reframes the source work around a report index layer first. The next
implementation should collect the report-card facts visible on the Gov.il
listing page before downloading or parsing PDFs. The source-observed fields are
`שם מסגרת`, `סוג מסגרת`, `סמל מסגרת`, `מינהל`, `מחוז`, and `תאריך ביצוע`, with
source links, PDF links where visible, pagination metadata, and collection-run
provenance preserved as companion metadata.

Real-source inspection after PR 6 showed two practical source constraints:

- Some environments receive Cloudflare 403 or HTML responses from direct HTTP
  requests even though the public page loads in a normal browser.
- Embedded text extraction succeeds technically, but deterministic parsing of
  real report metadata is not reliable enough for publication.

Future source and extraction work should therefore support browser-rendered
public collection/download paths and required LLM extraction over rendered PDF
pages, while preserving all provenance and avoiding private browser state.

## Discovery Strategy

1. Inspect the Gov.il dynamic collector page starting at `skip=0`.
2. Prefer a stable structured data endpoint if the dynamic collector uses one.
3. Use `httpx` against a structured endpoint when possible.
4. Use server HTML parsing when records are present in server output.
5. Use browser-rendered public collection when direct HTTP access returns
   blocked or incomplete responses and this approach is appropriate for the
   public portal.
6. Preserve source provenance for every discovered report.

The PR 2 implementation parses Gov.il-like HTML for public PDF/file links,
detects the embedded Gov.il DynamicCollector configuration when the server HTML
is only a client-rendered shell, posts conservative page requests to the public
structured endpoint, derives deterministic source document IDs, and writes a
source manifest JSONL plus diagnostics sidecar. It does not download PDFs.

## Pagination Questions

The `skip=0` query parameter is mirrored into the structured endpoint request as
both `From` and `QueryFilters.skip.Query`. The observed page size is 10.

The prototype iterates `skip` conservatively by a configurable page size and
stops on an empty page, repeated page signature, no new records, or max pages.
The default command starts at `skip=0`, uses a page size of 10, and limits a run
to five pages unless overridden.

Future source-discovery work should still verify that all records are reachable
by iterating `skip=0`, `skip=10`, `skip=20`, etc. through the structured
endpoint, and should compare the endpoint total with emitted manifest rows.

## Discovery Mechanisms to Record

Future implementation should explicitly document whether records are discovered
through:

- rendered HTML
- a Gov.il structured data endpoint
- pagination links
- browser-rendered DOM inspection

Any access limitations observed during implementation should be recorded here.
The collector must not attempt to bypass access controls or access non-public
information.

Browser-mediated collection should use a temporary profile whenever possible and
must not rely on personal logged-in cookies for public source data. If a manual
browser session is used for diagnosis, diagnostics should record that method
without storing unrelated browser state.

Current local observation from this implementation environment on 2026-04-30:
plain `curl` requests to the canonical page can receive a Cloudflare HTTP 403,
but the prototype's clear research user agent received HTTP 200 for the public
collector shell. The server HTML is an Angular dynamic collector shell, not a
page with rendered result records. The shell embeds:

- dynamic template ID:
  `48cbb17e-017a-45a5-8001-fd8a54253529`
- client ID: `149a5bad-edde-49a6-9fb9-188bd17d4788`
- structured endpoint: `https://www.gov.il/he/api/DynamicCollector`
- observed page size: `10`

The structured endpoint returned public JSON results containing report file
metadata. The resulting PDF URLs use this pattern:

```text
https://www.gov.il/BlobFolder/dynamiccollectorresultitem/{UrlName}/he/{FileName}
```

A one-page manual probe from this environment wrote 10 manifest rows and stopped
with `stop_reason=max_pages`. Diagnostics recorded HTTP 200 for both the shell
page and the structured endpoint. The generated manifest and diagnostics remain
ignored local outputs.

Manual local probe command:

```bash
welfare-inspections discover \
  --output outputs/source_manifest.jsonl \
  --diagnostics outputs/discovery_diagnostics.json
```

Manual PR 3 download command:

```bash
welfare-inspections download \
  --source-manifest outputs/source_manifest.jsonl \
  --output-manifest outputs/download_manifest.jsonl \
  --diagnostics outputs/download_diagnostics.json \
  --download-dir downloads/pdfs
```

Generated outputs and downloaded PDFs are ignored by git and should be inspected
locally before being used by later PRs. The downloader records per-record HTTP
diagnostics, blocked responses, checksum mismatches, and non-fatal download
failures without parsing or OCRing PDFs.

Manual PR 4 embedded-text extraction command:

```bash
welfare-inspections parse \
  --source-manifest outputs/download_manifest.jsonl \
  --text-output-dir outputs/extracted_text \
  --diagnostics outputs/text_extraction_diagnostics.json
```

The parser reads only the PR 3 manifest and local PDF paths, extracts embedded
text, writes ignored local text outputs, and preserves source/download
provenance in diagnostics. It does not collect from Gov.il, download PDFs, OCR,
parse report-level metadata, export datasets, or publish data.

Manual PR 5 metadata parse command:

```bash
welfare-inspections parse-metadata \
  --text-diagnostics outputs/text_extraction_diagnostics.json \
  --output outputs/report_metadata.jsonl \
  --diagnostics outputs/metadata_parse_diagnostics.json
```

The metadata parser reads only the PR 4 diagnostics and local extracted text
files. It preserves source provenance in report metadata rows and diagnostics,
and it does not collect from Gov.il, download PDFs, OCR, parse finding-level
rows, export final datasets, publish data, or contact the network.

## Required Source Record

Every discovered report should eventually have a raw source record containing:

- `source_document_id`
- `govil_item_slug`, if available
- `govil_item_url`
- `pdf_url`
- `title`
- `language_path`, such as `/he/` or `/ar/` if available
- `source_published_at`, if available
- `source_updated_at`, if available
- `discovered_at`
- `downloaded_at`, after download
- HTTP status
- response headers where relevant
- `pdf_sha256`, after download
- local path if stored
- collector version or package version

## Operational Constraints

This is an authorized public-data collection workflow for public government
publications. It should be implemented respectfully, reproducibly, and
conservatively with low request rates, clear logging, retries with backoff,
graceful handling of temporary failures, and no aggressive concurrency.
