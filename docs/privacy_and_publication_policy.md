# Privacy and Publication Policy

The target public dataset license is CC BY 4.0 for the derived dataset artifacts,
with attribution to the Israeli Ministry of Welfare as the source publisher of
the original PDFs and clear attribution to the Adanim/Taub/builder pipeline for
derived parsed data.

This is an authorized public-data transparency project. It uses public
government publications and is not an attempt to access non-public information.

## Source vs. Derived Data

Official source PDFs remain the Ministry's publications. Parsed tables,
manifests, warnings, and exported datasets are unofficial derived data produced
by the builder pipeline and may contain parsing or OCR errors.

Publication materials should include:

- CC BY 4.0 target license notice for derived dataset outputs
- attribution to the Israeli Ministry of Welfare as source of original PDFs
- attribution to the derived-data pipeline
- OCR/parsing accuracy disclaimer
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

## Data Repository Placeholders

The paired data repository should eventually include `NOTICE.md`,
`DISCLAIMER.md`, `datapackage.json`, schema metadata, source manifests,
extraction run manifests, and release snapshots.
