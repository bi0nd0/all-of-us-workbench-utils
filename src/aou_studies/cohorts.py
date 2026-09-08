import pandas as pd
from .contracts import CohortResult, unique_people
from .errors import DataContractError
from .features import predicate_mask
from .specs import StudySpec


def build_cohorts(features: pd.DataFrame, spec: StudySpec) -> CohortResult:
    data = unique_people(features)
    reason = pd.Series("", index=data.index, dtype="object")
    for mask, label in [
        (data.age_at_cutoff.isna() | data.age.isna(), "missing_or_invalid_age"),
        (data.age_at_cutoff < spec.minimum_age, "below_minimum_age"),
        (data.ehr_record_count.fillna(0) <= 0, "no_dated_ehr_evidence"),
    ]:
        reason.loc[(reason == "") & mask.fillna(False)] = label
    if spec.maximum_age is not None:
        reason.loc[(reason == "") & (data.age_at_cutoff > spec.maximum_age)] = "above_maximum_age"
    if spec.eligibility:
        reason.loc[(reason == "") & ~predicate_mask(data, spec.eligibility)] = "study_eligibility"
    eligible = data[reason == ""].copy()
    case = predicate_mask(eligible, spec.case)
    control = predicate_mask(eligible, spec.control)
    if (case & control).any():
        raise DataContractError("Case and control definitions overlap; define mutually exclusive groups.")
    cases = eligible[case].assign(is_case=1)
    controls = eligible[control].assign(is_case=0)
    exclusions = data.loc[reason != "", ["person_id"]].assign(reason=reason[reason != ""])
    unclassified = eligible.loc[~case & ~control, ["person_id"]].assign(reason="neither_case_nor_control")
    exclusions = pd.concat([exclusions, unclassified], ignore_index=True)
    return CohortResult(
        eligible,
        cases,
        controls,
        exclusions,
        {
            "source": len(data),
            "eligible": len(eligible),
            "cases": len(cases),
            "controls": len(controls),
            "excluded": len(exclusions),
        },
    )
