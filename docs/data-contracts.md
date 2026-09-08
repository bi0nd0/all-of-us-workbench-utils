# Data contracts and API

`StudySpec.load(path)` validates a YAML/JSON study definition. Unknown fields, moving dates, empty concept sets and incompatible model roles fail early. Configuration is separate from the library: no EDS concept IDs or scientific defaults are embedded in its core.

`BigQuerySource.prepare(study)` validates context and schema, resolves vocabulary seeds/descendants and survey source codes, and returns metadata. `extract(study)` uses parameterized BigQuery jobs with dry-run and billed-byte limits and returns one feature row per participant. All real results remain in Workbench.

`build_cohorts(features, study)` applies common adult/EHR eligibility before disjoint case/control predicates. Predicates compose `all_of`, `any_of`, `negate` and comparisons. Missing values do not become eligible through negation. Source counts refer to people with dated visit or condition evidence, not every person in the entire CDR. `ehr_days` is the span between recorded events, not continuous enrollment or guaranteed observation.

`match_groups(cohorts, match_spec)` returns a `MatchResult`: membership, unmatched case reasons, balance and engine metadata. One case and the declared number of controls form each set. Matching without replacement requires global participant uniqueness. Caliper differences, control order and descriptive weights are retained. Input order is canonicalized by string participant ID; shuffled input has identical output. Reused controls are allowed by the matching interface but rejected by the currently supported inference interface.

`fit_model(matched, model, predictor)` and `fit_models(matched, models)` return numeric results with explicit estimator, formula, case/control/set attrition, convergence and non-estimability reasons. The condition association interface currently accepts binary predictors. Exact-match invariant terms are conditioned out and recorded; rank deficiencies or unstable fits are not replaced by another test.

`StudyRun` exposes these stages and saves frozen configuration, content hashes and private artifacts. `sensitivity_spec` requires a distinct version. Changed eligibility or case definitions require building and matching a new cohort. Model-specific restrictions preserve only sets with one case and at least one control.

Feature reductions use dates at or before the frozen cutoff. Surveys select the latest eligible date per question, preserve conflicting same-date answers, then combine positive/negative evidence across questions. Source-code mappings resolve case-insensitively in the declared vocabulary and reject ambiguous or missing codes. Negative evidence must be explicitly mapped; absent/skipped survey data remains unknown.

Measurements require declared concept(s), units, valid range and lookback. The latest valid date supplies the value. Conflicting values on that date become missing; the implementation does not arbitrarily select one. Diagnosis flags use distinct dates and optionally a minimum span. No event after the clinical cutoff affects these features.

Caches include configuration, dataset, schema, resolved concepts and environment. Content hashes detect changed parquet contents. The source and all derived participant-level artifacts remain cloud-local; public manifests must not contain participant identifiers or restricted paths.
