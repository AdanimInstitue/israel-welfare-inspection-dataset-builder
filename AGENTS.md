# Agent Instructions

Treat this repository as the builder/code repository for an authorized
public-data transparency project conducted by Adanim Institute, a
semi-governmental public-policy research institute, in collaboration with the
Israeli Ministry of Welfare and the Taub Institute.

## Boundaries

- Preserve the builder/data repository split.
- Keep ETL source code, parser logic, discovery logic, tests, schemas, configs,
  documentation, CI, and small fixtures in this builder repository.
- Do not commit generated datasets, release snapshots, downloaded PDFs, or large
  binary artifacts to this builder repository.
- Generated open dataset artifacts belong in
  `AdanimInstitue/israel-welfare-inspection-dataset`.
- Do not publish directly to the data repository from local scripts. Future
  publication must use a PR-based flow.
- Do not add secrets, credentials, tokens, or private configuration to the repo.

## Source Collection

- The canonical source portal starts at
  `https://www.gov.il/he/departments/dynamiccollectors/molsa-supervision-frames-reports?skip=0`.
- Investigate Gov.il `skip` pagination before implementing source discovery.
- Prefer stable structured data access when available.
- Use browser-rendered collection only when appropriate and necessary for the
  public Gov.il portal.
- Respect the public portal's operational constraints: conservative request
  rates, no aggressive concurrency, clear logging, retries with backoff, and
  graceful failures.
- Do not attempt to access non-public information or bypass access controls.
- Preserve source provenance for every discovered document and every derived row.

## Parsing and Data Contracts

- Prefer deterministic, auditable parsing before AI or LLM extraction.
- Do not introduce opaque LLM-based extraction for v1.
- Every parsed field should eventually be traceable to source document, page,
  raw excerpt, extraction method, confidence, and warning status.
- Treat parsing failures as row-level warnings where possible.
- Keep Hebrew canonical text in logical order.
- Avoid visual bidi transformations in stored data. Debug/display tools may use
  bidi rendering separately.
- Avoid extracting or publishing sensitive personal data unless explicitly,
  legally, and ethically approved.

## Publication and Licensing

- Maintain CC BY 4.0 publication target requirements for the derived dataset.
- Preserve attribution to the Israeli Ministry of Welfare as source publisher of
  the original PDFs.
- Distinguish official source PDFs from unofficial parsed derived data.
- Include OCR/parsing accuracy and privacy disclaimers in publication materials.

## Engineering Standards

- Keep functions small and typed.
- Use Pydantic models for future external/internal contracts.
- Use structured logging for future pipeline stages.
- Use deterministic IDs where possible.
- Avoid hidden global state and hard-coded local absolute paths.
- Make the pipeline resumable and idempotent.
- Prefer JSONL manifests for append/readability.
- Update docs when contracts change.
- Keep CI passing.

## PR Completion

Feature work and PR work are incomplete until a properly labeled, non-draft
GitHub PR with a detailed description is open. When a relevant GitHub milestone
exists, assign it before handoff. Use repo-specific git and GitHub MCP tools
first, and use CLI fallbacks only for actions unsupported by the MCPs.
