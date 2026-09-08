# Publication review

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
