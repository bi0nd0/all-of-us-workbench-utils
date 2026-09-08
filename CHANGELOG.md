# Changelog

## 0.2.0 — 2026-09-08

`run.report()` now creates a formatted Excel workbook and an integrity-checked snapshot of screened aggregate results. Typed YAML layouts control labels, precision, ordering, sheet/model selection, grouped headers, widths and footnotes. Combine saved sensitivity reports into one workbook without querying or fitting again. XlsxWriter handles file generation; no hidden unsuppressed source cells or formulas are generated.

Preserve suppression when a characteristic category is absent in one group. Updated generic notebooks demonstrate automatic export and saved-report layout revisions. Excel changes do not alter extraction, matching or numerical model engines. Live v9 and author acceptance remain pending.

## 0.1.0 — 2026-09-08

Initial implementation: typed reusable study definitions, documented v9 OMOP extraction and Workbench context discovery, frozen provenance, configurable MatchIt matching, cobalt balance, conditional logistic and separate Firth sensitivity adapters, disclosure-review tables, and clean notebook examples.

Validated locally with generated data, an independent R conditional-logistic oracle, locked Python/R dependencies, and wheel installation. Live Workbench SQL, clinical phenotype, scientific protocol, and disclosure acceptance remain separate pending checks. This release contains no study findings or real participant data.
