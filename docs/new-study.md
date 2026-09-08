# Configure another paper

1. Copy a study configuration into a private study directory. Give it a new study ID and protocol version.
2. Freeze the dataset, tier, clinical cutoff and age reference. Validate all diagnosis codes against that release. Specify a scientific reason for each inclusion, exclusion, matching factor and covariate.
3. Define a common eligible population, mutually exclusive cases/controls, source features and missing-data rules. Controls must not be selected using the association results.
4. Choose exact factors, numeric calipers, distance variables, ratio and replacement. `nearest` delegates Mahalanobis matching to MatchIt; `propensity` delegates the score model and logit caliper. A greedy match is not a claim of global optimality.
5. Declare one primary model family, predictor list, adjustment, and prespecified sensitivities. Do not choose models by significance. A condition recorded in sampled controls does not imply population prevalence.
6. Run synthetic fixtures before cloud extraction, then inspect concepts, source coverage, missingness, matching and model diagnostics in Workbench.
7. Define `report-content.yaml` for study-specific summaries and `publication.yaml` for required manuscript/supplement content. Configure sheet layout separately in `report-layout.yaml`. Run the coverage check before exporting; every required variable/model must be represented, with accurate denominators and explicit unavailable states. See [reporting](reporting.md).
8. Preserve the frozen inputs and review all publication outputs together. A changed definition, release or numerical engine receives a new version.

`examples/alternate_study/study.yaml` demonstrates a different disease, control exclusion, age interval, distance method and 1:2 ratio without changing Python. Both public configurations contain toy concept IDs and can only demonstrate synthetic execution; they are not validated phenotypes.
