"""Small adapter and invariant checks around MatchIt, not another matching algorithm."""

import numpy as np
import pandas as pd
from .backends.r import run_r
from .contracts import CohortResult, MatchResult, unique_people
from .errors import DataContractError
from .specs import MatchSpec


def match_groups(cohorts: CohortResult, spec: MatchSpec) -> MatchResult:
    cases, controls = unique_people(cohorts.cases), unique_people(cohorts.controls)
    if set(cases.person_id) & set(controls.person_id):
        raise DataContractError("Cases and controls overlap.")
    combined = pd.concat([cases, controls], ignore_index=True)
    columns = sorted(set(spec.exact) | set(spec.distance) | set(spec.calipers))
    missing = set(columns) - set(combined.columns)
    if missing:
        raise DataContractError(f"Matching columns are missing: {sorted(missing)}")
    numeric = set(spec.distance) | set(spec.calipers)
    numeric -= set(spec.exact) | set(spec.categorical)
    for column in numeric:
        values = pd.to_numeric(combined[column], errors="coerce")
        combined[column] = values.where(np.isfinite(values))
    valid = combined[columns].notna().all(axis=1)
    excluded = combined.loc[~valid & (combined.is_case == 1), ["person_id"]].assign(
        reason="missing_match_feature"
    )
    # Stable identifiers are strings: preserve precision across Python/R and select reproducibly.
    data = combined[valid].sort_values(["is_case", "person_id"], ascending=[False, True], kind="stable")
    if data.is_case.nunique() != 2:
        raise DataContractError("Both eligible cases and controls are required for matching.")
    result = run_r(
        data[["person_id", "is_case", *columns]], {"mode": "match", "spec": spec.model_dump(mode="json")}
    )
    members = pd.DataFrame(result["members"])
    members["person_id"] = members.person_id.astype(str)
    members = members.merge(data.drop(columns="is_case"), on="person_id", how="left", validate="many_to_one")
    matched_cases = set(members.loc[members.is_case == 1, "person_id"])
    unmatched = data.loc[(data.is_case == 1) & ~data.person_id.isin(matched_cases), ["person_id"]]
    unmatched = pd.concat(
        [excluded, unmatched.assign(reason="no_sufficient_eligible_controls")], ignore_index=True
    )
    validate_criteria(members, spec)
    for column in spec.calipers:
        case_values = members.loc[members.is_case == 1].set_index("match_set_id")[column]
        members[f"match_difference_{column}"] = members[column] - members.match_set_id.map(case_values)
    return MatchResult(
        members,
        unmatched,
        pd.DataFrame(result["balance"]),
        {
            "engine": "MatchIt",
            "versions": result["versions"],
            "runtime": result["runtime"],
            "spec": spec.model_dump(mode="json"),
            "warning": result["engine_warning"],
            "matched_cases": len(matched_cases),
            "controls": int((members.is_case == 0).sum()),
            "missing_case_match_features": int((~valid & combined.is_case.eq(1)).sum()),
            "missing_control_match_features": int((~valid & combined.is_case.eq(0)).sum()),
            "unmatched_cases": len(unmatched),
            "achieved_ratios": members.groupby("match_set_id")
            .size()
            .sub(1)
            .value_counts()
            .sort_index()
            .to_dict(),
        },
    ).validate(replacement=spec.replace)


def validate_criteria(members: pd.DataFrame, spec: MatchSpec):
    for _, group in members.groupby("match_set_id", sort=False):
        cases, controls = group[group.is_case == 1], group[group.is_case == 0]
        if len(cases) != 1 or not spec.minimum_controls <= len(controls) <= spec.ratio:
            raise DataContractError("Backend returned a set outside the declared ratio policy.")
        case = cases.iloc[0]
        for column in spec.exact:
            if not controls[column].eq(case[column]).all():
                raise DataContractError(f"Backend violated exact matching on {column}.")
        for column, caliper in spec.calipers.items():
            distances = (pd.to_numeric(controls[column]) - float(case[column])).abs()
            if (distances > caliper + 1e-10).any():
                raise DataContractError(f"Backend violated the {column} caliper.")
