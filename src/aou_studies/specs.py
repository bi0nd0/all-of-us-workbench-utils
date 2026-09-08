"""Versioned, strict study specifications. No implicit dates or estimator selection."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ConceptSet(Spec):
    ids: tuple[int, ...] = ()
    codes: tuple[str, ...] = ()
    vocabulary: str = "SNOMED"
    domain: Literal["Condition", "Measurement", "Observation", "Drug", "Procedure"] = "Condition"
    descendants: bool = True
    exclude_ids: tuple[int, ...] = ()
    require_standard: bool = True

    @model_validator(mode="after")
    def nonempty(self):
        if not self.ids and not self.codes:
            raise ValueError("A concept set needs IDs or vocabulary codes; empty never means all concepts.")
        if any(v <= 0 for v in self.ids + self.exclude_ids):
            raise ValueError("Concept identifiers must be positive integers.")
        return self


class ConditionFeature(Spec):
    concepts: ConceptSet
    min_distinct_dates: int = Field(default=1, ge=1)
    min_span_days: int = Field(default=0, ge=0)
    lookback_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def condition_domain(self):
        if self.concepts.domain != "Condition":
            raise ValueError("Condition features require the Condition domain.")
        return self


class MeasurementFeature(Spec):
    concepts: ConceptSet
    unit_codes: tuple[str, ...]
    unit_vocabulary: str = "UCUM"
    minimum: float
    maximum: float
    lookback_days: int = Field(default=365, ge=0)

    @model_validator(mode="after")
    def valid_measurement(self):
        if self.concepts.domain != "Measurement" or not self.unit_codes or self.minimum >= self.maximum:
            raise ValueError("Measurement requires its domain, explicit units and minimum < maximum.")
        return self


class SurveyFeature(Spec):
    """Categorical evidence resolved across latest-per-question observations.

    Answer mappings are question-specific; positive/negative conflict is explicit.
    Numeric questions contribute positive evidence only above `numeric_positive_above`.
    """

    positive: dict[int, tuple[int, ...]] = Field(default_factory=dict)
    negative: dict[int, tuple[int, ...]] = Field(default_factory=dict)
    numeric_positive_above: dict[int, float] = Field(default_factory=dict)
    positive_codes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    negative_codes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    numeric_positive_codes: dict[str, float] = Field(default_factory=dict)
    vocabulary: str = "PPI"
    positive_label: str = "yes"
    negative_label: str = "no"
    unknown_label: str = "unknown"
    conflict_label: str = "conflict"

    @model_validator(mode="after")
    def mapping(self):
        if not any(
            [
                self.positive,
                self.negative,
                self.numeric_positive_above,
                self.positive_codes,
                self.negative_codes,
                self.numeric_positive_codes,
            ]
        ):
            raise ValueError("Provide explicit survey question/answer rules.")
        for q, values in self.positive.items():
            if set(values) & set(self.negative.get(q, ())):
                raise ValueError("An answer cannot be both positive and negative.")
        for q, values in self.positive_codes.items():
            if set(v.lower() for v in values) & set(v.lower() for v in self.negative_codes.get(q, ())):
                raise ValueError("An answer code cannot be both positive and negative.")
        if len({self.positive_label, self.negative_label, self.unknown_label, self.conflict_label}) != 4:
            raise ValueError("Survey evidence labels must be distinct.")
        return self


class Predicate(Spec):
    field: Name | None = None
    op: Literal["eq", "ne", "ge", "gt", "le", "lt", "in", "not_in", "is_missing", "not_missing"] = "eq"
    value: str | float | int | bool | tuple[str | float | int | bool, ...] | None = None
    all_of: tuple[Predicate, ...] = ()
    any_of: tuple[Predicate, ...] = ()
    negate: Predicate | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if sum((self.field is not None, bool(self.all_of), bool(self.any_of), self.negate is not None)) != 1:
            raise ValueError("A predicate must have exactly one field/all_of/any_of/negate expression.")
        if self.field and self.op in {"in", "not_in"} and not isinstance(self.value, tuple):
            raise ValueError("Membership predicates need a sequence of values.")
        return self


class MatchSpec(Spec):
    method: Literal["nearest", "propensity"] = "nearest"
    exact: tuple[Name, ...] = ()
    calipers: dict[Name, float] = Field(default_factory=dict)
    distance: tuple[Name, ...] = ("age",)
    categorical: tuple[Name, ...] = ()
    ratio: int = Field(default=4, ge=1, le=20)
    minimum_controls: int = Field(default=1, ge=1)
    replace: bool = False
    seed: int = Field(default=20260907, ge=0)
    propensity_caliper: float = Field(default=0.2, gt=0)

    @model_validator(mode="after")
    def matching_rules(self):
        if self.minimum_controls > self.ratio or any(v < 0 for v in self.calipers.values()):
            raise ValueError("Invalid ratio or negative caliper.")
        if not self.distance:
            raise ValueError("Declare distance variables explicitly.")
        if set(self.calipers) & set(self.categorical):
            raise ValueError("Raw calipers require numeric variables.")
        return self


class ModelSpec(Spec):
    name: Name
    predictors: tuple[Name, ...]
    covariates: tuple[Name, ...] = ()
    categorical: tuple[Name, ...] = ()
    method: Literal["conditional", "firth"] = "conditional"
    primary: bool = False
    family: str = "primary"
    restriction: Predicate | None = None
    max_iterations: int = Field(default=500, ge=20)

    @model_validator(mode="after")
    def model_rules(self):
        if not self.predictors or len(set(self.predictors)) != len(self.predictors):
            raise ValueError("Declare unique predictors.")
        if set(self.predictors) & set(self.covariates):
            raise ValueError("Predictors cannot also be covariates.")
        if len(set(self.covariates)) != len(self.covariates) or not set(self.categorical).issubset(
            self.covariates
        ):
            raise ValueError("Covariates must be unique; categorical terms must be declared covariates.")
        if self.primary and self.method != "conditional":
            raise ValueError("Primary matched analysis must use the supported conditional engine.")
        return self


class StudySpec(Spec):
    study_id: Name
    version: str
    design: Literal["matched_case_control"] = "matched_case_control"
    age_reference_date: date
    clinical_cutoff: date
    tier: Literal["registered", "controlled"] = "registered"
    dataset: str | None = None
    minimum_age: int = Field(default=18, ge=0)
    maximum_age: int | None = Field(default=None, ge=0)
    eligibility: Predicate | None = None
    case: Predicate
    control: Predicate
    conditions: dict[Name, ConditionFeature]
    measurements: dict[Name, MeasurementFeature] = Field(default_factory=dict)
    surveys: dict[Name, SurveyFeature] = Field(default_factory=dict)
    matching: MatchSpec
    models: tuple[ModelSpec, ...]
    labels: dict[str, str] = Field(default_factory=dict)
    categorical: tuple[Name, ...] = ("sex_at_birth", "race", "ethnicity")
    continuous: tuple[Name, ...] = ("age",)

    @model_validator(mode="after")
    def coherent(self):
        if self.clinical_cutoff > self.age_reference_date:
            raise ValueError("Clinical cutoff cannot follow the frozen reference date.")
        if self.maximum_age is not None and self.maximum_age < self.minimum_age:
            raise ValueError("Invalid age interval.")
        names = list(self.conditions) + list(self.measurements) + list(self.surveys)
        if not self.conditions:
            raise ValueError("Declare at least one condition feature.")
        if len(names) != len(set(names)):
            raise ValueError("Feature names must be unique across sources.")
        reserved = {
            "person_id",
            "is_case",
            "age",
            "age_at_cutoff",
            "birth_date",
            "sex_at_birth",
            "race",
            "ethnicity",
            "ehr_days",
            "ehr_record_count",
            "match_set_id",
            "weight",
        }
        if reserved & set(names):
            raise ValueError("A feature name conflicts with a reserved participant/matching field.")
        if sum(m.primary for m in self.models) != 1:
            raise ValueError("Declare exactly one primary model family.")
        if len({m.name for m in self.models}) != len(self.models):
            raise ValueError("Model names must be unique.")
        return self

    @classmethod
    def load(cls, path: str | Path) -> StudySpec:
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))
