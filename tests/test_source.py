from types import SimpleNamespace as NS
from datetime import date
import pandas as pd
import pytest
from aou_studies.source import BigQuerySource, REQUIRED_SCHEMA
from aou_studies.context import WorkspaceContext, LATEST
from aou_studies.errors import DataContractError, ContextError


class FakeClient:
    def __init__(self):
        self.missing = None
        self.calls = []

    def get_dataset(self, _):
        return NS(location="us-central1")

    def get_table(self, name):
        table = name.split(".")[-1]

        def kind(col):
            if col.endswith(("_date", "_datetime")):
                return "DATE"
            if col in {"domain_id", "vocabulary_id"}:
                return "STRING"
            if col.endswith("_id"):
                return "INTEGER"
            if col == "value_as_number":
                return "FLOAT"
            return "STRING"

        return NS(
            schema=[NS(name=c, field_type=kind(c)) for c in REQUIRED_SCHEMA[table] if c != self.missing]
        )

    def query(self, sql, job_config, location):
        self.calls.append((sql, job_config, location))
        return NS(job_id="synthetic", total_bytes_processed=123, cache_hit=False)


def source():
    return BigQuerySource(
        WorkspaceContext(LATEST["registered"], "my-project-123", "registered", "test"), client=FakeClient()
    )


def test_preflight_schema_location_and_release(study):
    s = source()
    info = s.preflight(study)
    assert info["context"]["location"] == "us-central1"
    s.client.missing = "person_id"
    with pytest.raises(DataContractError):
        s.preflight(study)


def test_query_parameters_cap_and_current_omop(study):
    s = source()
    s.preflight(study)
    s.resolved_concepts = {"case_condition": {"ids": [1]}, "condition": {"ids": [2]}}
    sql, params = s.extraction_query(study)
    assert all(x not in sql for x in ["cb_", "ds_", "all_events"])
    assert "condition_start_date <= @cutoff" in sql and "IN UNNEST(@condition_ids)" in sql
    s.query(sql, params, dry_run=True)
    _, config, location = s.client.calls[0]
    assert location == "us-central1" and config.maximum_bytes_billed == 10_000_000_000
    assert next(p for p in config.query_parameters if p.name == "cutoff").value == date(2025, 1, 1)
    s.maximum_bytes_billed = 100
    with pytest.raises(DataContractError):
        s.query(sql, params, dry_run=True)


def test_queries_require_preflight():
    with pytest.raises(ContextError):
        source().query("SELECT 1")


def test_invalid_seed_is_not_silently_mapped(study):
    s = source()
    s.preflight(study)
    s.query = lambda *_: pd.DataFrame(
        [
            {
                "concept_id": 1,
                "concept_name": "x",
                "domain_id": "Drug",
                "vocabulary_id": "SNOMED",
                "concept_code": "x",
                "standard_concept": "S",
                "invalid_reason": None,
            }
        ]
    )
    with pytest.raises(DataContractError):
        s.resolve_concepts(study.conditions["case_condition"].concepts)
