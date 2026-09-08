# Validation and release

Local synthetic validation is distinct from live dataset and scientific acceptance. No synthetic result should be inserted into a manuscript as an All of Us finding.

## Reproduce local checks

Build `Dockerfile.dev`, then run this inside that image with only the public repository mounted:

```sh
ruff check src tests
ruff format --check src tests
python -m build
pip install --no-deps dist/all_of_us_workbench_utils-0.3.0-py3-none-any.whl
pytest -q
aou-studies synthetic --config examples/synthetic.yaml --output outputs/validation
```

Tests include hand-calculated feature cases, study predicates, unique membership, exact/caliper/no-reuse rules, shuffled-input determinism, conditional coefficient/SE agreement with R survival (absolute tolerance 0.0002), cobalt balance agreement (absolute tolerance 1e-10), sparse Firth intervals, fixed multiplicity families, missingness attrition, cache tampering, model-specific suppression, and a fresh-kernel public notebook. The synthetic survey benchmark in this folder measures a local transformation only; it is not a Workbench cost or full-population performance estimate.

## Live acceptance in an authorized workspace

1. Verify the package artifact SHA-256, full commit, Python/R versions, and pinned study specification.
2. Verify `wb` resource resolution and the billing project independently. Run schema/vocabulary preflight, then dry-run all planned extraction queries against the explicit byte cap.
3. Run `python scripts/cloud_sql_smoke.py --billing-project YOUR_WORKSPACE_PROJECT`. The harness replaces every CDR table with literal synthetic fixtures and checks dated condition counts/span, age boundaries, survey conflicts, units, ties, and missingness. It reads no CDR data and creates no persistent dataset, but uses the project's BigQuery query service and temporary results. This test does not verify real dataset access or metadata.
4. Run the approved study. Inspect source coverage, flow, matching attrition, exact factors, calipers, ratios, and balance before fitting associations.
5. Run every prespecified model and sensitivity, including non-estimable rows. Review formula, sample/set attrition, uncertainty, and multiplicity together.
6. Restart the kernel and rerun frozen permitted inputs. Compare membership and numerical-result hashes under the same environment; investigate any difference before accepting a revision.
7. Review the complete proposed aggregate export for scientific accuracy and direct or indirect disclosure. Private participant frames and full diagnostics remain inside Workbench.

## Release boundary

Review only this repository. Keep study manuscripts, reviewer correspondence, private clinical configurations, participant data, credentials, notebook outputs, and research run manifests outside Git. Publish a full commit, immutable-in-use tag, wheel, sdist, checksums, and `release-manifest.json` as release assets. The manifest records local checks and live acceptance separately. It lives with release assets because a commit cannot contain its own final commit hash.

The current implementation needs live Workbench acceptance. Synthetic tests, metadata documentation, workspace creation, and a running VM do not substitute for that acceptance.

Version 0.1.0 passed 40 tests in a clean wheel environment. Version 0.2.0 extends that environment with locked XlsxWriter 3.2.9 and passed 51 tests, including XLSX round trips, original numeric precision, suppression, literal formula-like text, invalid layouts, snapshot tampering and regeneration without statistical engines or BigQuery. The fresh synthetic notebook exercises a custom layout. A private, wholly synthetic EDS notebook also completed all cohort sensitivities and its combined workbook. Workbook sheets were rendered and inspected separately from numerical validation; native desktop Excel execution was not tested.

The normal synthetic example produced an estimable primary model. No live BigQuery test has run yet. A separate generated 10,000/50,000-person matching benchmark is recorded in `matching-benchmark.json`; its dimensions and limitations are part of that record.

Version 0.3.0 passed 75 tests from the installed wheel in the locked local environment. New checks independently calculate joint/binary/continuous summaries and cover missingness, small-count screening, category collisions, identifier rejection, stable-key coverage across split layouts, omitted variables/models/columns/reports/diagnostics, incorrect report identity, explicit non-estimability and atomic export rejection. Saved-report regeneration is tested with process execution and BigQuery query calls blocked. The public synthetic notebook executes two different reporting specifications and checked layouts.

A private fresh-kernel synthetic study also completed its main analysis and all three cohort sensitivities. Its final 17-sheet workbook accounts for 112 declared content items, including every configured model/condition pair, model-specific condition fractions, sample/set sizes and flow/balance diagnostics. Explicit cell formats preserve wrapping in readers that do not inherit column formatting. This evidence establishes reporting behavior; native desktop Excel and live clinical acceptance are still separate.
