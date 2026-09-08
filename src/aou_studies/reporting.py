"""Numeric publication tables and conservative disclosure-review candidates.

Real outputs stay in Workbench. These checks do not certify cross-table safety.
"""

from dataclasses import dataclass, field
from html import escape
import json
from pathlib import Path
import pandas as pd
from .contracts import MatchResult
from .specs import StudySpec
from .errors import DataContractError
from .provenance import digest
from .report_content import ReportSpec, default_report_spec, summarize_characteristics

SUPPRESSED = "Suppressed"


def small_count(value: int, threshold: int = 20) -> bool:
    return 0 < value <= threshold


def characteristics(matched: MatchResult, study: StudySpec, spec: ReportSpec | None = None) -> pd.DataFrame:
    """Raw participant summaries, with explicit denominators; balance is separately weighted."""
    return summarize_characteristics(matched.members, spec or default_report_spec(study))


def screened_characteristics(table: pd.DataFrame) -> pd.DataFrame:
    """Suppress the entire variable across both groups if a cell/complement is small."""
    result = table.copy().astype(object)
    for variable, rows in table.groupby("variable"):
        unsafe = any(small_count(int(v)) for v in rows.n) or any(
            small_count(int(n - v)) for n, v in zip(rows.denominator, rows.n)
        )
        if "missing" in rows:
            unsafe |= any(small_count(int(v)) for v in rows.missing.dropna())
        if unsafe:
            cols = [c for c in table if c not in {"group", "variable", "level", "level_key", "statistic"}]
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


def publication_characteristics(
    table: pd.DataFrame, labels: dict, *, decimals=1, percent_decimals=1, summaries=None
) -> pd.DataFrame:
    def statistic(value):
        return "Not available" if pd.isna(value) else f"{value:.{decimals}f}"

    rows = {}
    identities = []
    summaries = summaries or {}
    missing = set(summaries) - set(table.variable)
    if missing:
        raise DataContractError(f"Unknown characteristic summary selection: {sorted(missing)}")
    for row in table.itertuples(index=False):
        variable = labels.get(row.variable, row.variable.replace("_", " ").title())
        hidden = row.n == SUPPRESSED
        if row.statistic == "n_percent":
            entries = [
                (
                    "n_percent",
                    str(row.level),
                    SUPPRESSED if hidden else f"{int(row.n)} ({row.percent:.{percent_decimals}f}%)",
                )
            ]
        elif row.statistic == "binary":
            fraction = (
                SUPPRESSED
                if hidden
                else (
                    "Not available"
                    if row.denominator == 0
                    else f"{int(row.n)}/{int(row.denominator)} ({row.percent:.{percent_decimals}f}%)"
                )
            )
            entries = [
                ("n_percent", "Recorded, n/N (%)", fraction),
                (
                    "missing",
                    "Observed / missing",
                    SUPPRESSED if hidden else f"{int(row.denominator)} / {int(row.missing)}",
                ),
            ]
        else:
            entries = [
                (
                    "mean_sd",
                    "Mean (SD)",
                    SUPPRESSED if hidden else f"{statistic(row.mean)} ({statistic(row.sd)})",
                ),
                (
                    "median_iqr",
                    "Median [Q1, Q3]",
                    SUPPRESSED
                    if hidden
                    else f"{statistic(row.median)} [{statistic(row.q1)}, {statistic(row.q3)}]",
                ),
                (
                    "missing",
                    "Observed / missing",
                    SUPPRESSED if hidden else f"{int(row.n)} / {int(row.missing)}",
                ),
            ]
        available = {entry[0] for entry in entries}
        selected = summaries.get(row.variable, tuple(available))
        if not selected or set(selected) - available:
            raise DataContractError(f"Unsupported summary selection for {row.variable!r}: {selected}")
        for summary, suffix, text in entries:
            if summary not in selected:
                continue
            level = getattr(row, "level_key", row.level)
            if pd.isna(level):
                level = row.level
            key = (row.variable, summary, str(level))
            if key not in rows:
                rows[key] = {"Characteristic": f"{variable}: {suffix}"}
                identities.append((row.variable, summary))
            if row.group in rows[key]:
                raise DataContractError("Duplicate characteristic rows in the saved report.")
            rows[key][row.group] = text
    result = pd.DataFrame(rows.values(), columns=["Characteristic", "Cases", "Controls"])
    for idx in result.index:
        fill = SUPPRESSED if result.loc[idx].eq(SUPPRESSED).any() else f"0 ({0:.{percent_decimals}f}%)"
        result.loc[idx] = result.loc[idx].fillna(fill)
    result.attrs["characteristics"] = identities
    return result


def publication_associations(
    table: pd.DataFrame, labels: dict, *, decimals=None, percent_decimals=1, numeric=False
) -> pd.DataFrame:
    def number(value, *, p=False):
        if isinstance(value, str):
            return value
        if pd.isna(value):
            return "Not estimable"
        if p and value < 0.001:
            return "<0.001"
        return f"{value:.3f}" if p else (f"{value:.3g}" if decimals is None else f"{value:.{decimals}f}")

    def scalar(value, *, p=False):
        if numeric and not isinstance(value, str) and pd.notna(value):
            return float(value)
        return number(value, p=p)

    def fraction(n, total):
        if isinstance(n, str) or isinstance(total, str):
            return SUPPRESSED
        if pd.isna(n) or pd.isna(total) or total == 0:
            return "Not available"
        return f"{int(n)}/{int(total)} ({100 * n / total:.{percent_decimals}f}%)"

    rows = []
    for _, row in table.iterrows():
        rows.append(
            {
                "Model": labels.get(row.model, row.model.replace("_", " ").title()),
                "Condition": labels.get(row.predictor, row.predictor.replace("_", " ").title()),
                "Status": {
                    "estimated": "Estimated",
                    "non_estimable": "Not estimable",
                    "suppressed_pending_disclosure_review": "Suppressed",
                }.get(row.status, row.status),
                "OR": scalar(row.odds_ratio),
                "95% CI": (
                    number(row.ci_lower)
                    if number(row.ci_lower) in {SUPPRESSED, "Not estimable"}
                    else number(row.ci_lower) + " to " + number(row.ci_upper)
                ),
                "P": scalar(row.p_value, p=True),
                "Holm P": scalar(row.p_holm, p=True) if row.primary else "Not primary",
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
    result = pd.DataFrame(rows)
    if table.duplicated(["model", "predictor"]).any():
        raise DataContractError("Duplicate model/condition results in the saved report.")
    result.attrs["associations"] = {(r.model, r.predictor): r.status for r in table.itertuples()}
    if numeric and not result.empty:
        result["OR (95% CI)"] = [
            number(row.odds_ratio)
            if isinstance(row.odds_ratio, str) or pd.isna(row.odds_ratio)
            else f"{number(row.odds_ratio)} ({number(row.ci_lower)} to {number(row.ci_upper)})"
            for row in table.itertuples(index=False)
        ]
    return result


@dataclass
class Report:
    tables: dict[str, pd.DataFrame]
    methods: str
    review_status: str = "requires_manual_disclosure_and_scientific_review"
    screened_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def save(self, path: str | Path):
        """Save screened aggregate inputs for formatting-only revisions inside Workbench."""

        def frames(tables):
            return {
                name: {
                    "columns": list(table),
                    "data": table.astype(object).where(pd.notna(table), None).to_numpy().tolist(),
                }
                for name, table in tables.items()
            }

        payload = {
            "schema_version": 1,
            "tables": frames(self.tables),
            "screened_tables": frames(self.screened_tables),
            "methods": self.methods,
            "review_status": self.review_status,
            "metadata": self.metadata,
        }
        Path(path).write_text(
            json.dumps({"payload": payload, "sha256": digest(payload)}, indent=2, allow_nan=False)
        )

    @classmethod
    def load(cls, path: str | Path):
        """Reload a saved report without participant files, source credentials or model engines."""
        path = Path(path)
        saved = json.loads((path / "report.json" if path.is_dir() else path).read_text())
        payload = saved["payload"]
        if digest(payload) != saved["sha256"] or payload["schema_version"] != 1:
            raise DataContractError("Report snapshot content/version changed. Restore the saved report.")

        def frames(tables):
            return {
                name: pd.DataFrame(value["data"], columns=value["columns"]) for name, value in tables.items()
            }

        return cls(
            tables=frames(payload["tables"]),
            methods=payload["methods"],
            review_status=payload["review_status"],
            screened_tables=frames(payload["screened_tables"]),
            metadata=payload["metadata"],
        )

    def write_excel(self, path: str | Path, *, layout=None, requirements=None):
        from .excel import write_workbook

        return write_workbook(path, {"main": self}, layout=layout, requirements=requirements)

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
        self.save(directory / "report.json")
        self.write_excel(directory / "tables.xlsx")


def build_report(
    matched: MatchResult, results: pd.DataFrame, flow: dict, study: StudySpec, spec: ReportSpec | None = None
) -> Report:
    labels = {
        **study.labels,
        **({key: item.label for key, item in spec.characteristics.items() if item.label} if spec else {}),
    }
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
    screened = {
        "characteristics": screened_characteristics(characteristics(matched, study, spec)),
        "associations": screened_associations(results, matched.members),
    }
    if spec:
        methods += (
            f"\nReport content version: {spec.version}; SHA-256: {digest(spec.model_dump(mode='json'))}."
        )
        for key, item in spec.characteristics.items():
            methods += f"\nDescriptive {key}: {item.kind}; source fields {list(item.fields)}."
            for category in item.groups:
                methods += f"\nDisplay group {category.label}: {category.values}."
        methods += "\nJoint categories preserve each recorded combination, including unknown/missing values. Explicit display groups do not alter matching. Binary n/N (%) uses observed values; missing counts are retained separately."
    # Persist only fields used by table presentation. Fit diagnostics remain private.
    association_fields = [
        "model",
        "predictor",
        "primary",
        "status",
        "odds_ratio",
        "ci_lower",
        "ci_upper",
        "p_value",
        "p_holm",
        "cases_analyzed",
        "controls_analyzed",
        "sets_analyzed",
        "case_with_condition",
        "control_with_condition",
    ]
    screened["associations"] = screened["associations"].reindex(columns=association_fields)
    return Report(
        {
            "characteristics": publication_characteristics(screened["characteristics"], labels),
            "associations": publication_associations(screened["associations"], study.labels),
            "flow": flow_table,
            "balance": balance,
        },
        methods,
        screened_tables=screened,
        metadata={
            "study_id": study.study_id,
            "protocol_version": study.version,
            "labels": labels,
            "report_spec": (spec or default_report_spec(study)).model_dump(mode="json"),
            "report_spec_hash": digest((spec or default_report_spec(study)).model_dump(mode="json")),
            "group_sizes": {
                "Cases" if role else "Controls": SUPPRESSED if small_count(len(group)) else len(group)
                for role, group in matched.members.drop_duplicates("person_id").groupby("is_case")
            },
            "age_reference_date": str(study.age_reference_date),
            "clinical_cutoff": str(study.clinical_cutoff),
            "dataset": study.dataset,
        },
    )
