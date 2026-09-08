"""Reusable manuscript layouts over screened aggregate reports, using XlsxWriter.

No extraction or estimation occurs here. Real workbooks still need whole-release
disclosure review inside Workbench. Presentation options cannot grant clearance.
"""

from collections.abc import Mapping
from pathlib import Path
import math
import re
import tempfile
import textwrap
from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

from .errors import DataContractError
from .report_content import Summary

if TYPE_CHECKING:
    from .reporting import Report


class LayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DisplayFormat(LayoutModel):
    descriptive_decimals: int = Field(default=1, ge=0, le=6)
    percent_decimals: int = Field(default=1, ge=0, le=6)
    estimate_decimals: int = Field(default=2, ge=0, le=8)
    p_decimals: int = Field(default=3, ge=1, le=8)
    characteristic_order: tuple[str, ...] = ()
    condition_order: tuple[str, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict)


class HeaderGroup(LayoutModel):
    label: str
    columns: tuple[str, ...] = Field(min_length=1)


class SheetSpec(LayoutModel):
    name: str = Field(min_length=1, max_length=31)
    report: str = "main"
    table: Literal["characteristics", "associations", "flow", "balance"]
    title: str = ""
    models: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()
    summaries: dict[str, tuple[Summary, ...]] = Field(default_factory=dict)
    group_sizes: bool = False
    columns: tuple[str, ...] = ()
    column_labels: dict[str, str] = Field(default_factory=dict)
    widths: dict[str, float] = Field(default_factory=dict)
    header_groups: tuple[HeaderGroup, ...] = ()
    footnotes: tuple[str, ...] = ()
    orientation: Literal["auto", "portrait", "landscape"] = "auto"

    @model_validator(mode="after")
    def valid_sheet(self):
        if (
            re.search(r"[\[\]:*?/\\\x00-\x1f]", self.name)
            or self.name.startswith("'")
            or self.name.endswith("'")
        ):
            raise ValueError("Use an Excel sheet name without brackets, slashes, colons or edge apostrophes.")
        if self.name.casefold() in {"methods", "history", "coverage"}:
            raise ValueError("Methods, History and Coverage are reserved sheet names.")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Select each column only once.")
        if any(not math.isfinite(w) or not 8 <= w <= 80 for w in self.widths.values()):
            raise ValueError("Column widths must be finite and between 8 and 80.")
        if self.models and self.table != "associations":
            raise ValueError("Model selection applies only to association tables.")
        if (self.variables or self.summaries or self.group_sizes) and self.table != "characteristics":
            raise ValueError("Variable/summary selection and group sizes apply to characteristics tables.")
        if len(set(self.variables)) != len(self.variables) or any(
            not values for values in self.summaries.values()
        ):
            raise ValueError("Select unique variables and at least one summary for each selected variable.")
        return self


class WorkbookSpec(LayoutModel):
    title: str = "Study tables"
    display: DisplayFormat = Field(default_factory=DisplayFormat)
    sheets: tuple[SheetSpec, ...] = ()

    @model_validator(mode="after")
    def unique_sheets(self):
        names = [s.name.casefold() for s in self.sheets]
        if len(set(names)) != len(names):
            raise ValueError("Sheet names must be unique, ignoring case.")
        return self

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))


def _ordered(frame, column, order):
    if not order:
        return frame
    # Unlisted rows remain present, in source order; a layout never drops them.
    rank = {name: i for i, name in enumerate(order)}
    return frame.iloc[frame[column].map(rank).fillna(len(rank)).argsort(kind="stable")]


def _table(report: "Report", sheet: SheetSpec, display: DisplayFormat):
    from .reporting import publication_associations, publication_characteristics

    labels = {**report.metadata.get("labels", {}), **display.labels}
    if sheet.table in report.screened_tables:
        source = report.screened_tables[sheet.table].copy(deep=True)
        if sheet.table == "characteristics":
            if sheet.variables:
                missing = set(sheet.variables) - set(source.variable)
                if missing:
                    raise DataContractError(
                        f"Missing saved characteristics: {sorted(missing)}. Regenerate the report with the required content."
                    )
                source = source[source.variable.isin(sheet.variables)]
            source = _ordered(source, "variable", display.characteristic_order)
            source = _ordered(source, "variable", sheet.variables)
            table = publication_characteristics(
                source,
                labels,
                decimals=display.descriptive_decimals,
                percent_decimals=display.percent_decimals,
                summaries=sheet.summaries,
            )
        else:
            if sheet.models:
                missing = set(sheet.models) - set(source.model)
                if missing:
                    raise DataContractError(f"Unknown model selection: {sorted(missing)}")
                source = source[source.model.isin(sheet.models)]
                source = _ordered(source, "model", sheet.models)
            source = _ordered(source, "predictor", display.condition_order)
            table = publication_associations(
                source,
                labels,
                decimals=display.estimate_decimals,
                percent_decimals=display.percent_decimals,
                numeric=True,
            )
    else:
        if sheet.models or sheet.variables or sheet.summaries:
            raise DataContractError("This saved report lacks numeric aggregates. Regenerate its report once.")
        table = report.tables[sheet.table].copy(deep=True)
    if table.empty:
        raise DataContractError(f"No rows for sheet {sheet.name}; review its table/model selection.")
    columns = list(sheet.columns or table.columns)
    if (
        sheet.table == "associations"
        and len({m for m, _ in table.attrs.get("associations", {})}) > 1
        and "Model" not in columns
    ):
        raise DataContractError("Include the Model column when displaying more than one model on a sheet.")
    if sheet.group_sizes and set(report.metadata.get("group_sizes", {})) != {"Cases", "Controls"}:
        raise DataContractError("This saved report lacks group sizes. Regenerate its report once.")
    if len(set(sheet.column_labels.get(c, c) for c in columns)) != len(columns):
        raise DataContractError("Displayed column labels must remain distinct.")
    referenced = set(columns) | set(sheet.widths) | set(sheet.column_labels)
    if referenced - set(table.columns):
        raise DataContractError(f"Unknown report columns: {sorted(referenced - set(table.columns))}")
    if (set(sheet.widths) | set(sheet.column_labels)) - set(columns):
        raise DataContractError("Column labels and widths must refer to selected columns.")
    used = set()
    for group in sheet.header_groups:
        if set(group.columns) - set(columns) or used.intersection(group.columns):
            raise DataContractError("Header groups must use selected, nonoverlapping columns.")
        positions = [columns.index(c) for c in group.columns]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise DataContractError("Header group columns must be contiguous and in display order.")
        used.update(group.columns)
    # Keep fit status visible even when the compact journal layout omits that column:
    # non-estimable/suppressed estimates themselves always retain their textual state.
    return table[columns]


def _default_layout(reports):
    sheets = []
    for index, key in enumerate(reports):
        for table in ("characteristics", "associations", "flow", "balance"):
            name = table.title() if len(reports) == 1 else f"{index + 1} {table.title()}"
            options = {}
            if table == "associations":
                options = dict(
                    columns=(
                        "Model",
                        "Condition",
                        "Condition in sampled cases",
                        "Condition in sampled controls",
                        "OR (95% CI)",
                        "P",
                        "Holm P",
                        "Status",
                    ),
                    widths={
                        "Model": 20,
                        "Condition": 23,
                        "Condition in sampled cases": 19,
                        "Condition in sampled controls": 19,
                        "OR (95% CI)": 24,
                        "P": 9,
                        "Holm P": 9,
                        "Status": 17,
                    },
                )
                if "associations" not in reports[key].screened_tables:
                    options = {}
            sheets.append(
                SheetSpec(name=name, report=key, table=table, title=f"{key}: {table.title()}", **options)
            )
    return WorkbookSpec(sheets=tuple(sheets))


def _write_text(ws, row, text, width, fmt, last_col):
    wrapped = "\n".join(textwrap.fill(line, max(20, int(width))) for line in text.splitlines())
    lines = max(1, len(wrapped.splitlines()))
    if len(text) > 32767 or lines * 14 + 6 > 409:
        raise DataContractError("A title or note is too long for an Excel row; split it into shorter notes.")
    if last_col:
        ws.merge_range(row, 0, row, last_col, wrapped, fmt)
    else:
        ws.write_string(row, 0, wrapped, fmt)
    ws.set_row(row, max(22, lines * 14 + 6))
    return row + 1


def _display_value(value, column, display):
    if isinstance(value, str):
        return value
    if pd.isna(value):
        return "Not available"
    if column in {"Cases", "Controls", "Matched sets", "Participants"}:
        return f"{value:,.0f}"
    if column in {"P", "Holm P"}:
        threshold = 10**-display.p_decimals
        return (
            f"<{threshold:.{display.p_decimals}f}" if value < threshold else f"{value:.{display.p_decimals}f}"
        )
    if column == "OR":
        return f"{value:.{display.estimate_decimals}f}"
    if "SMD" in column or "ratio" in column.lower():
        return f"{value:.3f}"
    return str(value)


def _sheet(writer, report, spec, display, table):
    book = writer.book
    ws = book.add_worksheet(spec.name)
    ws.hide_gridlines(2)
    columns = list(table)
    widths = [
        spec.widths.get(
            c,
            38
            if c in {"Characteristic", "Variable", "Stage"}
            else 18
            if "SMD" in c or "ratio" in c.lower() or c == "Type"
            else 24,
        )
        for c in columns
    ]
    total_width = sum(widths)
    base = {"font_name": "Arial", "font_size": 10, "valign": "vcenter", "text_wrap": True}
    note = book.add_format({**base, "font_color": "#454545"})
    title = book.add_format({**base, "font_size": 14, "bold": True, "bottom": 1})
    header = book.add_format({**base, "bold": True, "align": "center", "bg_color": "#EDF1F5", "bottom": 1})
    group_format = book.add_format({**base, "bold": True, "align": "center", "bottom": 1})
    last = len(columns) - 1
    row = _write_text(ws, 1, spec.title or spec.name, total_width, title, last)
    mode = "SYNTHETIC EXAMPLE. " if report.metadata.get("synthetic") else ""
    row = _write_text(ws, row, mode + "Draft for scientific and disclosure review.", total_width, note, last)
    if spec.header_groups:
        for group in spec.header_groups:
            a, b = columns.index(group.columns[0]), columns.index(group.columns[-1])
            if a == b:
                ws.write_string(row, a, group.label, group_format)
            else:
                ws.merge_range(row, a, row, b, group.label, group_format)
        ws.set_row(row, 30)
        row += 1
    header_row = row
    for col, name in enumerate(columns):
        label = spec.column_labels.get(name, name)
        if spec.group_sizes and name in {"Cases", "Controls"}:
            n = report.metadata["group_sizes"][name]
            label += f"\n(n = {n:,})" if isinstance(n, int) else f"\n(n = {n})"
        ws.write_string(row, col, label, header)
    ws.set_row(row, 44)
    row += 1
    body_formats = []
    for col, name in enumerate(columns):
        code = "General"
        if name in {"Cases", "Controls", "Matched sets", "Participants"}:
            code = "#,##0"
        elif name in {"P", "Holm P"}:
            threshold = 10**-display.p_decimals
            code = (
                f'[<{threshold:.{display.p_decimals}f}]"<{threshold:.{display.p_decimals}f}";0.'
                + "0" * display.p_decimals
            )
        elif name == "OR":
            code = "0" + ("." + "0" * display.estimate_decimals if display.estimate_decimals else "")
        elif "SMD" in name or "ratio" in name.lower():
            code = "0.000"
        fmt = book.add_format(
            {**base, "num_format": code, "indent": 1, "align": "right" if code != "General" else "left"}
        )
        ws.set_column(col, col, widths[col], fmt)
        body_formats.append(fmt)
    # Pandas writes only the selected screened values; no hidden raw-data sheets.
    table.to_excel(
        writer, sheet_name=spec.name, startrow=row, index=False, header=False, na_rep="Not available"
    )
    for offset, values in enumerate(table.itertuples(index=False, name=None)):
        # Explicit cell formats also work in readers that do not inherit column styles.
        for col, (value, fmt) in enumerate(zip(values, body_formats)):
            ws.write(row + offset, col, "Not available" if pd.isna(value) else value, fmt)
        height = max(
            1,
            max(
                sum(
                    len(textwrap.wrap(line, max(8, int(w - 2)))) or 1
                    for line in _display_value(v, c, display).splitlines()
                )
                for v, c, w in zip(values, columns, widths)
            ),
        )
        if any(len(str(v)) > 32767 for v in values) or height * 14 + 6 > 409:
            raise DataContractError("A report cell is too long to display in Excel; shorten its label.")
        ws.set_row(row + offset, max(24, height * 14 + 6))
    end = row + len(table)
    if len(table) > 18 or total_width > 125:
        ws.freeze_panes(row, 1)
    if spec.table in {"balance", "flow"}:
        ws.autofilter(header_row, 0, end - 1, last)
    footnotes = {
        "characteristics": "Counts are unique participants. Categorical percentages use the full group; binary n/N (%) uses participants with an observed value. Summary types and observed/missing counts are labeled per row. No baseline P values.",
        "associations": "OR: association odds ratio for sampled case status. Each fraction uses the model-specific denominator. Conditional models use pointwise 95% Wald intervals; unconditional Firth sensitivities use profile-likelihood intervals. Holm P applies only to the prespecified primary family.",
        "flow": "Participant counts describe cohort construction and matching. Stages may overlap; do not add them.",
        "balance": "SMD: standardized mean difference. Before matching uses the eligible pool; after matching uses retained-set weights. Characteristics use unweighted counts.",
    }
    for text in (
        footnotes[spec.table],
        *spec.footnotes,
        "Suppressed values are unavailable here. Review this workbook with all other proposed outputs before export from Workbench.",
    ):
        end = _write_text(ws, end + 1, text, total_width, note, last)
    ws.repeat_rows(header_row, header_row)
    ws.print_area(0, 0, end, last)
    ws.set_paper(1)
    if spec.orientation == "landscape" or (spec.orientation == "auto" and total_width > 95):
        ws.set_landscape()
    else:
        ws.set_portrait()
    ws.fit_to_pages(1, 0)
    ws.set_margins(0.3, 0.3, 0.4, 0.4)
    ws.set_footer("Page &P of &N")


def _prepare(reports, layout):
    if not reports:
        raise DataContractError("Provide at least one saved report.")
    if len({r.metadata.get("synthetic") for r in reports.values()}) > 1:
        raise DataContractError("Keep synthetic examples and real-data reports in separate workbooks.")
    layout = layout or _default_layout(reports)
    if not layout.sheets:
        layout = layout.model_copy(update={"sheets": _default_layout(reports).sheets})
    prepared = []
    for sheet in layout.sheets:
        if sheet.report not in reports:
            raise DataContractError(f"Missing report {sheet.report!r} for sheet {sheet.name!r}.")
        prepared.append((sheet, _table(reports[sheet.report], sheet, layout.display)))
    return layout, prepared


def _coverage_sheet(writer, coverage):
    ws = writer.book.add_worksheet("Coverage")
    ws.hide_gridlines(2)
    header = writer.book.add_format({"bold": True, "bg_color": "#EDF1F5", "text_wrap": True})
    body = writer.book.add_format({"font_name": "Arial", "font_size": 10, "text_wrap": True, "valign": "top"})
    ws.merge_range(
        0,
        0,
        0,
        4,
        "Required content is accounted for. Scientific and disclosure review remain separate.",
        body,
    )
    ws.set_row(0, 32)
    for col, (name, width) in enumerate(zip(coverage.table.columns, [20, 34, 24, 36, 55])):
        ws.set_column(col, col, width, body)
        ws.write_string(2, col, name, header)
    coverage.table.to_excel(writer, sheet_name="Coverage", startrow=3, index=False, header=False)
    for idx, values in enumerate(coverage.table.itertuples(index=False, name=None)):
        height = (
            max(
                sum(len(textwrap.wrap(line, width - 2)) or 1 for line in str(value).splitlines())
                for value, width in zip(values, [20, 34, 24, 36, 55])
            )
            * 14
            + 6
        )
        if height > 409 or any(len(str(value)) > 32767 for value in values):
            raise DataContractError(
                "Coverage labels are too long for Excel; shorten content identifiers or sheet names."
            )
        ws.set_row(idx + 3, max(24, height))
        for col, value in enumerate(values):
            ws.write_string(idx + 3, col, value, body)
    ws.freeze_panes(3, 2)
    ws.autofilter(2, 0, len(coverage.table) + 2, 4)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(2, 2)
    ws.print_area(0, 0, len(coverage.table) + 2, 4)


def write_workbook(
    path: str | Path,
    reports: Mapping[str, "Report"],
    *,
    layout: WorkbookSpec | None = None,
    requirements=None,
) -> Path:
    """Export screened tables; optional separate requirements reject incomplete publication coverage.

    Layout-only revisions never query, match or fit. A complete coverage check does
    not establish estimability, disclosure clearance or scientific acceptance.
    """
    from .coverage import reconcile

    layout, prepared = _prepare(reports, layout)
    coverage = reconcile(reports, prepared, requirements) if requirements is not None else None
    if coverage is not None:
        coverage.require_complete()
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise DataContractError("Choose a filename ending in .xlsx.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement keeps an existing workbook intact if validation/writing fails.
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        temporary = Path(tmp) / path.name
        with pd.ExcelWriter(
            temporary,
            engine="xlsxwriter",
            engine_kwargs={
                "options": {
                    "strings_to_formulas": False,
                    "strings_to_urls": False,
                    "strings_to_numbers": False,
                }
            },
        ) as writer:
            writer.book.set_properties(
                {"title": layout.title, "comments": "Screened aggregate review candidate"}
            )
            for sheet, table in prepared:
                _sheet(writer, reports[sheet.report], sheet, layout.display, table)
            if coverage is not None:
                _coverage_sheet(writer, coverage)
            ws = writer.book.add_worksheet("Methods")
            ws.hide_gridlines(2)
            ws.set_column(0, 0, 105)
            fmt = writer.book.add_format(
                {"font_name": "Arial", "font_size": 10, "text_wrap": True, "valign": "vcenter"}
            )
            row = 1
            if requirements is not None:
                from .provenance import digest

                row = _write_text(
                    ws,
                    row,
                    f"Publication requirements: {requirements.version}; SHA-256: {digest(requirements.model_dump(mode='json'))}",
                    105,
                    fmt,
                    0,
                )
            for key in dict.fromkeys(sheet.report for sheet in layout.sheets):
                report = reports[key]
                row = _write_text(ws, row, key, 105, fmt, 0)
                for line in report.methods.splitlines():
                    row = _write_text(ws, row, line, 105, fmt, 0)
                row = _write_text(ws, row, f"Review status: {report.review_status}", 105, fmt, 0)
                if report.metadata.get("synthetic"):
                    row = _write_text(
                        ws, row, "Generated synthetic participants; no study findings.", 105, fmt, 0
                    )
                row += 1
            ws.print_area(0, 0, row, 0)
            ws.fit_to_pages(1, 0)
            ws.set_margins(0.3, 0.3, 0.4, 0.4)
        temporary.replace(path)
    return path
