"""Documented Workbench resource resolution with explicit, frozen source identity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping

from .errors import ContextError

DOCUMENTATION_URL = "https://support.researchallofus.org/hc/en-us/articles/360033200232-Data-Dictionaries"
CATALOG_VERIFIED = "2026-09-08"
LATEST = {"registered": "wb-affable-acorn-7941.R2025Q4R6", "controlled": "wb-silky-artichoke-2408.C2025Q4R6"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]\.[A-Za-z_][A-Za-z0-9_]*$")
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")


def normalize_dataset(value: str) -> str:
    value = value.removeprefix("bq://").strip().strip("`")
    if not IDENTIFIER.fullmatch(value):
        raise ContextError("Dataset must be project_id.dataset_id (or bq://project_id.dataset_id).")
    return value


def _wb(args: list[str]) -> str:
    if not shutil.which("wb"):
        raise ContextError("Workbench CLI 'wb' is unavailable. Pass dataset and billing_project explicitly.")
    result = subprocess.run(["wb", *args], capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise ContextError(
            "Workbench resource discovery failed. Check wb auth status and workspace selection."
        )
    return result.stdout.strip()


@dataclass(frozen=True)
class WorkspaceContext:
    dataset: str
    billing_project: str
    tier: str
    resolved_from: str
    location: str | None = None
    catalog_verified: str = CATALOG_VERIFIED

    def __post_init__(self):
        normalize_dataset(self.dataset)
        if not PROJECT.fullmatch(self.billing_project):
            raise ContextError("Provide the workspace billing project ID, not the CDR source project.")
        if self.tier not in LATEST:
            raise ContextError("Tier must be registered or controlled.")

    def summary(self) -> dict:
        """Safe metadata only; never dump the environment or credentials."""
        return asdict(self)

    def require_release(self, *, pinned: str | None = None, cutoff: date | None = None):
        expected = normalize_dataset(pinned) if pinned else LATEST[self.tier]
        if self.dataset != expected:
            raise ContextError(
                f"Resolved dataset differs from {'frozen' if pinned else 'latest verified'} release. "
                "Select the intended resource explicitly; revisions must not silently upgrade."
            )
        prefix = self.dataset.split(".")[-1][:1]
        if prefix in {"R", "C"} and prefix != {"registered": "R", "controlled": "C"}[self.tier]:
            raise ContextError("Dataset identifier conflicts with selected access tier.")
        if self.dataset in LATEST.values() and cutoff and cutoff > date(2025, 1, 1):
            raise ContextError(
                "v9 documented clinical data cutoff is 2025-01-01; revise the clinical cutoff."
            )


def discover_context(
    *,
    dataset: str | None = None,
    billing_project: str | None = None,
    tier: str = "registered",
    resource: str | None = None,
    location: str | None = None,
    environ: Mapping[str, str] | None = None,
    cli=_wb,
) -> WorkspaceContext:
    """Resolve explicit values, a named Workbench resource, then validated context globals.

    No network call occurs when explicit values are provided. Missing/ambiguous
    resources fail rather than selecting an arbitrary CDR or billing project.
    Call `require_release` and BigQuerySource.preflight before extracting data.
    """
    env = os.environ if environ is None else environ
    origin = "explicit"
    if dataset is None and resource:
        dataset = cli(["resource", "resolve", f"--id={resource}"])
        origin = "wb resource resolve"
    if dataset is None:
        candidates = {
            normalize_dataset(v)
            for k, v in env.items()
            if k.startswith("WORKBENCH_") and (v.startswith("bq://") or IDENTIFIER.fullmatch(v))
        }
        candidates = {v for v in candidates if re.match(r"[RC]\d{4}Q\dR\d+$", v.split(".")[-1])}
        if candidates:
            expected = LATEST.get(tier)
            if len(candidates) != 1:
                raise ContextError("Multiple CDR references found. Pass dataset or resource explicitly.")
            dataset = candidates.pop()
            if dataset != expected:
                raise ContextError(
                    "Workspace context is not the latest verified CDR; select a resource explicitly."
                )
            origin = "WORKBENCH resource variable"
        elif env.get("WORKSPACE_CDR"):
            dataset = env["WORKSPACE_CDR"]
            origin = "legacy WORKSPACE_CDR (requires release validation)"
        else:
            raise ContextError(
                "No CDR reference found. Run 'wb resource list', then pass resource= or dataset=. "
                "Workbench 2.0 does not guarantee WORKSPACE_CDR."
            )
    if billing_project is None:
        billing_project = env.get("GOOGLE_CLOUD_PROJECT") or env.get("GOOGLE_PROJECT")
    if billing_project is None:
        raw = json.loads(cli(["workspace", "describe", "--format=json"]))
        billing_project = (raw.get("gcpContext") or {}).get("projectId")
        if not billing_project:
            raise ContextError(
                "Cannot resolve workspace billing project; inspect wb workspace describe and pass it."
            )
    return WorkspaceContext(normalize_dataset(dataset), billing_project, tier, origin, location)
