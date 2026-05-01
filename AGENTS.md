# Agent Instructions

Keep this file concise and actionable. Put dynamic state in `.agent-plan.md`;
put project design detail in `docs/`.

## Commands

- Install dev environment: `python -m pip install -e ".[dev]"`
- Lint: `ruff check .`
- Test: `pytest`
- CI-equivalent local check: `ruff check . && pytest`
- CLI smoke check: `python -m welfare_inspections.cli --help`

## Git And PR Rules

- Default branch prefix: `codex/`.
- Work for PR #1 stays on `codex/pr1-planning-scaffold`.
- Use repo-specific git and GitHub MCP tools first.
- Use `git` or `gh` only when the required MCP action is unavailable or blocked.
- Feature/PR work is incomplete until a non-draft, labeled GitHub PR with a
  detailed description is open.
- Assign a relevant GitHub milestone when one exists.
- Do not commit secrets, credentials, tokens, or private local config.

## Repository Boundary

- This repo is the builder/code repo for an authorized public-data transparency
  project by Adanim Institute with the Ministry of Welfare and the Taub
  Institute.
- Keep source code, schemas, tests, configs, docs, CI, and small reviewed
  fixtures here.
- Do not commit generated datasets, release snapshots, downloaded PDFs from
  normal runs, or large binary artifacts here.
- Generated dataset outputs belong in
  `AdanimInstitue/israel-welfare-inspection-dataset`.
- Publication to the data repo must be PR-based; do not push directly to `main`.

## PR 1 Scope

- PR 1 is planning/scaffold only.
- Do not implement Gov.il collection, browser automation, PDF parsing, OCR,
  dataset exports, publication, scheduled build workflows, or live
  network-dependent tests.

## Source Collection Constraints

- Canonical source URL:
  `https://www.gov.il/he/departments/dynamiccollectors/molsa-supervision-frames-reports?skip=0`
- Investigate `skip=0` pagination before implementing source discovery.
- Prefer stable structured data access when available.
- Use browser-rendered collection only when necessary and appropriate.
- Use conservative request rates, clear logging, retries with backoff, and
  graceful failures.
- Do not access or attempt to access non-public information.

## Parsing And Data Rules

- Use both deterministic extraction and LLM-based extraction in normal
  production runs. The real source PDFs are not reliably parseable through
  embedded text alone, and the Ministry does not expect to change the PDF
  structure in the near term.
- LLM extraction must be auditable, schema-bound, and provenance-preserving.
  Do not accept opaque free-text LLM answers into canonical outputs.
- Multimodal LLM extraction should inspect rendered PDF pages when embedded
  text is insufficient, and every returned field must include source evidence
  such as page number, raw excerpt or visual locator, confidence, model name,
  prompt/template version, and validation status.
- Merge deterministic and LLM-derived candidates conservatively. Preserve both
  candidates when they conflict, emit diagnostics, and require validation before
  publication.
- Preserve provenance for every discovered document and every derived row.
- Treat parse failures as row-level warnings where possible.
- Keep Hebrew canonical text in logical order.
- Do not store visual bidi transformations in canonical data.
- Do not intentionally extract or publish sensitive personal data unless
  explicitly approved legally and ethically.

## Fixture Rules

- Small, clearly licensed, reviewable fixtures are allowed.
- Normal-run downloaded PDFs must not be committed.
- Real source PDF fixtures require explicit provenance/licensing notes in the PR
  that adds them.
- Golden expected outputs should be text-based where possible.

## Automation

- CI must stay offline and deterministic for PR 1.
- `pr-agent-context` is integrated through GitHub Actions with append-mode PR
  comments, raw `.coverage*` artifacts, debug artifacts, and refresh-mode reuse.
- Do not add weekly build or publish workflows in PR 1.
