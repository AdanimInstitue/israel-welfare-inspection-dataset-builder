# Privacy and Publication Policy

The target public dataset license is CC BY 4.0 for the derived dataset artifacts,
with attribution to the Israeli Ministry of Welfare as the source publisher of
the original PDFs and clear attribution to the Adanim/Taub/builder pipeline for
derived parsed data.

This is an authorized public-data transparency project. It uses public
government publications and is not an attempt to access non-public information.

## Source vs. Derived Data

Official source PDFs remain the Ministry's publications. Parsed tables,
manifests, warnings, LLM extraction candidates, reconciliation decisions, and
exported datasets are unofficial derived data produced by the builder pipeline
and may contain parsing, OCR, or LLM errors.

Publication materials should include:

- CC BY 4.0 target license notice for derived dataset outputs
- attribution to the Israeli Ministry of Welfare as source of original PDFs
- attribution to the derived-data pipeline
- OCR/parsing accuracy disclaimer
- LLM extraction disclaimer when LLM-derived fields are published
- warning that parsed data may contain errors
- distinction between official source documents and parsed derived data
- provenance and reproducibility notes

## Privacy Caution

No personal or sensitive data should be intentionally extracted into public
structured fields unless explicitly approved legally and ethically. The pipeline
should avoid storing unnecessary personal data in structured outputs.

If sensitive personal data is accidentally extracted, it should not be published
without review. Future publication workflows should include checks for privacy
risk under Israeli privacy law and GDPR-style data minimization principles.

LLM prompts and provider payloads should use only public source documents and
pipeline-generated artifacts needed for extraction. Do not send secrets,
private browser state, personal local files, unrelated cookies, or private local
configuration to an LLM provider. Prompt and response logs must be stored only
when they are safe to retain and useful for audit; otherwise store hashes,
model/prompt versions, and structured extraction diagnostics.

PR 7 keeps prompt/provider payload handling local and inert: dry-run mode emits
no provider payloads, mock mode reads local JSONL fixtures, and production mode
fails closed without explicit provider/model configuration. Generated images,
prompt payloads, raw responses, candidates, diagnostics, and evaluation reports
remain under ignored local output directories until separately reviewed.

PR 9 weekly review-artifact uploads intentionally exclude downloaded PDFs,
rendered page images, prompt payloads, raw provider responses, generated report
exports, and candidate payload manifests. Uploaded artifacts are limited to
explicit source/download/render manifests, diagnostics, LLM evaluation reports,
reconciliation diagnostics, dry-run backfill summaries, and run summaries
needed for review. The workflow does not publish data to the paired repository.

PR 10 publication planning keeps the same boundary for actual publication.
`publish-plan` prepares a data-repo PR body, release notes, and diagnostics
summary that state the Ministry PDFs are official source documents and the
parsed dataset is unofficial derived data. It excludes downloaded PDFs,
rendered page images, prompt payloads, raw LLM responses, unreviewed large
artifacts, finding-level rows, and suspected sensitive personal data from the
planned data-repo file set. Production planning fails closed unless reviewed
inputs, explicit human approval, clear quality gates, and GitHub credentials
are present.

PR 11 finding extraction remains review-only. `extract-findings` may create
local finding candidate and diagnostics sidecars from dry-run or mock fixtures,
but those sidecars are not publication inputs. Finding rows, especially
free-text findings and recommendations, require later privacy review,
canonical schema work, quality gates, and explicit publication scope before
they can enter the paired data repository.

## Data Repository Placeholders

The paired data repository should eventually include `NOTICE.md`,
`DISCLAIMER.md`, `datapackage.json`, schema metadata, source manifests,
extraction run manifests, and release snapshots.

## v0 Preview Publication Policy

A first manual dataset publication may be prepared as a `v0 preview` before
scheduled build and publication automation exists. This preview should be
report-metadata-first, PR-based into
`AdanimInstitue/israel-welfare-inspection-dataset`, and reviewed before merge.

The preview PR should include:

- clear `v0 preview` language
- source provenance and run dates
- diagnostics summary and known limitations
- model and prompt provenance for any LLM-derived fields
- CC BY 4.0 target license notice for derived outputs
- attribution to the Ministry of Welfare as source publisher
- attribution to the Adanim/Taub/builder pipeline for derived parsed data
- disclaimer that parsed data is unofficial and may contain errors

Do not publish downloaded PDFs, unreviewed large artifacts, finding-level rows,
or any suspected personal/sensitive data in the v0 preview. LLM-derived fields
must be clearly marked through provenance and reconciliation metadata.

The PR 10 planner may prepare report-level publication PR metadata and command
plans, but it does not authorize automatic publication. Human reviewers must
inspect the generated PR text, release notes, diagnostics, and intended
data-repo file set before any paired data-repo PR is opened.
