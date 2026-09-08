import numpy as np
import pandas as pd
import pytest
from aou_studies.analysis import fit_model, fit_models
from aou_studies.backends.r import run_r
from aou_studies.cohorts import build_cohorts
from aou_studies.contracts import valid_model_sets
from aou_studies.matching import match_groups
from aou_studies.specs import ModelSpec, MatchSpec


@pytest.fixture
def matched(features, study):
    return match_groups(build_cohorts(features, study), study.matching)


def test_match_constraints_and_determinism(features, study, matched):
    other = match_groups(build_cohorts(features.sample(frac=1, random_state=19), study), study.matching)
    pd.testing.assert_frame_equal(matched.members, other.members)
    assert matched.members.person_id.is_unique
    assert matched.members.match_difference_age.abs().max() <= 3
    sizes = matched.members.groupby("match_set_id").size()
    assert sizes.between(2, 3).all()
    assert matched.balance.variable.str.contains("age").any()
    for _, group in matched.members.groupby("match_set_id"):
        assert group[group.is_case == 0].weight.sum() == pytest.approx(1)
        assert group.sex_at_birth.nunique() == 1


def test_conditional_agrees_with_independent_r(matched):
    spec = ModelSpec(name="oracle", predictors=["condition"], covariates=["age"])
    result = fit_model(matched, spec, "condition")
    oracle = run_r(
        matched.members[["person_id", "match_set_id", "is_case", "condition", "age"]],
        {
            "mode": "conditional_reference",
            "terms": ["condition", "age"],
            "categorical": [],
            "max_iterations": 500,
        },
    )
    assert result["status"] == "estimated", result
    assert result["coefficient"] == pytest.approx(oracle["coefficients"]["condition"], abs=2e-4)
    assert result["standard_error"] == pytest.approx(oracle["se"]["condition"], abs=2e-4)


def test_firth_sparse_fit(matched):
    matched.members["sparse"] = 0
    matched.members.loc[matched.members.is_case.eq(1).idxmax(), "sparse"] = 1
    spec = ModelSpec(
        name="sparse",
        predictors=["sparse"],
        covariates=["age", "sex_at_birth"],
        categorical=["sex_at_birth"],
        method="firth",
    )
    result = fit_model(matched, spec, "sparse")
    assert result["status"] == "estimated", result
    assert np.isfinite([result["odds_ratio"], result["ci_lower"], result["ci_upper"]]).all()
    assert result["ci_method"] == "profile_penalized_likelihood"


def test_missing_case_removes_set(matched):
    df = matched.members.copy()
    target = df.index[df.is_case.eq(1)][0]
    setid = df.loc[target, "match_set_id"]
    df.loc[target, "bmi"] = np.nan
    selected, counts = valid_model_sets(df, ["bmi"])
    assert setid not in set(selected.match_set_id)
    assert counts["sets_removed"] == 1


def test_model_restriction_attrition_starts_from_original_matched_sample(matched):
    members = matched.members
    target = members.index[members.is_case.eq(1)][0]
    members["included"] = 1
    members.loc[target, "included"] = 0
    size = int(members.match_set_id.eq(members.loc[target, "match_set_id"]).sum())
    spec = ModelSpec(
        name="restricted",
        predictors=["condition"],
        covariates=["age"],
        restriction={"field": "included", "value": 1},
    )
    result = fit_model(matched, spec, "condition")
    assert result["rows_before"] == len(members)
    assert result["rows_removed_by_restriction"] == 1
    assert result["rows_removed"] == size
    assert result["sets_removed"] == 1


def test_constant_predictor_and_fixed_family(matched):
    matched.members["constant"] = 0
    model = ModelSpec(name="primary", predictors=["condition", "constant"], covariates=["age"], primary=True)
    results = fit_models(matched, (model,))
    assert results.family_size.eq(2).all()
    assert results.loc[1, "status"] == "non_estimable"
    assert pd.isna(results.loc[1, "p_holm"])
    assert results.loc[0, "p_holm"] == pytest.approx(min(1, 2 * results.loc[0, "p_value"]))


def test_propensity_alternative(features, study):
    spec = MatchSpec(method="propensity", distance=["age", "bmi"], exact=[], ratio=1)
    result = match_groups(build_cohorts(features, study), spec)
    assert result.members.groupby("match_set_id").size().eq(2).all()


def test_constant_exact_categories_do_not_break_balance(features, study):
    spec = MatchSpec(exact=["sex_at_birth", "race", "ethnicity"], calipers={"age": 3}, ratio=2)
    result = match_groups(build_cohorts(features, study), spec)
    constants = result.balance[result.balance.variable.isin(["race", "ethnicity"])]
    assert constants.Type.eq("Constant").all()
    assert constants["Diff.Adj"].isna().all()
    assert result.members.groupby("match_set_id").race.nunique().eq(1).all()


def test_cobalt_age_balance_uses_full_unmatched_pool(features, study, matched):
    cohorts = build_cohorts(features, study)
    sd = cohorts.cases.age.std(ddof=1)
    before = (cohorts.cases.age.mean() - cohorts.controls.age.mean()) / sd
    members = matched.members
    cases = members[members.is_case.eq(1)]
    controls = members[members.is_case.eq(0)]
    after = (
        np.average(cases.age, weights=cases.weight) - np.average(controls.age, weights=controls.weight)
    ) / sd
    row = matched.balance.set_index("variable").loc["age"]
    assert row["Diff.Un"] == pytest.approx(before, abs=1e-10)
    assert row["Diff.Adj"] == pytest.approx(after, abs=1e-10)


def test_public_example_meets_explicit_conditional_score_tolerance():
    from pathlib import Path
    from aou_studies.specs import StudySpec
    from aou_studies.synthetic import synthetic_features

    spec = StudySpec.load(Path(__file__).parents[1] / "examples/synthetic.yaml")
    matched = match_groups(build_cohorts(synthetic_features(spec), spec), spec.matching)
    result = fit_model(matched, spec.models[0], "example_condition")
    assert result["status"] == "estimated", result
    assert result["score_max"] <= 1e-3
