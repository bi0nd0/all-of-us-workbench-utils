"""Visible analysis stages and frozen cloud-local provenance."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd
from .analysis import fit_models
from .cohorts import build_cohorts
from .matching import match_groups
from .provenance import ArtifactStore, digest, environment_versions, frame_digest
from .reporting import build_report
from .specs import StudySpec
from .errors import DataContractError


@dataclass
class StudyRun:
    spec: StudySpec
    directory: Path
    synthetic: bool = False

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.store = ArtifactStore(self.directory / "private")
        frozen = self.directory / "frozen-spec.json"
        config = self.spec.model_dump(mode="json")
        if frozen.exists() and digest(json.loads(frozen.read_text())) != digest(config):
            raise DataContractError(
                "Study configuration changed. Use a new version and run directory; preserve the original."
            )
        frozen.write_text(json.dumps(config, indent=2))
        self.manifest = {
            "study": config,
            "synthetic": self.synthetic,
            "environment": environment_versions(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.features = self.cohorts = self.matched = self.results = None

    def extract(self, source, *, reuse=True):
        self._assert_unchanged()
        prepared = source.prepare(self.spec)
        identity = {
            "study": self.spec.model_dump(mode="json"),
            "source": prepared,
            "environment": environment_versions(),
        }
        self.features = self.store.load_frame("features", identity) if reuse else None
        self.manifest["cache_hit"] = self.features is not None
        if self.features is None:
            self.features = source.extract(self.spec)
            self.store.save_frame("features", self.features, identity)
        self.manifest.update(source=prepared, queries=source.jobs, feature_hash=frame_digest(self.features))
        self._save_manifest()
        return {"stage": "extracted", "cache_hit": self.manifest["cache_hit"]}

    def use_synthetic(self, features: pd.DataFrame):
        self._assert_unchanged()
        if not self.synthetic:
            raise DataContractError(
                "Direct DataFrame input is reserved for explicitly synthetic runs in this runner."
            )
        self.features = features.copy(deep=True)
        self.manifest["feature_hash"] = frame_digest(features)
        return {"stage": "synthetic_features_loaded"}

    def reuse_features(self, other: "StudyRun"):
        """Reuse a frozen extraction for a different cohort/model specification, within the same runtime."""
        self._assert_unchanged()
        other._assert_unchanged()
        fields = [
            "age_reference_date",
            "clinical_cutoff",
            "tier",
            "dataset",
            "conditions",
            "measurements",
            "surveys",
        ]
        this = self.spec.model_dump(mode="json")
        that = other.spec.model_dump(mode="json")
        if (
            self.synthetic != other.synthetic
            or other.features is None
            or any(this[k] != that[k] for k in fields)
        ):
            raise DataContractError(
                "Feature reuse requires identical extraction definitions, dates, dataset and data mode."
            )
        if frame_digest(other.features) != other.manifest["feature_hash"]:
            raise DataContractError("Source features changed after extraction; do not reuse them.")
        self.features = other.features.copy(deep=True)
        self.manifest.update(
            feature_hash=other.manifest["feature_hash"],
            source=other.manifest.get("source"),
            reused_from_protocol=other.spec.version,
            cache_hit=True,
            queries=[],
        )
        self._save_manifest()
        return {"stage": "frozen_features_reused"}

    def build_groups(self):
        self._assert_unchanged()
        if self.features is None:
            raise DataContractError("Extract features before building groups.")
        if frame_digest(self.features) != self.manifest["feature_hash"]:
            raise DataContractError(
                "Features changed after extraction. Start a new run with explicit inputs."
            )
        self.cohorts = build_cohorts(self.features, self.spec)
        self.manifest["cohort_hashes"] = {
            role: frame_digest(getattr(self.cohorts, role)) for role in ("cases", "controls", "eligible")
        }
        return {"stage": "groups_built"}

    def match(self):
        self._assert_unchanged()
        if self.cohorts is None:
            raise DataContractError("Build groups before matching.")
        if any(
            frame_digest(getattr(self.cohorts, role)) != expected
            for role, expected in self.manifest["cohort_hashes"].items()
        ):
            raise DataContractError(
                "Cohort data changed after group construction. Rebuild from frozen inputs."
            )
        self.matched = match_groups(self.cohorts, self.spec.matching)
        self.manifest["matching"] = self.matched.metadata
        self.manifest["membership_hash"] = frame_digest(self.matched.members)
        self.store.save_frame("members", self.matched.members, self.manifest["membership_hash"])
        self.store.save_frame("unmatched", self.matched.unmatched, self.manifest["membership_hash"])
        self.store.save_frame("balance", self.matched.balance, self.manifest["membership_hash"])
        self._save_manifest()
        return {"stage": "matched", "criteria_validated": True}

    def analyze(self):
        self._assert_unchanged()
        if self.matched is None:
            raise DataContractError("Match groups before analysis.")
        if frame_digest(self.matched.members) != self.manifest["membership_hash"]:
            raise DataContractError("Matched data changed after matching. Rebuild from frozen inputs.")
        self.results = fit_models(self.matched, self.spec.models)
        self.manifest["result_hash"] = frame_digest(self.results)
        # Full numerical results are private; no formatted number feeds further calculations.
        self.results.to_json(self.directory / "private" / "model-results.json", orient="records", indent=2)
        self._save_manifest()
        return {"stage": "analyzed", "all_estimable": bool(self.results.status.eq("estimated").all())}

    def report(self, *, spec=None):
        self._assert_unchanged()
        if self.results is None:
            raise DataContractError("Analyze before building review tables.")
        if (
            frame_digest(self.results) != self.manifest["result_hash"]
            or frame_digest(self.matched.members) != self.manifest["membership_hash"]
        ):
            raise DataContractError("Analysis inputs or results changed. Regenerate from frozen inputs.")
        flow = {
            **self.cohorts.flow,
            "matched_cases": self.matched.metadata["matched_cases"],
            "matched_controls": self.matched.metadata["controls"],
        }
        report = build_report(self.matched, self.results, flow, self.spec, spec)
        report.metadata["synthetic"] = self.synthetic
        report.write(self.directory / "review")
        return {
            "stage": "review_tables_written",
            "review_status": report.review_status,
            "workbook": str(self.directory / "review" / "tables.xlsx"),
            "snapshot": str(self.directory / "review" / "report.json"),
        }

    def _save_manifest(self):
        (self.directory / "private" / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2, default=str)
        )

    def _assert_unchanged(self):
        if digest(self.spec.model_dump(mode="json")) != digest(self.manifest["study"]):
            raise DataContractError(
                "Study configuration mutated during this run. Start a new protocol version."
            )


def sensitivity_spec(base: StudySpec, *, version: str, **changes) -> StudySpec:
    """Explicit new protocol identity; rebuild groups and rematch for changed eligibility/phenotype."""
    if version == base.version:
        raise DataContractError("Sensitivity specifications require a distinct version.")
    return StudySpec.model_validate({**base.model_dump(mode="json"), **changes, "version": version})
