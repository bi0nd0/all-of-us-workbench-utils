import json
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
import pytest
from pydantic import ValidationError

from aou_studies.errors import DataContractError
from aou_studies.excel import WorkbookSpec, SheetSpec, HeaderGroup, DisplayFormat, write_workbook
from aou_studies.reporting import (
    Report,
    SUPPRESSED,
    screened_characteristics,
    screened_associations,
    publication_characteristics,
    publication_associations,
)

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx(path):
    with ZipFile(path) as archive:
        strings = ["".join(n.itertext()) for n in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        sheets = ET.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS)
        result = {}
        for i, sheet in enumerate(sheets, start=1):
            xml = ET.fromstring(archive.read(f"xl/worksheets/sheet{i}.xml"))
            cells = {}
            for c in xml.findall(".//s:c", NS):
                value = c.find("s:v", NS)
                if value is not None:
                    cells[c.attrib["r"]] = (
                        strings[int(value.text)] if c.get("t") == "s" else float(value.text)
                    )
            result[sheet.attrib["name"]] = (xml, cells)
        return result, archive.namelist(), strings


@pytest.fixture
def report():
    characteristics = pd.DataFrame(
        [
            dict(
                variable="sex",
                group=group,
                level=level,
                statistic="n_percent",
                n=n,
                denominator=200,
                percent=n / 2,
            )
            for group in ["Cases", "Controls"]
            for level, n in [("A", 100), ("B", 100)]
        ]
        + [
            dict(
                variable="rare",
                group="Cases",
                level="x",
                statistic="n_percent",
                n=1,
                denominator=200,
                percent=0.5,
            )
        ]
    )
    members = pd.DataFrame(
        {"is_case": [0] * 200 + [1] * 200, "common": ([0] * 100 + [1] * 100) * 2, "rare": [1] + [0] * 399}
    )
    rows = [
        dict(
            model="primary",
            predictor=predictor,
            primary=True,
            status="estimated",
            odds_ratio=1.234567891234567,
            ci_lower=1.1,
            ci_upper=1.5,
            p_value=0.0009999999999999994,
            p_holm=0.0019999999999999988,
            cases_analyzed=200,
            controls_analyzed=200,
            sets_analyzed=200,
            case_with_condition=100,
            control_with_condition=100,
        )
        for predictor in ["common", "rare"]
    ]
    rows[1]["odds_ratio"] = 12345678.7654321  # Must never enter the saved workbook/snapshot.
    char = screened_characteristics(characteristics)
    assoc = screened_associations(pd.DataFrame(rows), members)
    return Report(
        tables={
            "characteristics": publication_characteristics(char, {}),
            "associations": publication_associations(assoc, {}),
            "flow": pd.DataFrame({"Stage": ["Matched cases"], "Participants": [200]}),
            "balance": pd.DataFrame({"Variable": ["Age"], "Absolute SMD after": [0.01234]}),
        },
        screened_tables={"characteristics": char, "associations": assoc},
        methods="Age reference: 2026-09-07; clinical cutoff: 2025-01-01.\nPrimary: conditional.",
        metadata={"synthetic": True, "labels": {}},
    )


def test_saved_report_revision_preserves_precision_and_needs_no_engines(tmp_path, report, monkeypatch):
    report.save(tmp_path / "report.json")
    loaded = Report.load(tmp_path)
    assert loaded.screened_tables["associations"].iloc[0].p_value == 0.0009999999999999994

    def forbidden(*args, **kwargs):
        raise AssertionError("Formatting must not run external engines")

    monkeypatch.setattr(subprocess, "run", forbidden)
    from google.cloud.bigquery import Client

    monkeypatch.setattr(Client, "query", forbidden)
    layout = WorkbookSpec(
        display=DisplayFormat(estimate_decimals=4),
        sheets=(
            SheetSpec(
                name="Table 2",
                table="associations",
                models=("primary",),
                columns=("Condition", "OR", "95% CI", "P", "Cases", "Status"),
            ),
        ),
    )
    write_workbook(tmp_path / "revision.xlsx", {"main": loaded}, layout=layout)
    sheets, _, _ = read_xlsx(tmp_path / "revision.xlsx")
    _, cells = sheets["Table 2"]
    assert cells["B5"] == 1.234567891234567
    assert cells["C5"] == "1.1000 to 1.5000"
    assert cells["D5"] == 0.0009999999999999994
    assert cells["E5"] == 200
    assert cells["B6"] == SUPPRESSED


def test_workbook_contains_no_hidden_values_formulas_or_links(tmp_path, report):
    report.metadata["labels"] = {"common": '=HYPERLINK("https://example.org", "literal")'}
    report.write(tmp_path)
    sheets, paths, strings = read_xlsx(tmp_path / "tables.xlsx")
    assert len(sheets) == 5
    assert any(s.startswith("=HYPERLINK") for s in strings)
    assert "12345678.7654321" not in (tmp_path / "report.json").read_text()
    assert not any("externalLink" in p or "comments" in p for p in paths)
    with ZipFile(tmp_path / "tables.xlsx") as archive:
        assert "12345678.7654321" not in "".join(
            archive.read(p).decode() for p in paths if p.endswith(".xml")
        )
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        assert not any(
            s.get("state") in {"hidden", "veryHidden"} for s in workbook.findall("s:sheets/s:sheet", NS)
        )
    for xml, _ in sheets.values():
        assert xml.findall(".//s:f", NS) == []
        assert xml.findall(".//s:hyperlink", NS) == []
        assert not any(row.get("hidden") == "1" for row in xml.findall(".//s:row", NS))


def test_snapshot_tampering_is_rejected(tmp_path, report):
    path = tmp_path / "report.json"
    report.save(path)
    content = json.loads(path.read_text())
    content["payload"]["screened_tables"]["associations"]["data"][0][4] = 999
    path.write_text(json.dumps(content))
    with pytest.raises(DataContractError, match="content/version"):
        Report.load(path)


def test_layout_groups_labels_order_and_multiple_reports(tmp_path, report):
    layout = WorkbookSpec(
        display=DisplayFormat(characteristic_order=("rare", "sex")),
        sheets=(
            SheetSpec(
                name="Characteristics",
                table="characteristics",
                columns=("Characteristic", "Cases", "Controls"),
                column_labels={"Cases": "Study group"},
                widths={"Characteristic": 40},
                header_groups=(HeaderGroup(label="Participants, n (%)", columns=("Cases", "Controls")),),
            ),
            SheetSpec(name="Sensitivity", report="second", table="associations", models=("primary",)),
        ),
    )
    write_workbook(tmp_path / "tables.xlsx", {"main": report, "second": report}, layout=layout)
    sheets, _, _ = read_xlsx(tmp_path / "tables.xlsx")
    xml, cells = sheets["Characteristics"]
    assert cells["B4"] == "Participants, n (%)"
    assert cells["B5"] == "Study group"
    assert cells["A6"] == "Rare: x"
    assert cells["B6"] == cells["C6"] == SUPPRESSED  # Missing group level stays suppressed.
    assert xml.find("s:pageSetup", NS).get("orientation") == "portrait"
    assert len(sheets) == 3


@pytest.mark.parametrize("name", ["bad/name", "'edge", "Methods", "History"])
def test_invalid_sheet_names(name):
    with pytest.raises(ValidationError):
        SheetSpec(name=name, table="flow")


def test_invalid_selection_preserves_existing_workbook(tmp_path, report):
    path = tmp_path / "tables.xlsx"
    path.write_bytes(b"existing workbook")
    for change in [
        {"models": ("not_a_model",)},
        {"columns": ("person_id",)},
        {
            "columns": ("Condition", "OR", "P"),
            "header_groups": (HeaderGroup(label="Wrong order", columns=("Condition", "P")),),
        },
    ]:
        layout = WorkbookSpec(sheets=(SheetSpec(name="Results", table="associations", **change),))
        with pytest.raises(DataContractError):
            write_workbook(path, {"main": report}, layout=layout)
        assert path.read_bytes() == b"existing workbook"


def test_zero_missing_nonestimable_and_literal_text_stay_distinct(tmp_path, report):
    source = report.screened_tables["associations"]
    source.loc[0, ["odds_ratio", "ci_lower", "ci_upper", "p_value", "p_holm"]] = None
    source.loc[0, "status"] = "non_estimable"
    report.tables["flow"] = pd.DataFrame(
        {"Stage": ["Zero", "Missing", "=literal"], "Participants": [0, None, 200]}
    )
    report.write_excel(tmp_path / "tables.xlsx")
    sheets, _, strings = read_xlsx(tmp_path / "tables.xlsx")
    _, flow = sheets["Flow"]
    assert flow["B5"] == 0
    assert flow["B6"] == "Not available"
    assert flow["A7"] == "=literal"
    assert "Not estimable" in strings
    assert SUPPRESSED in strings


def test_duplicate_sheets_and_mixed_modes_fail(tmp_path, report):
    with pytest.raises(ValidationError, match="unique"):
        WorkbookSpec(sheets=(SheetSpec(name="Flow", table="flow"), SheetSpec(name="flow", table="flow")))
    real = Report(report.tables, report.methods, metadata={"synthetic": False})
    with pytest.raises(DataContractError, match="separate workbooks"):
        write_workbook(tmp_path / "mixed.xlsx", {"main": report, "real": real})
