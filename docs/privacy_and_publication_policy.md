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
