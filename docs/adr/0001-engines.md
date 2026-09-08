# ADR 0001: Use existing extraction, matching and inference engines

Accepted for the initial implementation on 2026-09-08.

Use Google's BigQuery Python SDK for parameterized extraction, pandas for reductions, Pydantic for specifications, MatchIt for matching, cobalt for standardized balance diagnostics, statsmodels for conditional logistic regression, and logistf for the separate Firth sensitivity. R survival is an independent reference oracle. The adapters handle study contracts and provenance, not new numerical algorithms.

The synthetic contract suite demonstrated exact/caliper matching, partial matching, input-order reproducibility, propensity matching, sparse Firth estimation and agreement between statsmodels and `survival::clogit`. Compare conditional coefficients and standard errors within an absolute tolerance of 0.0002. Exact likelihood in clogit does not mean its confidence intervals are exact small-sample intervals.

Calling R as a subprocess makes engine versions, temporary files and failure handling explicit and avoids adding an in-process R binding. Temporary participant CSVs exist only inside the authorized runtime and are removed when the call ends. An engine failure never invokes an alternative estimator automatically.

R adds installation cost. BLAS/LAPACK development libraries are required for current MatchIt/logistf compilation. Explicit package/version checks catch partial R installation failures that otherwise return a zero shell status. `renv.lock` records the tested dependency closure; Python versions are recorded separately.

Own source is MIT licensed. Third-party packages retain their own licenses, including GPL-licensed R dependencies. They are installed as separate dependencies; their implementations are not copied into this repository. The release retains dependency lockfiles and citations to the original packages.

## Optimizer configuration compatibility

The pinned statsmodels 0.14.6 conditional-model wrapper accepts `**kwargs` but does not forward solver options to its parent fitter. Its default scaled gradient stopping rule can leave an absolute score above this library's acceptance threshold. The adapter therefore calls the existing public `LikelihoodModel.fit` on the `ConditionalLogit` instance, using BFGS with `gtol=1e-8`. It preserves the same conditional likelihood, score, Hessian, and statsmodels solver; no solver is reimplemented. Convergence metadata, score, information, and warnings must all pass. A synthetic regression fixture and independent R oracle cover this path. Recheck this compatibility choice before upgrading statsmodels.

Sources: [conditional-model source](https://www.statsmodels.org/stable/_modules/statsmodels/discrete/conditional_models.html), [LikelihoodModel.fit](https://www.statsmodels.org/stable/dev/generated/statsmodels.base.model.LikelihoodModel.fit.html), and the inspected installed 0.14.6 source on 2026-09-08.
