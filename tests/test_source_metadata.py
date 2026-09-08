from pathlib import Path
import json
import pandas as pd
import pytest
from aou_studies.source import BigQuerySource, REQUIRED_SCHEMA
from aou_studies.context import WorkspaceContext, LATEST
from aou_studies.specs import SurveyFeature
from aou_studies.errors import DataContractError


def test_required_fields_exist_in_official_dictionary_snapshot():
    dictionary = json.loads(Path("docs/v9-schema-reference.json").read_text())["fields"]
    for table, columns in REQUIRED_SCHEMA.items():
        assert columns.issubset(dictionary[table]), (table, columns - dictionary[table].keys())
    assert dictionary["concept"]["domain_id"].startswith("varchar")
    assert dictionary["concept"]["vocabulary_id"].startswith("varchar")


def test_survey_source_code_resolution_and_collision():
    source = BigQuerySource(
        WorkspaceContext(LATEST["registered"], "my-project-123", "registered", "test"), client=object()
    )
    records = pd.DataFrame(
        [
            {
                "concept_id": 101,
                "concept_code": "Smoking_Example",
                "concept_name": "Question",
                "vocabulary_id": "PPI",
                "invalid_reason": None,
            },
            {
                "concept_id": 102,
                "concept_code": "Example_Yes",
                "concept_name": "Yes",
                "vocabulary_id": "PPI",
                "invalid_reason": None,
            },
            {
                "concept_id": 103,
                "concept_code": "Example_No",
                "concept_name": "No",
                "vocabulary_id": "PPI",
                "invalid_reason": None,
            },
        ]
    )
    source.query = lambda *args, **kwargs: records
    spec = SurveyFeature(
        positive_codes={"smoking_example": ["Example_Yes"]},
        negative_codes={"smoking_example": ["Example_No"]},
    )
    resolved, metadata = source.resolve_survey(spec)
    assert resolved.positive == {101: (102,)}
    assert resolved.negative == {101: (103,)}
    assert len(metadata["records"]) == 3
    records.loc[3] = {**records.iloc[0].to_dict(), "concept_id": 104}
    with pytest.raises(DataContractError, match="ambiguous"):
        source.resolve_survey(spec)
