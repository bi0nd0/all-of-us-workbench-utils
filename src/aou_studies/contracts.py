"""Participant and matched-sample invariants, independent of the engine."""

from dataclasses import dataclass
import pandas as pd
from .errors import DataContractError


def unique_people(frame: pd.DataFrame) -> pd.DataFrame:
    if "person_id" not in frame or frame.person_id.isna().any():
        raise DataContractError("Every participant needs a non-null person_id.")
    result = frame.copy(deep=True)
    result["person_id"] = result.person_id.astype(str)
    if result.person_id.duplicated().any():
        raise DataContractError("Expected one row per participant; resolve duplicate IDs before proceeding.")
    return result


@dataclass
class CohortResult:
    eligible: pd.DataFrame
    cases: pd.DataFrame
    controls: pd.DataFrame
    exclusions: pd.DataFrame
    flow: dict[str, int]


@dataclass
class MatchResult:
    members: pd.DataFrame
    unmatched: pd.DataFrame
    balance: pd.DataFrame
    metadata: dict

    def validate(self, *, replacement=False):
        df = self.members
        if df.empty:
            raise DataContractError("No valid matched sets; inspect eligibility, calipers and missingness.")
        if df[["person_id", "match_set_id", "is_case"]].isna().any().any():
            raise DataContractError("Matched membership contains null identifiers or roles.")
        if not df.is_case.isin([0, 1]).all():
            raise DataContractError("Matched roles must be binary.")
        if df.duplicated(["match_set_id", "person_id"]).any():
            raise DataContractError("A participant is duplicated inside a matched set.")
        if not replacement and df.person_id.duplicated().any():
            raise DataContractError("A participant was reused despite matching without replacement.")
        sizes = df.groupby("match_set_id").is_case.agg(["sum", "count"])
        if not ((sizes["sum"] == 1) & (sizes["count"] >= 2)).all():
            raise DataContractError("Every set requires exactly one case and at least one control.")
        return self


def valid_model_sets(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    before_rows, before_sets = len(frame), frame.match_set_id.nunique()
    selected = frame.dropna(subset=columns).copy()
    counts = selected.groupby("match_set_id").is_case.agg(["sum", "count"])
    keep = counts.index[(counts["sum"] == 1) & (counts["count"] >= 2)]
    selected = selected[selected.match_set_id.isin(keep)].copy()
    return selected, {
        "rows_before": before_rows,
        "rows_analyzed": len(selected),
        "sets_before": int(before_sets),
        "sets_analyzed": int(len(keep)),
        "rows_removed": before_rows - len(selected),
        "sets_removed": int(before_sets - len(keep)),
    }
