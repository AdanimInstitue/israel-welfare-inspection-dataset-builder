# Source Site Notes

Canonical starting URL:

https://www.gov.il/he/departments/dynamiccollectors/molsa-supervision-frames-reports?skip=0

The source portal is a Gov.il dynamic collector page used by the Israeli
Ministry of Welfare and Social Affairs / Ministry of Welfare and Social
Security to publish public inspection and supervision reports for out-of-home
welfare facilities, including hostels, residential centers, and care facilities.

PR 2 adds an inert-by-default discovery prototype. It is run only by manual
local command and is tested only with mocked HTML/HTTP responses.

## Discovery Strategy

1. Inspect the Gov.il dynamic collector page starting at `skip=0`.
2. Prefer a stable structured data endpoint if the dynamic collector uses one.
3. Use `httpx` against a structured endpoint when possible.
4. Use server HTML parsing when records are present in server output.
5. Use Playwright only as a browser-rendered fallback when records are available
   only after client-side rendering and this approach is appropriate for the
   public portal.
6. Preserve source provenance for every discovered report.

The PR 2 implementation parses Gov.il-like HTML for public PDF/file links,
derives deterministic source document IDs, and writes a source manifest JSONL
plus diagnostics sidecar. It does not download PDFs.

## Pagination Questions

The `skip=0` query parameter appears likely to be a pagination or offset
parameter and must be investigated before collection is implemented.

Future source-discovery work must answer:

- Does `skip=0` represent the first page?
- What page size is used?
- Do later pages use `skip=10`, `skip=20`, etc.?
- Is pagination reflected in HTML, browser state, or an underlying structured
  data request?
- Are all records reachable by iterating `skip`, or is there a separate Gov.il
  dynamic collector data source?

The prototype iterates `skip` conservatively by a configurable page size and
stops on an empty page, repeated page signature, no new records, or max pages.
The default command starts at `skip=0`, uses a page size of 10, and limits a run
to five pages unless overridden.

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

Current local observation from this implementation environment: direct `curl`
requests to the canonical page returned HTTP 403 with a Cloudflare block page on
2026-04-30. The prototype records blocked responses in diagnostics instead of
attempting to bypass the block.

Manual local probe command:

```bash
welfare-inspections discover \
  --output outputs/source_manifest.jsonl \
  --diagnostics outputs/discovery_diagnostics.json
```

Generated outputs are ignored by git and should be inspected locally before
being used by later PRs.

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
