# Publication review

## Define content separately from layout

Each study can require different tables. Keep three versioned files beside its notebook:

| File | Purpose | When a change needs participant data |
|---|---|---|
| `report-content.yaml` | Source fields and categorical, joint, binary or continuous summaries | New summaries must be calculated inside Workbench from the frozen matched participants. Existing fits can be reused. |
| `publication.yaml` | Required variables/statistics, model/condition pairs, sample sizes and diagnostic columns across the manuscript and supplement | Never for the coverage check itself. An unrun required analysis still needs to be performed. |
| `report-layout.yaml` | Sheets, selected variables/statistics/models, labels, precision and formatting | Never when the required aggregates already exist in the saved report. |

Do not change the scientific study definition for a formatting revision. A new source field or changed scientific definition requires the appropriate versioned extraction/analysis; adding a summary of an existing field does not.

```python
from aou_studies.report_content import ReportSpec

content = ReportSpec.load("report-content.yaml")
run.report(spec=content)
```

`ReportSpec.characteristics` maps stable identifiers to `fields`, `kind` and optional `label`. Multiple fields define a joint categorical summary, such as `[race, ethnicity]`. The source columns and matching remain unchanged. Optional `groups` contain a label and explicit ordered value tuples; overlapping groups and ambiguous displayed categories are rejected. Unlisted combinations, including missing values, remain separate. Participant and matched-set identifiers cannot be summarized.

Binary summaries require 0/1/missing values and report positive `n/N (%)` using the observed denominator, plus observed/missing counts. Categorical percentages use the full group's denominator and retain missing categories. Continuous summaries offer `mean_sd`, `median_iqr` and `missing`. Invalid numeric values fail rather than silently becoming normal or missing values. Small counts/complements and small missingness counts suppress the whole variable across both groups before persistence. Joint and marginal tables still require combined disclosure review.

The saved report records the content definition/hash and screened group sizes. It cannot reconstruct a new joint table from old marginal counts. Regenerate that report from frozen participant features inside Workbench; do not attempt to infer joint cells from published tables.

## Check complete publication coverage

```python
from aou_studies.coverage import PublicationSpec, check_coverage
from aou_studies.excel import WorkbookSpec, write_workbook
from aou_studies.reporting import Report

reports = {"main": Report.load("outputs/primary/review")}
layout = WorkbookSpec.load("report-layout.yaml")
requirements = PublicationSpec.load("publication.yaml")
coverage = check_coverage(reports, layout=layout, requirements=requirements)
display(coverage.table)
coverage.require_complete()
write_workbook("outputs/manuscript-tables.xlsx", reports,
               layout=layout, requirements=requirements)
```

Requirements are independent of the sheet arrangement. Select expected `study_id`/`protocol_version` for each named report, `characteristics` (variable to required summary names), `associations` (model to conditions), `group_sizes`, and `tables` (flow/balance to required columns). Association requirements default to condition, OR, CI, P and analyzed case/control/set sizes; primary results additionally require Holm P. An `OR (95% CI)` column supplies both estimate fields, and a condition fraction supplies its model-specific group denominator. Results and sample sizes may be on separate sheets; reconciliation uses original identifiers rather than visible labels. A sheet containing multiple models must display their identities.

Missing required content blocks export before replacing an existing workbook. Coverage records explicitly suppressed and non-estimable rows as accounted for; an absent/unrun model remains missing. A successful check establishes content coverage, not valid clinical findings, estimability or permission to export. Checked exports include a Coverage sheet and a requirements version/hash in Methods. Export without requirements remains available for exploratory or backward-compatible reports, but makes no coverage claim.

See [`examples/publication.yaml`](../examples/publication.yaml) and the different requirements/layout in [`examples/alternate_study/`](../examples/alternate_study/). The synthetic notebook executes both examples. Keep study-specific requirements and source manuscripts outside the public library.

`run.report()` automatically writes `review/tables.xlsx`, CSV/HTML tables, methods evidence, and `report.json`. The Excel workbook has participant characteristics, associations, participant flow, matching balance and methods sheets. Full fit diagnostics remain in the private run bundle. Percentages use explicit denominators; labels distinguish mean/SD from median and quartiles. Baseline significance tests are omitted.

## Format tables without repeating the analysis

The saved `report.json` contains screened aggregate inputs and display tables, with an integrity checksum. It contains no participant rows. Keep it inside Workbench for real studies. Change decimal places, titles, labels, ordering and sheet selection without credentials, database queries, matching or model execution:

```python
from aou_studies.reporting import Report
from aou_studies.excel import WorkbookSpec

report = Report.load("outputs/my-study/review")
layout = WorkbookSpec.load("examples/report-layout.yaml")
report.write_excel("outputs/my-study/manuscript-tables.xlsx", layout=layout)
```

Copy [the example layout](../examples/report-layout.yaml) for a paper. This configuration is separate from `StudySpec`, so changing presentation does not change the frozen scientific protocol. Run only the saved-report export cell for a formatting revision. Editing generated Excel cells does not update the notebook or saved results; regenerate from the layout to preserve reproducibility.

- `display`: decimal places for summaries, percentages, estimates and P values. Characteristic/condition order uses original variable keys. `display.labels` overrides variable or model names. Unlisted variables remain visible.
- `sheets`: ordered sheet definitions selecting `characteristics`, `associations`, `flow` or `balance`. `report` selects a named saved analysis when combining sensitivities. `models` selects exact model IDs for association sheets; unknown IDs fail.
- Characteristic sheets support `variables`, per-variable `summaries`, and `group_sizes: true` for headers. Selected summaries must exist and be appropriate for the variable. Selection happens after screening, so hiding a category or statistic cannot undo suppression. Requirements can demand summaries split across multiple sheets.
- `columns` and `column_labels`: choose/order columns and rename headers. Association columns include `OR`, `95% CI`, `OR (95% CI)`, nominal `P`, `Holm P`, model-specific sample/set sizes and condition fractions.
- `widths`, `header_groups`, `footnotes` and `orientation`: control presentation and printing. Grouped headers require contiguous, nonoverlapping selected columns. Headers freeze when scrolling is needed. Methods and review status are always included.

Combine multiple prespecified analyses in one workbook:

```python
from aou_studies.excel import write_workbook

reports = {
    "main": Report.load("outputs/primary/review"),
    "sensitivity": Report.load("outputs/sensitivity/review"),
}
write_workbook("outputs/paper-tables.xlsx", reports,
               layout=WorkbookSpec.load("paper-layout.yaml"))
```

Use `report: sensitivity` in the appropriate sheet definition. Report names and methods distinguish studies; the library does not pool them. Synthetic and real reports cannot be mixed. Each sensitivity's remaining review tables and private diagnostics belong in the whole-release review, even when the manuscript workbook selects only its associations.

Pandas and [XlsxWriter](https://xlsxwriter.readthedocs.io/working_with_pandas.html) handle Excel generation. Counts and individual estimates/P values are numeric cells with display formats; composite journal entries such as `n/N (%)` and `OR (95% CI)` are text. Display precision never feeds back into statistics. `p_decimals: 3` displays values below 0.001 as `<0.001` while retaining an available numeric P value. Missing, non-estimable and suppressed values stay distinct from zero. Formula-like text is literal; no formulas, macros, external links or hidden source sheets are generated. A failed Excel export leaves an existing workbook intact.

Snapshots are available starting in 0.2.0. Older runs need their report generated once with a compatible analysis environment; CSV strings alone cannot recover original precision. Checksums detect accidental modification, not malicious rewriting. A snapshot or workbook never authorizes data export.

## Scientific interpretation and disclosure

The primary matched analysis models sampled case status. Its odds ratios describe associations under the sampling design; they do not establish incidence, causal effects or treatment recommendations. Conditional Wald intervals are pointwise. Firth profile intervals belong to an unconditional adjusted sensitivity. Non-estimability remains visible even if another prespecified analysis gives a finite estimate.

The [All of Us policy](https://support.researchallofus.org/hc/article_attachments/36691474331668) prohibits disclosure of counts 1–20, directly or indirectly. Automated checks screen count/complement boundaries and conservatively suppress whole variable blocks across groups. Small supporting cells can also suppress model summaries. All outputs retain `requires_manual_disclosure_and_scientific_review` status.

These checks are not a proof of disclosure safety. Review totals, model sample sizes, missingness, overlapping subgroup tables, plots, text and previous public reports together. Small-count reconstruction can occur across otherwise acceptable individual tables. Do not export a real review bundle until that review is complete. Synthetic tables contain generated participants and have no such participant-data restriction.
