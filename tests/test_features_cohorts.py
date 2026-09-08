from datetime import date
import pandas as pd
import pytest
from aou_studies.features import age_on, predicate_mask, reduce_survey, reduce_measurement
from aou_studies.specs import Predicate, SurveyFeature, MeasurementFeature
from aou_studies.cohorts import build_cohorts
from aou_studies.errors import DataContractError


def test_calendar_age():
    ages = age_on(pd.Series(["2000-09-07", "2000-09-08", "2000-02-29", None, "2027-01-01"]), date(2026, 9, 7))
    assert ages.iloc[:3].tolist() == [26, 25, 26]
    assert ages.iloc[3:].isna().all()
    assert age_on(pd.Series(["2000-02-29"]), date(2025, 2, 28)).iloc[0] == 24


def test_predicates_do_not_turn_unknown_into_control():
    d = pd.DataFrame({"flag": pd.Series([1, 0, None], dtype="Int64")})
    rule = Predicate(negate=Predicate(field="flag", value=1))
    assert predicate_mask(d, rule).tolist() == [False, True, False]
    rule = Predicate(
        all_of=(Predicate(field="flag", op="ge", value=0), Predicate(field="flag", op="lt", value=1))
    )
    assert predicate_mask(d, rule).tolist() == [False, True, False]


def test_survey_per_question_ties_unknown_and_numeric():
    d = pd.DataFrame(
        [
            ["a", 1, 10, "2024-01-01", None, None],
            ["a", 2, 99, "2024-01-01", None, "skip"],
            ["b", 1, 99, "2024-01-01", None, "refused"],
            ["c", 1, 10, "2024-01-01", None, None],
            ["c", 1, 11, "2024-01-01", None, None],
            ["d", 2, 99, "2024-01-01", None, "10"],
            ["a", 1, 11, "2026-01-01", None, None],
        ],
        columns=["person_id", "question_id", "answer_id", "event_date", "value_as_number", "value_as_string"],
    )
    s = SurveyFeature(positive={1: (10,)}, negative={1: (11,)}, numeric_positive_above={2: 0})
    result = reduce_survey(d, s, date(2025, 1, 1)).set_index("person_id").value.to_dict()
    assert result == {"a": "yes", "b": "unknown", "c": "conflict", "d": "yes"}
    assert len(d) == 7


def test_measurement_validation_and_ambiguous_ties():
    s = MeasurementFeature(
        concepts={"ids": [1], "domain": "Measurement"}, unit_codes=("kg/m2",), minimum=10, maximum=80
    )
    d = pd.DataFrame(
        [
            ["a", "2024-12-01", 25, "kg/m2"],
            ["a", "2024-12-02", 900, "kg/m2"],
            ["a", "2024-12-03", 30, "unknown"],
            ["b", "2024-12-01", 25, "kg/m2"],
            ["b", "2024-12-01", 26, "kg/m2"],
        ],
        columns=["person_id", "event_date", "value", "unit_code"],
    )
    r = reduce_measurement(d, s, date(2025, 1, 1)).set_index("person_id")
    assert r.loc["a", "value"] == 25 and pd.isna(r.loc["b", "value"])


def test_cohort_unique_common_eligibility(features, study):
    features.loc[0, "age_at_cutoff"] = 17
    features.loc[1, "ehr_record_count"] = 0
    features.loc[2, "age"] = pd.NA
    result = build_cohorts(features, study)
    assert len(result.cases) == 87 and len(result.controls) == 270
    assert set(result.exclusions.reason) == {
        "below_minimum_age",
        "no_dated_ehr_evidence",
        "missing_or_invalid_age",
    }
    assert "is_case" not in features
    with pytest.raises(DataContractError):
        build_cohorts(pd.concat([features, features.iloc[:1]]), study)
