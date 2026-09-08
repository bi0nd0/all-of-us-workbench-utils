# Find and freeze the All of Us dataset

As verified on **2026-09-08**, the official [Data Dictionaries](https://support.researchallofus.org/hc/en-us/articles/360033200232-Data-Dictionaries) list CDR **v9**, with clinical data cutoff **2025-01-01**:

| Tier | Dataset reference |
|---|---|
| Registered | `wb-affable-acorn-7941.R2025Q4R6` |
| Controlled | `wb-silky-artichoke-2408.C2025Q4R6` |

The source project stores the CDR. Your workspace billing project pays for queries and is a different identifier. Do not pass a billing account number to BigQuery's `project=` argument.

## Workspace resource setup

In **Resources → Data from catalog**, choose the authorized All of Us tier and the recommended collection version. Select the research dataset `R2025Q4R6` or `C2025Q4R6`. The `prep_` datasets and `cb_`/`ds_` Data Explorer tables are not the research extraction interface.

An existing workspace can be bound to an older collection version. The Workbench UI recommends duplicating it and selecting **Update version** during resource review. Preserve the old workspace until its required code/files and the new notebook are verified. Do not delete old cloud resources as part of package installation. A stopped VM can still incur disk-storage costs; billing is associated through its pod.

## Discover from a notebook

Workbench 2.0 does **not guarantee** the legacy globals `WORKSPACE_CDR` or `GOOGLE_PROJECT`. [Verily documents](https://support.workbench.verily.com/docs/guides/cli/workspace_context/) `GOOGLE_CLOUD_PROJECT` and resolved resource variables prefixed with `WORKBENCH_`. Never print the entire environment.

In a terminal attached to the intended workspace:

```sh
wb resource list
wb resource resolve --id=R2025Q4R6
wb workspace describe --format=json
```

Use the resource identifier actually returned by `wb resource list`; display names can differ. The [CLI guide](https://support.workbench.verily.com/docs/guides/cli/basic_usage/) describes these reference operations. Do not guess the project from the workspace name.

```python
from aou_studies.context import discover_context
from aou_studies.source import BigQuerySource
from aou_studies.specs import StudySpec

study = StudySpec.load('study.yaml')
context = discover_context(resource='R2025Q4R6', tier=study.tier)
context.require_release(pinned=study.dataset, cutoff=study.clinical_cutoff)
context.summary()  # only dataset, project, tier, location and resolution metadata
source = BigQuerySource(context, maximum_bytes_billed=10_000_000_000)
metadata = source.prepare(study)  # access, schema and vocabulary checks
sql, parameters = source.extraction_query(study)
source.query(sql, parameters, dry_run=True)  # estimated bytes; no participant result
```

If CLI discovery cannot parse a runtime response, provide the two values explicitly:

```python
context = discover_context(
    dataset=study.dataset,
    billing_project='your-workspace-project',
    tier=study.tier,
)
```

The resolver prefers explicit arguments, a named `wb` resource, then unambiguous documented resource globals. Legacy variables are compatibility inputs that still require release validation. Multiple CDR references or a stale default fail with instructions instead of silently selecting one. The runtime reads each required table's schema and verifies its actual location before extraction.

## Latest release versus reproducible revisions

A new study starts with the **latest verified** release in the package catalog. Check the official dictionary again when beginning another paper; the library does not scrape and silently upgrade clinical data. If a newer release exists, update and validate the catalog/schema contract before use. A frozen study writes the full dataset identifier, age date, clinical cutoff, resolved concept sets, configuration hash and environment to its run manifest. A different configuration requires a new protocol version and directory.

The age reference is a literal date, independent of the clinical cutoff. For the current EDS reanalysis it is **2026-09-07**. It must never be replaced by `today()`. Registered Tier dates are shifted; age is CDR-derived and is not an unshifted clinical age or evidence of survival to the reference date.

Only three recent CDR versions are retained by All of Us. A pin cannot prevent a dataset from being withdrawn or deprecated. Preserve permitted intermediates inside approved cloud storage and document any required re-extraction as a new analysis version.

## Run and review

Use a cloud-local run directory. Execute setup, dry run, extraction, cohorts, matching, model fitting and reporting as visible stages. Inspect balance and retention before association results. Do not call `.head()` on participant frames in shared notebook outputs. Review the entire proposed export for counts 1–20 and indirect reconstruction before downloading or publishing it. The library writes review candidates, never a declaration of disclosure clearance.
