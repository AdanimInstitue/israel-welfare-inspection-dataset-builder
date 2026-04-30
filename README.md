# Israel Welfare Inspection Dataset Builder

This repository contains the planned builder code, schemas, tests, documentation,
configuration, and automation for an authorized public-interest transparency
project led by Adanim Institute in collaboration with the Israeli Ministry of
Welfare and the Taub Institute.

The project goal is to build a reproducible Python ETL pipeline that converts
publicly published government PDF inspection and supervision reports into an
open-access research dataset.

Canonical source portal:
https://www.gov.il/he/departments/dynamiccollectors/molsa-supervision-frames-reports?skip=0

Paired data/output repository:
https://github.com/AdanimInstitue/israel-welfare-inspection-dataset

## Repository Boundary

This builder repository is for source code, parser logic, source discovery,
tests, schemas, configs, documentation, CI, and small fixtures only.

Generated dataset artifacts belong in the paired data repository, not here.

## Current Status

PR 1 establishes project design, specification, agent instructions, repository
conventions, a minimal Python package skeleton, placeholder schemas, tests, and
CI. It intentionally does not implement live Gov.il collection, browser
automation, PDF parsing, OCR, dataset publication, or generated artifacts.

## Documentation

- [Architecture](docs/architecture.md)
- [Source site notes](docs/source_site_notes.md)
- [Schema](docs/schema.md)
- [Extraction methodology](docs/extraction_methodology.md)
- [Data quality](docs/data_quality.md)
- [Privacy and publication policy](docs/privacy_and_publication_policy.md)
- [Operations](docs/operations.md)
- [Roadmap](docs/roadmap.md)
- [Implementation plan](docs/implementation_plan.md)

## Local Validation

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
```
