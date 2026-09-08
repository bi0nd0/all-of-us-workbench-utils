from datetime import date
import pytest
from pydantic import ValidationError
from aou_studies import StudySpec, ConceptSet
from aou_studies.context import discover_context, LATEST, WorkspaceContext
from aou_studies.errors import ContextError


def test_frozen_date_and_unknown_config(study_dict):
    s = StudySpec.model_validate(study_dict)
    assert s.age_reference_date == date(2026, 9, 7)
    with pytest.raises(ValidationError):
        StudySpec.model_validate({**study_dict, "age_refrence_date": "2027-01-01"})
    with pytest.raises(ValidationError):
        s.age_reference_date = date(2027, 1, 1)
    with pytest.raises(ValidationError):
        ConceptSet(ids=[])
    with pytest.raises(ValidationError):
        StudySpec.model_validate({**study_dict, "clinical_cutoff": "2027-01-01"})


def test_explicit_context_no_cli():
    def forbidden(_):
        raise AssertionError("Unexpected CLI call")

    c = discover_context(
        dataset=LATEST["registered"], billing_project="my-workspace-123", environ={}, cli=forbidden
    )
    c.require_release(cutoff=date(2025, 1, 1))
    assert c.resolved_from == "explicit"
    with pytest.raises(ContextError):
        c.require_release(cutoff=date(2026, 1, 1))


def test_named_resource_and_billing():
    seen = []

    def cli(args):
        seen.append(args)
        return (
            "bq://" + LATEST["registered"]
            if args[0] == "resource"
            else '{"gcpContext":{"projectId":"my-project-123"}}'
        )

    c = discover_context(resource="current_cdr", environ={}, cli=cli)
    assert c.dataset == LATEST["registered"] and c.billing_project == "my-project-123"
    assert seen[0] == ["resource", "resolve", "--id=current_cdr"]


def test_missing_and_ambiguous_globals():
    with pytest.raises(ContextError):
        discover_context(environ={})
    env = {
        "WORKBENCH_v8": "bq://wb-affable-acorn-7941.R2024Q3R9",
        "WORKBENCH_v9": "bq://" + LATEST["registered"],
        "GOOGLE_CLOUD_PROJECT": "my-project-123",
    }
    with pytest.raises(ContextError):
        discover_context(environ=env)
    c = discover_context(
        environ={"WORKBENCH_v9": env["WORKBENCH_v9"], "GOOGLE_CLOUD_PROJECT": "my-project-123"}
    )
    assert c.dataset == LATEST["registered"]


def test_stale_legacy_and_tier_validation():
    c = discover_context(
        environ={"WORKSPACE_CDR": "wb-affable-acorn-7941.R2024Q3R9", "GOOGLE_PROJECT": "my-project-123"}
    )
    with pytest.raises(ContextError):
        c.require_release()
    wrong = WorkspaceContext(LATEST["controlled"], "my-project-123", "registered", "test")
    with pytest.raises(ContextError):
        wrong.require_release(pinned=LATEST["controlled"])
