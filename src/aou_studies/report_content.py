"""Study-specific descriptive content, calculated before disclosure screening.

These specifications do not change cohorts, source features or fitted models.
"""

import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

from .errors import DataContractError

Summary = Literal["n_percent", "mean_sd", "median_iqr", "missing"]


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))


class CategoryGroup(ContentModel):
    label: str = Field(min_length=1)
    values: tuple[tuple[str | None, ...], ...] = Field(min_length=1)


class CharacteristicSpec(ContentModel):
    fields: tuple[str, ...] = Field(min_length=1)
    kind: Literal["categorical", "binary", "continuous"] = "categorical"
    label: str = ""
    groups: tuple[CategoryGroup, ...] = ()

    @model_validator(mode="after")
    def valid_content(self):
        if set(self.fields) & {"person_id", "match_set_id"}:
            raise ValueError(
                "Participant and matched-set identifiers cannot be descriptive categories or summaries."
            )
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("Select each source field only once.")
        if self.kind != "categorical" and (len(self.fields) != 1 or self.groups):
            raise ValueError("Binary and continuous summaries require one field and no category groups.")
        labels = [group.label for group in self.groups]
        values = [value for group in self.groups for value in group.values]
        if len(set(labels)) != len(labels) or len(set(values)) != len(values):
            raise ValueError("Category groups must have unique labels and nonoverlapping source values.")
        if any(len(value) != len(self.fields) for value in values):
            raise ValueError("Each category value must specify every source field in order.")
        return self


class ReportSpec(ContentModel):
    version: str = Field(min_length=1)
    characteristics: dict[str, CharacteristicSpec] = Field(min_length=1)


def default_report_spec(study):
    return ReportSpec(
        version="default-1",
        characteristics={
            **{v: CharacteristicSpec(fields=(v,)) for v in study.categorical},
            **{v: CharacteristicSpec(fields=(v,), kind="continuous") for v in study.continuous},
        },
    )


def summarize_characteristics(members: pd.DataFrame, spec: ReportSpec) -> pd.DataFrame:
    required = {field for item in spec.characteristics.values() for field in item.fields}
    if required - set(members):
        raise DataContractError(f"Missing descriptive source fields: {sorted(required - set(members))}")
    rows = []
    display_keys = {name: {} for name in spec.characteristics}
    for role, group in members.groupby("is_case"):
        group = group.drop_duplicates("person_id")
        for variable, item in spec.characteristics.items():
            base = dict(group="Cases" if role else "Controls", variable=variable, total=len(group))
            if item.kind == "categorical":
                values = group[list(item.fields)].astype("string")
                keys = [
                    tuple(None if pd.isna(v) else str(v) for v in row)
                    for row in values.itertuples(index=False, name=None)
                ]
                mapping = {value: g.label for g in item.groups for value in g.values}
                # Unlisted combinations remain separate. No participant disappears into an implicit Other.
                counts = {}
                for key in keys:
                    identity = ("group", mapping[key]) if key in mapping else ("raw", json.dumps(key))
                    label = mapping.get(key, " / ".join("Missing" if v is None else v for v in key))
                    previous = display_keys[variable].setdefault(label, identity)
                    if previous != identity:
                        raise DataContractError(
                            f"Ambiguous category label in {variable!r}; define explicit category groups to distinguish source values."
                        )
                    if identity not in counts:
                        counts[identity] = [label, 0]
                    counts[identity][1] += 1
                for identity, (label, n) in sorted(counts.items()):
                    rows.append(
                        dict(
                            **base,
                            level=label,
                            level_key=json.dumps(identity),
                            statistic="n_percent",
                            n=n,
                            denominator=len(group),
                            percent=100 * n / len(group),
                        )
                    )
            else:
                raw = group[item.fields[0]]
                values = pd.to_numeric(raw, errors="coerce")
                # Non-numeric present values are a data error, not a new missing-data convention.
                if (raw.notna() & values.isna()).any() or np.isinf(values.dropna()).any():
                    raise DataContractError(
                        f"Invalid numeric values in descriptive field {item.fields[0]!r}."
                    )
                values = values.dropna()
                missing = len(group) - len(values)
                if item.kind == "binary":
                    if not values.isin([0, 1]).all():
                        raise DataContractError(
                            f"Binary descriptive field {item.fields[0]!r} must contain 0, 1 or missing."
                        )
                    n = int(values.eq(1).sum())
                    rows.append(
                        dict(
                            **base,
                            level="",
                            statistic="binary",
                            n=n,
                            denominator=len(values),
                            missing=missing,
                            percent=100 * n / len(values) if len(values) else np.nan,
                        )
                    )
                else:
                    rows.append(
                        dict(
                            **base,
                            level="",
                            statistic="continuous",
                            n=len(values),
                            denominator=len(group),
                            missing=missing,
                            mean=values.mean(),
                            sd=values.std(ddof=1),
                            median=values.median(),
                            q1=values.quantile(0.25),
                            q3=values.quantile(0.75),
                        )
                    )
    return pd.DataFrame(rows)
