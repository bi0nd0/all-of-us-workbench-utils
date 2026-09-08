import numpy as np
import pandas as pd
import pytest
from aou_studies.specs import StudySpec


@pytest.fixture
def study_dict():
    return {
        "study_id": "synthetic",
        "version": "1",
        "age_reference_date": "2026-09-07",
        "clinical_cutoff": "2025-01-01",
        "tier": "registered",
        "case": {"field": "case_condition", "value": 1},
        "control": {"field": "case_condition", "value": 0},
        "conditions": {"case_condition": {"concepts": {"ids": [1]}}, "condition": {"concepts": {"ids": [2]}}},
        "matching": {"exact": ["sex_at_birth"], "calipers": {"age": 3}, "distance": ["age"], "ratio": 2},
        "models": [{"name": "primary", "predictors": ["condition"], "covariates": ["age"], "primary": True}],
    }


@pytest.fixture
def study(study_dict):
    return StudySpec.model_validate(study_dict)


@pytest.fixture
def features():
    rng = np.random.default_rng(88)
    n = 360
    return pd.DataFrame(
        {
            "person_id": [str(x) for x in range(1, n + 1)],
            "age": rng.integers(25, 70, n),
            "age_at_cutoff": rng.integers(23, 68, n),
            "sex_at_birth": np.where(np.arange(n) % 2, "female", "male"),
            "race": "example",
            "ethnicity": "example",
            "ehr_record_count": 10,
            "ehr_days": 600,
            "case_condition": (np.arange(n) < 90).astype(int),
            "condition": rng.binomial(1, 0.3, n),
            "bmi": rng.normal(26, 3, n),
        }
    )
