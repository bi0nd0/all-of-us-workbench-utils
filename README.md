# All of Us Workbench utilities

Define a study once, extract its OMOP features, create disjoint study and control groups, match them, and generate reproducible analysis tables. The Python package is **`aou_studies`**; the distribution is **`all-of-us-workbench-utils`**.

This independent project is not endorsed by the All of Us Research Program. Public examples and tests use generated data. Real participant data, intermediate files, model diagnostics, and disclosure-review candidates belong inside the authorized Workbench.

## What it does

- Versioned Pydantic configurations describe eligibility, concepts and descendants, dated diagnosis criteria, survey/measurement features, comparison groups, matching, models, and report labels.
- `BigQuerySource` uses the official Google client and documented OMOP tables. It validates the release, tier, location, fields, types, and vocabulary before extraction. Queries use parameters and an explicit per-query billing cap.
- MatchIt handles nearest Mahalanobis or propensity matching, exact factors, calipers, ratios, and replacement. Independent checks verify membership, no-reuse rules, and calipers. cobalt provides balance diagnostics using the full matching pool and explicit retained-set weights.
- statsmodels conditional logistic regression preserves individual matched sets. R logistf provides an explicitly labeled **unconditional Firth sensitivity**, with prespecified covariate adjustment. Unsupported or unstable fits remain non-estimable; no silent estimator substitution.
- Tables derive percentages from numerical denominators, report missingness, omit baseline P tests, and keep prespecified hypotheses in their Holm family. Conservative small-cell screening produces review candidates, not export clearance.
- The notebook generates formatted Excel tables automatically. Reuse a YAML layout for journal headings, ordering, precision and sensitivity sheets; regenerate from saved aggregate reports without repeating queries or models.
- Frozen dates, configuration, source concepts, dependency versions, code hashes, memberships, query metadata, and cache hashes make revisions traceable.

The latest release verified on **2026-09-08** is **CDR v9**, with clinical cutoff **2025-01-01**. New studies should check the official [Data Dictionaries](https://support.researchallofus.org/hc/en-us/articles/360033200232-Data-Dictionaries). Existing analyses retain their pinned dataset and dates; the package never silently upgrades them.

## Run a synthetic example

The validated environment uses Python 3.12 and R 4.2.2. The development image restores the numerical dependencies from `requirements.lock` and `renv.lock`:

```sh
docker build -f Dockerfile.dev -t aou-studies-dev .
docker run --rm -v "$PWD:/workspace" aou-studies-dev sh -c '
  pip install --no-deps -e . &&
  aou-studies synthetic --config examples/synthetic.yaml --output outputs/example
'
```

Open `outputs/example/review/tables.xlsx` or `report.html`. They contain synthetic review tables. `notebooks/synthetic_study.ipynb` runs both the initial example and a second study with different eligibility, exclusion, distance method, and ratio, then demonstrates a custom manuscript layout.

```python
from pathlib import Path
from aou_studies import StudySpec
from aou_studies.runner import StudyRun
from aou_studies.synthetic import synthetic_features

study = StudySpec.load("examples/synthetic.yaml")
run = StudyRun(study, Path("outputs/my-study"), synthetic=True)
run.use_synthetic(synthetic_features(study))
run.build_groups()
run.match()       # Inspect retention, constraints, and balance before inference.
run.analyze()
run.report()
```

## Use All of Us data in Workbench

Install a verified release commit and the locked environment in a dedicated VM kernel. Follow [installation](docs/installation.md), then [dataset discovery and freezing](docs/workbench.md). Workbench 2.0 does not guarantee the legacy `WORKSPACE_CDR` variable. Resolve the resource with `wb resource resolve`, a documented `WORKBENCH_` variable, or explicit verified identifiers. The CDR source project and the workspace billing project have different roles.

```python
from aou_studies.context import discover_context
from aou_studies.source import BigQuerySource

context = discover_context(resource="R2025Q4R6", tier=study.tier)
context.require_release(pinned=study.dataset, cutoff=study.clinical_cutoff)
source = BigQuerySource(context, maximum_bytes_billed=10_000_000_000)
source.prepare(study)
sql, parameters = source.extraction_query(study)
estimate = source.query(sql, parameters, dry_run=True)
# Inspect estimates and approved definitions before running:
run = StudyRun(study, Path("cloud-local-study-output"))
run.extract(source)
```

Use a clinically reviewed study configuration with `notebooks/workbench_study.ipynb`; the public toy concepts are not clinical phenotypes. The per-query cap does not cap total session spending. Source metadata and feature queries also consume BigQuery resources.

## Design and limits

The current analysis interface supports binary condition associations in matched case-control studies. It does not implement a time-to-event model, causal identification strategy, validated EDS phenotype, or prevalence estimator. Matching with reused controls is available for design exploration, but current inference rejects reused participants because their dependence requires another variance/model strategy.

The extraction defaults to dated condition/visit evidence by the clinical cutoff, applies adult eligibility at that cutoff, and computes age separately at a literal reference date. Registered Tier date shifting affects interpretation. Missing smoking answers stay unknown; absence of a measurement is not a normal result. Numerical models use complete cases and discard sets without a case and control after exclusions.

Synthetic tests include a separate `survival::clogit` reference, deterministic row-shuffle checks, hand-calculated balance, sparse Firth fits, missing-case attrition, suppression boundaries, dictionary-contract checks, and fresh-kernel notebook execution. **Live Workbench SQL and scientific acceptance are separate requirements; local tests do not establish correct clinical results.** See the release validation record for the acceptance status of a particular version.

## Documentation

- [Configure another paper](docs/new-study.md) and [data contracts](docs/data-contracts.md)
- [Reporting and disclosure review](docs/reporting.md)
- [Engine choices](docs/adr/0001-engines.md) and [dependency credits](NOTICE.md)
- [Validation and release procedure](docs/validation.md)

MIT applies to this project's original source. Dependencies retain their own licenses. Cite the numerical engines used in your analysis as well as the pinned library release.
