"""Execute generated OMOP SQL against literal synthetic fixtures in BigQuery.

Run inside Workbench with --billing-project. No AoU table is read and no dataset
is created. BigQuery's temporary query results remain in the billing project.
This validates SQL/feature semantics, not access to the real CDR or its metadata.
"""

from __future__ import annotations

import argparse
from datetime import date
from types import SimpleNamespace
import pandas as pd
from google.cloud import bigquery
from aou_studies.context import WorkspaceContext, LATEST
from aou_studies.source import BigQuerySource, REQUIRED_SCHEMA
from aou_studies.specs import StudySpec
from aou_studies.cohorts import build_cohorts


def fixture_tables():
    columns = {
        "person": {
            "person_id": "INT64",
            "birth_datetime": "TIMESTAMP",
            "sex_at_birth_concept_id": "INT64",
            "race_concept_id": "INT64",
            "ethnicity_concept_id": "INT64",
        },
        "condition_occurrence": {
            "person_id": "INT64",
            "condition_concept_id": "INT64",
            "condition_start_date": "DATE",
        },
        "visit_occurrence": {"person_id": "INT64", "visit_start_date": "DATE"},
        "concept": {
            "concept_id": "INT64",
            "concept_name": "STRING",
            "domain_id": "STRING",
            "vocabulary_id": "STRING",
            "concept_code": "STRING",
            "standard_concept": "STRING",
            "invalid_reason": "STRING",
        },
        "concept_ancestor": {"ancestor_concept_id": "INT64", "descendant_concept_id": "INT64"},
        "observation": {
            "person_id": "INT64",
            "observation_date": "DATE",
            "observation_source_concept_id": "INT64",
            "value_source_concept_id": "INT64",
            "value_as_number": "FLOAT64",
            "value_as_string": "STRING",
        },
        "measurement": {
            "person_id": "INT64",
            "measurement_concept_id": "INT64",
            "measurement_date": "DATE",
            "value_as_number": "FLOAT64",
            "unit_concept_id": "INT64",
        },
    }
    concepts = [
        (1, "Synthetic case", "Condition", "SNOMED", "toy-case", "S", None),
        (2, "Synthetic condition", "Condition", "SNOMED", "toy-condition", "S", None),
        (3, "Synthetic BMI", "Measurement", "LOINC", "toy-bmi", "S", None),
        (4, "Synthetic unit", "Unit", "UCUM", "kg/m2", "S", None),
        (10, "Synthetic sex", "Gender", "Gender", "toy-sex", "S", None),
        (11, "Synthetic race", "Race", "Race", "toy-race", "S", None),
        (12, "Synthetic ethnicity", "Ethnicity", "Ethnicity", "toy-ethnicity", "S", None),
        (100, "Synthetic question", "Observation", "PPI", "toy-question", None, None),
        (101, "Synthetic yes", "Observation", "PPI", "toy-yes", None, None),
        (102, "Synthetic no", "Observation", "PPI", "toy-no", None, None),
    ]
    rows = {
        "person": [
            (1, "1980-09-08", 10, 11, 12),
            (2, "2010-01-01", 10, 11, 12),
            (3, "1975-01-01", 10, 11, 12),
            (4, "1980-01-01", 10, 11, 12),
            (5, None, 10, 11, 12),
            (6, "2007-01-02", 10, 11, 12),
        ],
        "condition_occurrence": [
            (1, 1, "2024-01-01"),
            (1, 1, "2024-01-01"),
            (1, 1, "2024-02-15"),
            (1, 2, "2024-01-05"),
            (2, 1, "2024-01-01"),
            (2, 2, "2026-01-01"),
        ],
        "visit_occurrence": [(3, "2024-05-01"), (5, "2024-05-01"), (6, "2024-05-01")],
        "concept": concepts,
        "concept_ancestor": [(1, 1), (2, 2), (3, 3)],
        "observation": [
            (1, "2024-01-01", 100, 102, None, None),
            (1, "2024-12-01", 100, 101, None, None),
            (2, "2024-01-01", 100, 102, None, None),
            (3, "2024-01-01", 100, 101, None, None),
            (3, "2024-01-01", 100, 102, None, None),
        ],
        "measurement": [
            (1, 3, "2024-12-30", 26, 4),
            (1, 3, "2024-12-30", 27, 4),
            (3, 3, "2023-01-01", 20, 4),
            (3, 3, "2024-06-01", 30, 4),
            (3, 3, "2024-12-31", 999, 4),
            (3, 3, "2024-12-31", 25, 999),
        ],
    }
    return columns, rows


def literal_table(columns, rows):
    def literal(value, kind):
        if value is None:
            return f"CAST(NULL AS {kind})"
        if kind in {"INT64", "FLOAT64"}:
            return f"CAST({value} AS {kind})"
        # Only fixed, source-controlled synthetic strings enter this function.
        return f"CAST('{str(value).replace(chr(39), chr(39) * 2)}' AS {kind})"

    structs = [
        "STRUCT("
        + ", ".join(f"{literal(v, kind)} AS {col}" for (col, kind), v in zip(columns.items(), row))
        + ")"
        for row in rows
    ]
    return "(SELECT * FROM UNNEST([" + ", ".join(structs) + "]))"


class LiteralFixtureClient:
    """Replace every supported source reference; reject an unreplaced CDR reference."""

    def __init__(self, project, location):
        self.client = bigquery.Client(project=project)
        self.location = location
        self.columns, self.rows = fixture_tables()

    def get_dataset(self, _):
        return SimpleNamespace(location=self.location)

    def get_table(self, table):
        name = table.split(".")[-1]
        return SimpleNamespace(schema=[bigquery.SchemaField(k, v) for k, v in self.columns[name].items()])

    def query(self, sql, **kwargs):
        for table in REQUIRED_SCHEMA:
            ref = f"`{LATEST['registered']}.{table}`"
            sql = sql.replace(ref, literal_table(self.columns[table], self.rows[table]))
        if LATEST["registered"] in sql:
            raise ValueError("An unrecognized source reference was not replaced with synthetic literals.")
        return self.client.query(sql, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--billing-project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--maximum-bytes-billed", type=int, default=100_000_000)
    args = parser.parse_args()
    spec = StudySpec.model_validate(
        {
            "study_id": "literal_sql_fixture",
            "version": "1",
            "age_reference_date": "2026-09-07",
            "clinical_cutoff": "2025-01-01",
            "tier": "registered",
            "case": {"field": "case_condition", "value": 1},
            "control": {"field": "any_case", "value": 0},
            "conditions": {
                "case_condition": {"concepts": {"ids": [1]}, "min_distinct_dates": 2, "min_span_days": 30},
                "any_case": {"concepts": {"ids": [1]}},
                "condition": {"concepts": {"ids": [2]}},
            },
            "measurements": {
                "bmi": {
                    "concepts": {"ids": [3], "domain": "Measurement", "vocabulary": "LOINC"},
                    "unit_codes": ["kg/m2"],
                    "minimum": 10,
                    "maximum": 80,
                    "lookback_days": 365,
                }
            },
            "surveys": {"smoking": {"positive": {100: [101]}, "negative": {100: [102]}}},
            "models": [{"name": "primary", "predictors": ["condition"], "primary": True}],
        }
    )
    client = LiteralFixtureClient(args.billing_project, args.location)
    context = WorkspaceContext(
        LATEST["registered"], args.billing_project, "registered", "literal synthetic fixture", args.location
    )
    source = BigQuerySource(context, client=client, maximum_bytes_billed=args.maximum_bytes_billed)
    source.prepare(spec)
    data = source.extract(spec).set_index("person_id", drop=False)
    assert set(data.index) == {"1", "2", "3", "5", "6"}
    assert data.loc["1", "case_condition"] == 1 and data.loc["1", "case_condition__days"] == 2
    assert data.loc["2", "case_condition"] == 0 and data.loc["2", "condition"] == 0
    assert data.loc["1", "age"] == 45 and data.loc["1", "age_at_cutoff"] == 44
    assert data.loc["1", "smoking"] == "yes" and data.loc["3", "smoking"] == "conflict"
    assert pd.isna(data.loc["1", "bmi"]) and data.loc["3", "bmi"] == 30
    groups = build_cohorts(data.reset_index(drop=True), spec)
    assert groups.cases.person_id.tolist() == ["1"]
    assert groups.controls.person_id.tolist() == ["3"]
    print(
        {
            "synthetic_bigquery_contract": "passed",
            "real_cdr_tables_read": False,
            "queries": len(source.jobs),
            "clinical_cutoff": str(date(2025, 1, 1)),
        }
    )


if __name__ == "__main__":
    main()
