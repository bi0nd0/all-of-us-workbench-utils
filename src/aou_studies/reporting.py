"""Numeric publication tables and conservative disclosure-review candidates.

Real outputs stay in Workbench. These checks do not certify cross-table safety.
"""

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .contracts import MatchResult
from .specs import StudySpec

SUPPRESSED = "Suppressed"


def small_count(value: int, threshold: int = 20) -> bool:
    return 0 < value <= threshold


def characteristics(matched: MatchResult, study: StudySpec) -> pd.DataFrame:
    """Raw participant summaries, with explicit denominators; balance is separately weighted."""
    rows = []
    for role, group in matched.members.groupby("is_case"):
        group = group.drop_duplicates("person_id")
        label = "Cases" if role else "Controls"
        for variable in study.categorical:
            values = group[variable].astype("string").fillna("Missing")
            for level, count in values.value_counts(dropna=False).sort_index().items():
                rows.append(
                    dict(
                        group=label,
                        variable=variable,
                        level=str(level),
                        statistic="n_percent",
                        n=int(count),
                        denominator=len(group),
                        percent=100 * count / len(group),
                    )
                )
        for variable in study.continuous:
            values = pd.to_numeric(group[variable], errors="coerce")
            values = values[np.isfinite(values)]
            rows.append(
                dict(
                    group=label,
                    variable=variable,
                    level="",
                    statistic="continuous",
                    n=len(values),
                    denominator=len(group),
                    missing=len(group) - len(values),
                    mean=values.mean(),
                    sd=values.std(ddof=1),
                    median=values.median(),
                    q1=values.quantile(0.25),
                    q3=values.quantile(0.75),
                )
            )
    return pd.DataFrame(rows)


def screened_characteristics(table: pd.DataFrame) -> pd.DataFrame:
    """Suppress the entire variable across both groups if a cell/complement is small."""
    result = table.copy().astype(object)
    for variable, rows in table.groupby("variable"):
        unsafe = any(small_count(int(v)) for v in rows.n) or any(
            small_count(int(n - v)) for n, v in zip(rows.denominator, rows.n)
        )
        if unsafe:
            cols = [c for c in table if c not in {"group", "variable", "level", "statistic"}]
            result.loc[rows.index, cols] = SUPPRESSED
    return result


def screened_associations(results: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    result = results.copy().astype(object)
    metadata = {
        "model",
        "predictor",
        "method",
        "formula",
        "primary",
        "family",
        "status",
        "reason",
        "ci_method",
        "test_method",
        "conditioned_out_terms",
        "warnings",
        "engine_version",
    }
    for i, row in results.iterrows():
        predictor = row.predictor
        tab = pd.crosstab(members.is_case, members[predictor]).reindex(
            index=[0, 1], columns=[0, 1], fill_value=0
        )
        counts = [
            row.get(c)
            for c in [
                "cases_analyzed",
                "controls_analyzed",
                "discordant_sets",
                "sets_removed",
                "rows_removed",
                "case_with_condition",
                "case_without_condition",
                "control_with_condition",
                "control_without_condition",
            ]
        ]
        unsafe = any(small_count(int(v)) for v in tab.to_numpy().flat) or any(
            small_count(int(v)) for v in counts if pd.notna(v)
        )
        if unsafe:
            for col in result.columns.difference(list(metadata)):
                result.loc[i, col] = SUPPRESSED
            result.loc[i, "status"] = "suppressed_pending_disclosure_review"
    return result


def publication_characteristics(table: pd.DataFrame, labels: dict) -> pd.DataFrame:
    def statistic(value):
        return "Not available" if pd.isna(value) else f"{value:.1f}"

    rows = []
    for row in table.itertuples(index=False):
        variable = labels.get(row.variable, row.variable.replace("_", " ").title())
        hidden = row.n == SUPPRESSED
        if row.statistic == "n_percent":
            rows.append(
                {
                    "Characteristic": f"{variable}: {row.level}",
                    "Group": row.group,
                    "Value": SUPPRESSED if hidden else f"{int(row.n)} ({row.percent:.1f}%)",
                }
            )
        else:
            for suffix, text in [
                ("Mean (SD)", SUPPRESSED if hidden else f"{statistic(row.mean)} ({statistic(row.sd)})"),
                (
                    "Median [Q1, Q3]",
                    SUPPRESSED
                    if hidden
                    else f"{statistic(row.median)} [{statistic(row.q1)}, {statistic(row.q3)}]",
                ),
                ("Observed / missing", SUPPRESSED if hidden else f"{int(row.n)} / {int(row.missing)}"),
            ]:
                rows.append({"Characteristic": f"{variable}: {suffix}", "Group": row.group, "Value": text})
    return (
        pd.DataFrame(rows)
        .pivot(index="Characteristic", columns="Group", values="Value")
        .fillna("0 (0.0%)")
        .reset_index()
        .rename_axis(None, axis=1)
    )


def publication_associations(table: pd.DataFrame, labels: dict) -> pd.DataFrame:
    def number(value, *, p=False):
        if isinstance(value, str):
            return value
        if pd.isna(value):
            return "Not estimable"
        if p and value < 0.001:
            return "<0.001"
        return f"{value:.3f}" if p else f"{value:.3g}"

    def fraction(n, total):
        if isinstance(n, str) or isinstance(total, str):
            return SUPPRESSED
        if pd.isna(n) or pd.isna(total) or total == 0:
            return "Not available"
        return f"{int(n)}/{int(total)} ({100 * n / total:.1f}%)"

    rows = []
    for _, row in table.iterrows():
        rows.append(
            {
                "Model": row.model.replace("_", " ").title(),
                "Condition": labels.get(row.predictor, row.predictor.replace("_", " ").title()),
                "Status": {
                    "estimated": "Estimated",
                    "non_estimable": "Not estimable",
                    "suppressed_pending_disclosure_review": "Suppressed",
                }.get(row.status, row.status),
                "OR": number(row.odds_ratio),
                "95% CI": (
                    number(row.ci_lower)
                    if number(row.ci_lower) in {SUPPRESSED, "Not estimable"}
                    else number(row.ci_lower) + " to " + number(row.ci_upper)
                ),
                "P": number(row.p_value, p=True),
                "Holm P": number(row.p_holm, p=True) if row.primary else "Not primary",
                "Cases": row.get("cases_analyzed"),
                "Controls": row.get("controls_analyzed"),
                "Matched sets": row.get("sets_analyzed"),
                "Condition in sampled cases": fraction(
                    row.get("case_with_condition"), row.get("cases_analyzed")
                ),
                "Condition in sampled controls": fraction(
                    row.get("control_with_condition"), row.get("controls_analyzed")
                ),
            }
        )
    return pd.DataFrame(rows)


@dataclass
class Report:
    tables: dict[str, pd.DataFrame]
    methods: str
    review_status: str = "requires_manual_disclosure_and_scientific_review"

    def write(self, directory: str | Path):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        sections = []
        for name, table in self.tables.items():
            table.to_csv(directory / f"{name}.csv", index=False)
            sections.append(
                f'<h2>{escape(name.replace("_", " ").title())}</h2><div class="table">'
                + table.to_html(index=False, escape=True, na_rep="Not available")
                + "</div>"
            )
        (directory / "methods.md").write_text(self.methods)
        (directory / "review.json").write_text(
            json.dumps(
                {
                    "status": self.review_status,
                    "policy": "AoU counts 1–20 inclusive; zero is allowed",
                    "instructions": "Review the complete proposed release, including text, totals, plots and other tables. "
                    "Keep inside Workbench until approved for export.",
                },
                indent=2,
            )
        )
        html = (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Study review tables</title>'
            "<style>body{font:15px system-ui;margin:2rem;color:#163044}h1,h2{font-weight:600}"
            ".table{overflow-x:auto;margin-bottom:2rem}table{border-collapse:collapse;font-size:13px}"
            "th,td{padding:8px;border:1px solid #c7d2dc;white-space:normal}th{background:#edf3f7}"
            "pre{white-space:pre-wrap;max-width:90ch}</style><h1>Study review tables</h1>"
            "<p>Draft for scientific and disclosure review. Automated screening is incomplete.</p>"
            + "".join(sections)
            + "<h2>Methods evidence</h2><pre>"
            + escape(self.methods)
            + "</pre></html>"
        )
        (directory / "report.html").write_text(html)


def build_report(matched: MatchResult, results: pd.DataFrame, flow: dict, study: StudySpec) -> Report:
    flow_table = pd.DataFrame([{"stage": k, "n": v} for k, v in flow.items()])
    counts = list(flow.values())
    if any(small_count(int(v)) for v in counts) or any(
        small_count(abs(int(a) - int(b))) for a in counts for b in counts
    ):
        flow_table["n"] = SUPPRESSED
    balance = matched.balance.drop(columns=["_row"], errors="ignore").copy()
    for col in ["Diff.Un", "Diff.Adj"]:
        balance[col] = pd.to_numeric(balance[col], errors="coerce").abs()
    if any(small_count(int(v)) for v in [matched.metadata["matched_cases"], matched.metadata["controls"]]):
        balance.loc[:, balance.columns != "variable"] = SUPPRESSED
    balance = balance.rename(
        columns={
            "variable": "Variable",
            "Type": "Type",
            "Diff.Un": "Absolute SMD before",
            "Diff.Adj": "Absolute SMD after",
            "V.Ratio.Un": "Variance ratio before",
            "V.Ratio.Adj": "Variance ratio after",
        }
    )
    balance = balance[["Variable", *[c for c in balance if c != "Variable"]]]
    flow_table["stage"] = flow_table.stage.str.replace("_", " ").str.capitalize()
    flow_table = flow_table.rename(columns={"stage": "Stage", "n": "Participants"})
    methods = (
        f"Study: {study.study_id}; protocol version: {study.version}.\n"
        f"Design: matched case-control analysis of recorded diagnoses. Sampled case status is the response.\n"
        f"Age reference: {study.age_reference_date}; clinical cutoff: {study.clinical_cutoff}; tier: {study.tier}.\n"
        f"Adult eligibility uses age at clinical cutoff. Age and dates are CDR-derived; Registered Tier dates are shifted.\n"
        f"Matching: MatchIt {study.matching.method}; exact {list(study.matching.exact)}; "
        f"raw calipers {study.matching.calipers}; up to {study.matching.ratio} controls, "
        f"minimum {study.matching.minimum_controls}; replacement {study.matching.replace}.\n"
        "Balance uses cobalt, the full eligible matching pool before matching, and retained-set weights afterward. "
        "Each case has weight one; its controls have total weight one. Characteristics use raw unique-person counts.\n"
        "No baseline significance tests. Continuous summaries are mean/SD and median/25th/75th percentiles.\n"
        "Conditional logistic regression uses one stratum per set, without descriptive matching weights. "
        "Pointwise 95% Wald intervals and Wald tests are distinguished from Firth profile-likelihood sensitivity intervals. "
        "The latter are unconditional, with explicit covariate adjustment. No causal or incidence interpretation.\n"
        "Complete-case restrictions remove incomplete rows and then sets lacking one case and at least one control. "
        "Non-estimable models retain their declared place in the primary Holm family (p=1 for adjustment, adjusted value hidden).\n"
        + "\n".join(
            f"{m.name}: {m.method}; each of {list(m.predictors)}; covariates {list(m.covariates)}; "
            f"primary={m.primary}; restriction={m.restriction.model_dump(mode='json') if m.restriction else None}."
            for m in study.models
        )
    )
    return Report(
        {
            "characteristics": publication_characteristics(
                screened_characteristics(characteristics(matched, study)), study.labels
            ),
            "associations": publication_associations(
                screened_associations(results, matched.members), study.labels
            ),
            "flow": flow_table,
            "balance": balance,
        },
        methods,
    )
