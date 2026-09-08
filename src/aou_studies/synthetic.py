"""Generated participants only. No All of Us observations or copied distributions."""

import numpy as np
import pandas as pd
from .specs import StudySpec
from .provenance import digest


def synthetic_features(spec: StudySpec, n=1200, seed=419) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.integers(24, 79, n)
    data = pd.DataFrame(
        {
            "person_id": [f"synthetic_{i:06d}" for i in range(n)],
            "age": age,
            "age_at_cutoff": age - 2,
            "sex_at_birth": rng.choice(["female", "male"], n),
            "race": rng.choice(["synthetic_race_a", "synthetic_race_b"], n),
            "ethnicity": rng.choice(["synthetic_ethnicity_a", "synthetic_ethnicity_b"], n),
            "ehr_record_count": rng.integers(5, 300, n),
            "ehr_days": rng.integers(60, 1800, n),
        }
    )
    events = {}
    for i, (name, rule) in enumerate(spec.conditions.items()):
        key = digest(rule.concepts.model_dump(mode="json"))
        if key not in events:
            present = rng.binomial(1, 0.18 if i == 0 else 0.3, n)
            events[key] = (present * rng.integers(1, 6, n), present * rng.integers(0, 500, n))
        days, span = events[key]
        data[name] = ((days >= rule.min_distinct_dates) & (span >= rule.min_span_days)).astype(int)
        data[f"{name}__days"] = days
        data[f"{name}__span"] = span
    for name in spec.measurements:
        data[name] = rng.normal(26, 4, n)
        data.loc[rng.random(n) < 0.12, name] = np.nan
    for name, rule in spec.surveys.items():
        data[name] = rng.choice(
            [rule.positive_label, rule.negative_label, rule.unknown_label], n, p=[0.25, 0.65, 0.1]
        )
    return data
