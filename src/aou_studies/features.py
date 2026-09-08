"""Deterministic feature reduction on synthetic or authorized Workbench frames."""

from datetime import date, timedelta
import numpy as np
import pandas as pd
from .specs import Predicate, SurveyFeature, MeasurementFeature
from .errors import DataContractError


def age_on(birth_dates: pd.Series, reference: date) -> pd.Series:
    dob = pd.to_datetime(birth_dates, errors="coerce")
    age = (
        reference.year
        - dob.dt.year
        - (
            (dob.dt.month > reference.month)
            | ((dob.dt.month == reference.month) & (dob.dt.day > reference.day))
        ).astype(int)
    )
    return age.where(dob.notna() & (dob.dt.date <= reference)).astype("Int64")


def predicate_mask(frame: pd.DataFrame, rule: Predicate) -> pd.Series:
    if rule.all_of:
        return pd.concat([predicate_mask(frame, r) for r in rule.all_of], axis=1).all(axis=1)
    if rule.any_of:
        return pd.concat([predicate_mask(frame, r) for r in rule.any_of], axis=1).any(axis=1)
    if rule.negate:
        # Unknowns must not become eligible just because a predicate is negated.
        return ~_nullable_predicate(frame, rule.negate).fillna(True)
    return _nullable_predicate(frame, rule).fillna(False).astype(bool)


def _nullable_predicate(frame, rule):
    if rule.field is None:
        if rule.all_of:
            values = [_nullable_predicate(frame, x) for x in rule.all_of]
            result = values[0]
            for val in values[1:]:
                result = result & val
            return result
        if rule.any_of:
            values = [_nullable_predicate(frame, x) for x in rule.any_of]
            result = values[0]
            for val in values[1:]:
                result = result | val
            return result
        return ~_nullable_predicate(frame, rule.negate)
    if rule.field not in frame:
        raise DataContractError(f"Unknown predicate field: {rule.field}")
    s = frame[rule.field]
    if rule.op == "is_missing":
        return s.isna().astype("boolean")
    if rule.op == "not_missing":
        return s.notna().astype("boolean")
    operations = {
        "eq": s.eq,
        "ne": s.ne,
        "ge": s.ge,
        "gt": s.gt,
        "le": s.le,
        "lt": s.lt,
        "in": s.isin,
        "not_in": lambda v: ~s.isin(v),
    }
    return operations[rule.op](rule.value).astype("boolean").mask(s.isna())


def reduce_survey(events: pd.DataFrame, spec: SurveyFeature, cutoff: date) -> pd.DataFrame:
    """Use all ties on the latest date per question; conflicting evidence remains visible."""
    columns = ["person_id", "question_id", "answer_id", "event_date", "value_as_number", "value_as_string"]
    if not set(columns).issubset(events):
        raise DataContractError("Survey event columns do not match the documented observation mapping.")
    df = events.copy()
    df["event_date"] = pd.to_datetime(df.event_date, errors="coerce")
    questions = set(spec.positive) | set(spec.negative) | set(spec.numeric_positive_above)
    df = df[df.question_id.isin(questions) & (df.event_date.dt.date <= cutoff)]
    latest = df.groupby(["person_id", "question_id"]).event_date.transform("max")
    df = df[df.event_date == latest].drop_duplicates()
    if df.empty:
        return pd.DataFrame(columns=["person_id", "value"])
    pairs = pd.MultiIndex.from_frame(df[["question_id", "answer_id"]])
    positives = [(q, answer) for q, answers in spec.positive.items() for answer in answers]
    negatives = [(q, answer) for q, answers in spec.negative.items() for answer in answers]
    values = pd.to_numeric(df.value_as_number, errors="coerce").fillna(
        pd.to_numeric(df.value_as_string, errors="coerce")
    )
    thresholds = df.question_id.map(spec.numeric_positive_above)
    df["_positive"] = pairs.isin(positives) | (np.isfinite(values) & values.gt(thresholds)).fillna(False)
    df["_negative"] = pairs.isin(negatives)
    evidence = df.groupby("person_id", sort=True)[["_positive", "_negative"]].any()
    evidence["value"] = np.select(
        [evidence._positive & evidence._negative, evidence._positive, evidence._negative],
        [spec.conflict_label, spec.positive_label, spec.negative_label],
        default=spec.unknown_label,
    )
    result = evidence[["value"]].reset_index()
    result["person_id"] = result.person_id.astype(str)
    return result


def reduce_measurement(events: pd.DataFrame, spec: MeasurementFeature, cutoff: date) -> pd.DataFrame:
    df = events.copy()
    df["event_date"] = pd.to_datetime(df.event_date, errors="coerce")
    df["value"] = pd.to_numeric(df.value, errors="coerce")
    start = pd.Timestamp(cutoff - timedelta(days=spec.lookback_days))
    df = df[
        df.event_date.between(start, pd.Timestamp(cutoff))
        & df.unit_code.isin(spec.unit_codes)
        & df.value.between(spec.minimum, spec.maximum)
        & np.isfinite(df.value)
    ]
    latest = df.groupby("person_id").event_date.transform("max")
    df = df[df.event_date == latest]
    # Different same-day values are ambiguous: do not pick whichever row happens to arrive first.
    result = df.groupby("person_id").value.agg(["first", "nunique"]).reset_index()
    result["value"] = result["first"].where(result["nunique"] == 1)
    result["person_id"] = result.person_id.astype(str)
    return result[["person_id", "value"]]
