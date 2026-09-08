import subprocess

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from aou_studies.coverage import PublicationSpec, ReportRequirement, check_coverage
from aou_studies.errors import DataContractError
from aou_studies.excel import DisplayFormat, SheetSpec, WorkbookSpec, write_workbook
from aou_studies.report_content import CharacteristicSpec, ReportSpec, summarize_characteristics
from aou_studies.reporting import Report, SUPPRESSED, publication_characteristics, screened_characteristics
from test_excel import read_xlsx, report as report


@pytest.fixture
def members():
    return pd.DataFrame(
        {
            "person_id": [str(i) for i in range(240)],
            "is_case": [1] * 120 + [0] * 120,
            "category_a": (["a"] * 60 + ["b"] * 60) * 2,
            "category_b": (["x"] * 30 + ["y"] * 30) * 4,
            "condition": ([1] * 30 + [0] * 60 + [None] * 30) * 2,
            "score": np.arange(240, dtype=float),
        }
    )


@pytest.fixture
def content():
    return ReportSpec(
        version="1",
        characteristics={
            "joint": CharacteristicSpec(fields=("category_a", "category_b")),
            "condition": CharacteristicSpec(fields=("condition",), kind="binary"),
            "score": CharacteristicSpec(fields=("score",), kind="continuous"),
        },
    )


def test_joint_binary_and_continuous_summaries_are_hand_calculated(members, content):
    result = summarize_characteristics(members, content)
    joint = result[result.variable.eq("joint")]
    assert joint.n.tolist() == [30] * 8
    assert set(joint.level) == {"a / x", "a / y", "b / x", "b / y"}
    assert joint.groupby("group").n.sum().tolist() == [120, 120]
    binary = result[result.variable.eq("condition")]
    assert binary.n.tolist() == [30, 30]
    assert binary.denominator.tolist() == [90, 90]
    assert binary.missing.tolist() == [30, 30]
    assert binary.percent.tolist() == pytest.approx([100 / 3, 100 / 3])
    score = result[(result.variable == "score") & (result.group == "Cases")].iloc[0]
    assert score["mean"] == score["median"] == 59.5
    assert score.q1 == 29.75 and score.q3 == 89.25
    shown = publication_characteristics(
        screened_characteristics(result), {}, summaries={"score": ("mean_sd",)}
    )
    assert "30/90 (33.3%)" in shown.Cases.tolist()
    assert "90 / 30" in shown.Cases.tolist()
    assert ("score", "median_iqr") not in shown.attrs["characteristics"]
    assert members.condition.isna().sum() == 60  # Reporting did not impute/change source values.


def test_explicit_category_groups_keep_unlisted_and_missing_values(members):
    members.loc[:29, "category_a"] = None
    spec = ReportSpec.model_validate(
        {
            "version": "1",
            "characteristics": {
                "joint": {
                    "fields": ["category_a", "category_b"],
                    "groups": [{"label": "Known a", "values": [["a", "x"], ["a", "y"]]}],
                }
            },
        }
    )
    result = summarize_characteristics(members, spec)
    assert "Missing / x" in result.level.tolist()
    assert result.groupby("group").n.sum().tolist() == [120, 120]
    assert result[(result.group == "Cases") & (result.level == "Known a")].n.item() == 30


@pytest.mark.parametrize("n", [1, 20])
def test_binary_missing_small_count_suppresses_both_groups(members, content, n):
    members["condition"] = ([1] * 30 + [0] * 90) * 2
    members.loc[: n - 1, "condition"] = np.nan
    result = screened_characteristics(summarize_characteristics(members, content))
    assert result[result.variable == "condition"].n.eq(SUPPRESSED).all()


def test_zero_and_all_missing_binary_results_are_distinct(members):
    spec = ReportSpec(
        version="1", characteristics={"flag": CharacteristicSpec(fields=("condition",), kind="binary")}
    )
    members["condition"] = 0.0
    members.loc[members.is_case == 1, "condition"] = np.nan
    shown = publication_characteristics(
        screened_characteristics(summarize_characteristics(members, spec)), {}
    )
    assert shown.iloc[0].Cases == "Not available"
    assert shown.iloc[0].Controls == "0/120 (0.0%)"
    assert shown.iloc[1].Cases == "0 / 120"


@pytest.mark.parametrize("change", ["missing_column", "invalid_binary", "infinite"])
def test_invalid_descriptive_source_fails(members, content, change):
    if change == "missing_column":
        members = members.drop(columns="category_a")
    else:
        members.loc[0, "condition"] = 2 if change == "invalid_binary" else np.inf
    with pytest.raises(DataContractError):
        summarize_characteristics(members, content)


def test_category_groups_must_not_overlap():
    with pytest.raises(ValidationError, match="nonoverlapping"):
        CharacteristicSpec.model_validate(
            {
                "fields": ["category"],
                "groups": [
                    {"label": "A", "values": [["x"]]},
                    {"label": "B", "values": [["x"]]},
                ],
            }
        )


@pytest.mark.parametrize("field", ["person_id", "match_set_id"])
def test_identifier_columns_cannot_be_reported(field):
    with pytest.raises(ValidationError, match="identifiers"):
        CharacteristicSpec(fields=(field,))


def test_colliding_joint_labels_fail_instead_of_merging_distinct_categories(members):
    members.loc[0, "category_a"] = "a / b"
    members.loc[0, "category_b"] = "c"
    members.loc[1, "category_a"] = "a"
    members.loc[1, "category_b"] = "b / c"
    content = ReportSpec(
        version="1", characteristics={"joint": CharacteristicSpec(fields=("category_a", "category_b"))}
    )
    with pytest.raises(DataContractError, match="Ambiguous category"):
        summarize_characteristics(members, content)


def example_requirements():
    return PublicationSpec(
        version="publication-1",
        reports={
            "main": ReportRequirement(
                characteristics={"sex": ("n_percent",)},
                associations={"primary": ("common", "rare")},
                group_sizes=True,
                tables={"flow": ("Stage", "Participants")},
            )
        },
    )


def split_layout():
    return WorkbookSpec(
        sheets=(
            SheetSpec(name="People", table="characteristics", variables=("sex",), group_sizes=True),
            SheetSpec(
                name="Estimates",
                table="associations",
                columns=("Condition", "OR (95% CI)", "P", "Holm P", "Status"),
            ),
            SheetSpec(
                name="Samples",
                table="associations",
                columns=("Model", "Condition", "Cases", "Controls", "Matched sets", "Status"),
            ),
            SheetSpec(name="Selection", table="flow"),
        )
    )


def test_split_tables_satisfy_same_requirements_and_keep_statuses(tmp_path, report):
    report.metadata["group_sizes"] = {"Cases": 200, "Controls": 200}
    requirements = example_requirements()
    coverage = check_coverage({"main": report}, layout=split_layout(), requirements=requirements)
    assert coverage.complete
    assert coverage.table.Status.eq("Included, suppressed").sum() == 1
    write_workbook(
        tmp_path / "split.xlsx", {"main": report}, layout=split_layout(), requirements=requirements
    )
    sheets, _, strings = read_xlsx(tmp_path / "split.xlsx")
    assert "Cases\n(n = 200)" in strings
    assert "Coverage" in sheets
    assert "12345678.7654321" not in strings
    layout = WorkbookSpec(
        sheets=(
            split_layout().sheets[0],
            SheetSpec(name="All results", table="associations"),
            split_layout().sheets[-1],
        )
    )
    assert check_coverage({"main": report}, layout=layout, requirements=requirements).complete


@pytest.mark.parametrize("omission", ["variable", "model", "column", "report", "group_size", "diagnostic"])
def test_incomplete_coverage_rejects_export_without_replacing_file(tmp_path, report, omission):
    report.metadata["group_sizes"] = {"Cases": 200, "Controls": 200}
    spec = example_requirements().model_dump(mode="json")
    item = spec["reports"]["main"]
    if omission == "variable":
        item["characteristics"]["not_reported"] = ["n_percent"]
    elif omission == "model":
        item["associations"]["not_fitted"] = ["common"]
    elif omission == "column":
        item["association_columns"].append("OR missing column")
    elif omission == "report":
        spec["reports"]["absent"] = item.copy()
    elif omission == "group_size":
        layout = split_layout().model_copy(
            update={
                "sheets": tuple(s.model_copy(update={"group_sizes": False}) for s in split_layout().sheets)
            }
        )
    else:
        item["tables"]["balance"] = ["Variable", "Absolute SMD after"]
    requirements = PublicationSpec.model_validate(spec)
    layout = layout if omission == "group_size" else split_layout()
    assert not check_coverage({"main": report}, layout=layout, requirements=requirements).complete
    path = tmp_path / "existing.xlsx"
    path.write_bytes(b"preserve")
    with pytest.raises(DataContractError, match="coverage is incomplete"):
        write_workbook(path, {"main": report}, layout=layout, requirements=requirements)
    assert path.read_bytes() == b"preserve"


def test_coverage_uses_stable_ids_and_checks_study_identity(report):
    report.metadata.update(group_sizes={"Cases": 200, "Controls": 200}, study_id="example")
    layout = split_layout().model_copy(
        update={"display": DisplayFormat(labels={"common": "Renamed", "sex": "Renamed"})}
    )
    assert check_coverage({"main": report}, layout=layout, requirements=example_requirements()).complete
    requirements = PublicationSpec(version="1", reports={"main": ReportRequirement(study_id="wrong")})
    assert not check_coverage({"main": report}, layout=layout, requirements=requirements).complete


def test_saved_coverage_and_layout_revision_need_no_queries_or_models(tmp_path, report, monkeypatch):
    report.metadata["group_sizes"] = {"Cases": 200, "Controls": 200}
    report.save(tmp_path / "report.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("No query or process during saved-report export")

    monkeypatch.setattr(subprocess, "run", forbidden)
    from google.cloud.bigquery import Client

    monkeypatch.setattr(Client, "query", forbidden)
    loaded = Report.load(tmp_path)
    write_workbook(
        tmp_path / "revision.xlsx",
        {"main": loaded},
        layout=split_layout(),
        requirements=example_requirements(),
    )
    assert (
        loaded.screened_tables["associations"].iloc[0].p_value
        == report.screened_tables["associations"].iloc[0].p_value
    )


def test_required_nonestimable_is_accounted_for_but_pending_is_not(report):
    report.metadata["group_sizes"] = {"Cases": 200, "Controls": 200}
    source = report.screened_tables["associations"]
    source.loc[0, ["odds_ratio", "ci_lower", "ci_upper", "p_value", "p_holm"]] = None
    source.loc[0, "status"] = "non_estimable"
    result = check_coverage({"main": report}, layout=split_layout(), requirements=example_requirements())
    assert result.complete and "Included, not estimable" in result.table.Status.tolist()
    source.loc[0, "status"] = "not_run"
    assert not check_coverage(
        {"main": report}, layout=split_layout(), requirements=example_requirements()
    ).complete


def test_multiple_model_rows_cannot_hide_their_identity(report):
    report.metadata["group_sizes"] = {"Cases": 200, "Controls": 200}
    second = report.screened_tables["associations"].copy()
    second["model"] = "second"
    report.screened_tables["associations"] = pd.concat([report.screened_tables["associations"], second])
    with pytest.raises(DataContractError, match="Model column"):
        check_coverage({"main": report}, layout=split_layout(), requirements=example_requirements())


def test_summary_selection_and_joint_snapshot_roundtrip(tmp_path, report, members, content):
    raw = summarize_characteristics(members, content)
    report.screened_tables["characteristics"] = screened_characteristics(raw)
    report.save(tmp_path / "report.json")
    loaded = Report.load(tmp_path)
    layout = WorkbookSpec(
        sheets=(
            SheetSpec(
                name="Scores",
                table="characteristics",
                variables=("score",),
                summaries={"score": ("mean_sd",)},
            ),
        )
    )
    requirements = PublicationSpec(
        version="1", reports={"main": ReportRequirement(characteristics={"score": ("mean_sd", "missing")})}
    )
    assert not check_coverage({"main": loaded}, layout=layout, requirements=requirements).complete
    with pytest.raises(DataContractError, match="Unsupported summary"):
        loaded.write_excel(
            tmp_path / "invalid.xlsx",
            layout=WorkbookSpec(
                sheets=(SheetSpec(name="Wrong", table="characteristics", summaries={"joint": ("mean_sd",)}),)
            ),
        )
    assert (
        loaded.screened_tables["characteristics"].level_key.dropna().tolist()
        == raw.level_key.dropna().tolist()
    )
