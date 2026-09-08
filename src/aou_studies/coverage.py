"""Reconcile publication content independently of its table arrangement."""

from dataclasses import dataclass
import pandas as pd
from pydantic import Field, model_validator

from .errors import DataContractError
from .report_content import ContentModel, Summary


class ReportRequirement(ContentModel):
    study_id: str | None = None
    protocol_version: str | None = None
    characteristics: dict[str, tuple[Summary, ...]] = Field(default_factory=dict)
    associations: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    association_columns: tuple[str, ...] = (
        "Condition",
        "OR",
        "95% CI",
        "P",
        "Cases",
        "Controls",
        "Matched sets",
    )
    tables: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    group_sizes: bool = False

    @model_validator(mode="after")
    def valid_requirements(self):
        for mapping in (self.characteristics, self.associations, self.tables):
            if any(
                not key or not values or len(set(values)) != len(values) for key, values in mapping.items()
            ):
                raise ValueError(
                    "Required content needs nonempty identifiers and unique, nonempty selections."
                )
        if set(self.tables) - {"flow", "balance"}:
            raise ValueError(
                "Use characteristics/associations requirements for summaries and models; diagnostic tables are flow/balance."
            )
        if self.associations and not self.association_columns:
            raise ValueError("Select required association columns.")
        return self


class PublicationSpec(ContentModel):
    version: str = Field(min_length=1)
    reports: dict[str, ReportRequirement] = Field(min_length=1)


@dataclass
class CoverageResult:
    table: pd.DataFrame

    @property
    def complete(self):
        return not self.table.Status.eq("Missing").any()

    def require_complete(self):
        missing = self.table[self.table.Status.eq("Missing")]
        if not missing.empty:
            details = "; ".join(f"{r.Report}: {r.Content} ({r.Details})" for r in missing.itertuples())
            raise DataContractError("Publication coverage is incomplete: " + details)


def _columns(table):
    columns = set(table.columns)
    if "OR (95% CI)" in columns:
        columns.update(["OR", "95% CI"])
    if "Condition in sampled cases" in columns:
        columns.add("Cases")
    if "Condition in sampled controls" in columns:
        columns.add("Controls")
    return columns


def reconcile(reports, prepared, requirements: PublicationSpec) -> CoverageResult:
    rows = []

    def record(report, content, found, details="", status="Included"):
        rows.append(
            dict(
                Report=report,
                Content=content,
                Status=status if found else "Missing",
                Sheets=", ".join(found),
                Details=details,
            )
        )

    for key, requirement in requirements.reports.items():
        report = reports.get(key)
        selected = [(sheet, table) for sheet, table in prepared if sheet.report == key]
        if report is None or not selected:
            record(key, "Report", [], "No tables from the required report")
            continue
        for field in ("study_id", "protocol_version"):
            expected = getattr(requirement, field)
            if expected is not None and report.metadata.get(field) != expected:
                record(key, field, [], "Saved report does not match the required study/version")
        if requirement.group_sizes:
            found = [
                s.name
                for s, _ in selected
                if s.table == "characteristics"
                and s.group_sizes
                and {"Cases", "Controls"}.issubset(s.columns or ("Cases", "Controls"))
                and set(report.metadata.get("group_sizes", {})) == {"Cases", "Controls"}
            ]
            record(key, "Group sizes", found, "Unique matched participants; suppressed sizes remain labeled")
        for variable, summaries in requirement.characteristics.items():
            for summary in summaries:
                found, columns = [], set()
                for sheet, table in selected:
                    if (variable, summary) in table.attrs.get("characteristics", []):
                        found.append(sheet.name)
                        columns.update(table.columns)
                missing = {"Characteristic", "Cases", "Controls"} - columns
                record(
                    key,
                    f"{variable}: {summary}",
                    found if not missing else [],
                    "Missing columns: " + ", ".join(sorted(missing))
                    if missing
                    else "Screened summary included",
                )
        for model, predictors in requirement.associations.items():
            for predictor in predictors:
                found, columns, statuses = [], set(), set()
                for sheet, table in selected:
                    items = table.attrs.get("associations", {})
                    if (model, predictor) in items:
                        found.append(sheet.name)
                        columns.update(_columns(table))
                        statuses.add(items[(model, predictor)])
                source = report.screened_tables.get("associations", pd.DataFrame())
                source_rows = (
                    source[(source.model == model) & (source.predictor == predictor)]
                    if {"model", "predictor"}.issubset(source)
                    else pd.DataFrame()
                )
                required = set(requirement.association_columns)
                if not source_rows.empty and source_rows.primary.any():
                    required.add("Holm P")
                missing = required - columns
                state = "Included"
                if "suppressed_pending_disclosure_review" in statuses:
                    state = "Included, suppressed"
                elif "non_estimable" in statuses:
                    state = "Included, not estimable"
                valid = statuses <= {"estimated", "non_estimable", "suppressed_pending_disclosure_review"}
                details = (
                    "Missing columns: " + ", ".join(sorted(missing))
                    if missing
                    else "Result is accounted for; scientific acceptance is separate"
                )
                if not valid:
                    details = "Required analysis has an unavailable or unrecognized status"
                record(key, f"{model}: {predictor}", found if not missing and valid else [], details, state)
        for name, required in requirement.tables.items():
            found = [s.name for s, t in selected if s.table == name and set(required).issubset(t)]
            record(key, name, found, "Required diagnostic columns included")
        record(key, "Methods and review status", ["Methods"], "Generated for each displayed report")
    return CoverageResult(pd.DataFrame(rows))


def check_coverage(reports, *, layout, requirements: PublicationSpec) -> CoverageResult:
    """Inspect omissions without writing files or running extraction/statistical engines."""
    from .excel import _prepare

    _, prepared = _prepare(reports, layout)
    return reconcile(reports, prepared, requirements)
