import pandas as pd
import pytest
from aou_studies.errors import DataContractError
from aou_studies.provenance import ArtifactStore, frame_digest
from aou_studies.reporting import small_count, screened_characteristics, screened_associations, SUPPRESSED
from aou_studies.runner import StudyRun, sensitivity_spec


@pytest.mark.parametrize("n, expected", [(0, False), (1, True), (19, True), (20, True), (21, False)])
def test_policy_boundaries(n, expected):
    assert small_count(n) == expected


def test_complementary_suppression_across_groups():
    table = pd.DataFrame(
        {
            "variable": ["race"] * 4,
            "group": ["Cases"] * 2 + ["Controls"] * 2,
            "level": ["a", "b"] * 2,
            "statistic": "n_percent",
            "n": [1, 99, 30, 170],
            "denominator": [100, 100, 200, 200],
            "percent": [1, 99, 15, 85],
        }
    )
    result = screened_characteristics(table)
    assert result.n.eq(SUPPRESSED).all()
    assert result.percent.eq(SUPPRESSED).all()
    assert result.denominator.eq(SUPPRESSED).all()


def test_cache_identity_and_tamper_detection(tmp_path, features):
    store = ArtifactStore(tmp_path)
    store.save_frame("features", features, {"release": "v9"})
    assert store.load_frame("features", {"release": "v8"}) is None
    assert frame_digest(store.load_frame("features", {"release": "v9"})) == frame_digest(features)
    modified = features.copy()
    modified.loc[0, "age"] = 40
    modified.to_parquet(tmp_path / "features.parquet", index=False)
    with pytest.raises(DataContractError, match="content hash"):
        store.load_frame("features", {"release": "v9"})


def test_full_synthetic_pipeline_and_repeat(tmp_path, features, study):
    run = StudyRun(study, tmp_path / "first", synthetic=True)
    run.use_synthetic(features)
    run.build_groups()
    run.match()
    run.analyze()
    run.report()
    assert (tmp_path / "first/review/report.html").exists()
    assert run.results.status.eq("estimated").all()
    repeated = StudyRun(study, tmp_path / "repeat", synthetic=True)
    repeated.use_synthetic(features.sample(frac=1, random_state=1))
    repeated.build_groups()
    repeated.match()
    repeated.analyze()
    assert run.manifest["membership_hash"] == repeated.manifest["membership_hash"]
    assert run.manifest["result_hash"] == repeated.manifest["result_hash"]
    changed = sensitivity_spec(study, version="2", minimum_age=30)
    with pytest.raises(DataContractError, match="configuration changed"):
        StudyRun(changed, tmp_path / "first")


def test_real_direct_input_is_rejected(tmp_path, study, features):
    with pytest.raises(DataContractError, match="synthetic"):
        StudyRun(study, tmp_path).use_synthetic(features)


def test_changed_config_or_features_cannot_continue_frozen_run(tmp_path, study, features):
    run = StudyRun(study, tmp_path / "config", synthetic=True)
    run.use_synthetic(features)
    study.labels["condition"] = "Changed during run"
    with pytest.raises(DataContractError, match="configuration mutated"):
        run.build_groups()
    run = StudyRun(study, tmp_path / "features", synthetic=True)
    run.use_synthetic(features)
    run.features.loc[0, "age"] += 1
    with pytest.raises(DataContractError, match="Features changed"):
        run.build_groups()


def test_sensitivity_reuse_checks_extraction_identity(tmp_path, study, features):
    run = StudyRun(study, tmp_path / "base", synthetic=True)
    run.use_synthetic(features)
    compatible = sensitivity_spec(study, version="eligible", minimum_age=30)
    variant = StudyRun(compatible, tmp_path / "eligible", synthetic=True)
    variant.reuse_features(run)
    assert frame_digest(variant.features) == frame_digest(features)
    incompatible = sensitivity_spec(study, version="cutoff", clinical_cutoff="2024-01-01")
    with pytest.raises(DataContractError, match="identical extraction"):
        StudyRun(incompatible, tmp_path / "cutoff", synthetic=True).reuse_features(run)


def test_model_specific_small_cell_screens_large_overall_table():
    members = pd.DataFrame(
        {"is_case": [0] * 100 + [1] * 100, "condition": [0] * 50 + [1] * 50 + [0] * 50 + [1] * 50}
    )
    results = pd.DataFrame(
        [
            {
                "model": "complete_case",
                "predictor": "condition",
                "status": "estimated",
                "case_with_condition": 1,
                "case_without_condition": 50,
                "control_with_condition": 50,
                "control_without_condition": 50,
                "odds_ratio": 2.0,
                "p_value": 0.01,
            }
        ]
    )
    screened = screened_associations(results, members)
    assert screened.loc[0, "odds_ratio"] == SUPPRESSED
    assert screened.loc[0, "case_with_condition"] == SUPPRESSED
