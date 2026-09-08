"""Content-addressed, cloud-local artifacts; no automatic export of research data."""

from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import platform
import re
import pandas as pd
from importlib.resources import files
from .errors import DataContractError


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def frame_digest(df: pd.DataFrame) -> str:
    canonical = df.reindex(sorted(df.columns), axis=1).astype("string").fillna("<NA>")
    canonical = canonical.sort_values(list(canonical.columns), kind="stable").reset_index(drop=True)
    return hashlib.sha256(pd.util.hash_pandas_object(canonical, index=False).values.tobytes()).hexdigest()


def environment_versions() -> dict:
    names = ["all-of-us-workbench-utils", "pandas", "numpy", "statsmodels", "scipy", "google-cloud-bigquery"]
    result = {"python": platform.python_version()}
    for name in names:
        try:
            result[name] = version(name)
        except Exception:
            result[name] = "uninstalled"
    package = Path(str(files("aou_studies")))
    source = hashlib.sha256()
    for path in sorted(p for p in package.rglob("*") if p.suffix in {".py", ".R"}):
        source.update(str(path.relative_to(package)).encode())
        source.update(path.read_bytes())
    result["aou_studies_source_sha256"] = source.hexdigest()
    return result


class ArtifactStore:
    """Use permitted Workbench paths for real data; use local paths for synthetic data only."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save_frame(self, name: str, frame: pd.DataFrame, identity: dict):
        self._validate_name(name)
        path = self.directory / f"{name}.parquet"
        temporary = path.with_suffix(".parquet.tmp")
        frame.to_parquet(temporary, index=False)
        temporary.replace(path)
        metadata = {
            "identity": digest(identity),
            "content": frame_digest(frame),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path.with_suffix(".json").write_text(json.dumps(metadata, indent=2))

    def load_frame(self, name: str, identity: dict) -> pd.DataFrame | None:
        self._validate_name(name)
        path = self.directory / f"{name}.parquet"
        metadata_path = path.with_suffix(".json")
        if not path.exists() and not metadata_path.exists():
            return None
        if not path.exists() or not metadata_path.exists():
            raise DataContractError("Incomplete cached artifact; regenerate it explicitly.")
        metadata = json.loads(metadata_path.read_text())
        if metadata["identity"] != digest(identity):
            return None
        frame = pd.read_parquet(path)
        if frame_digest(frame) != metadata["content"]:
            raise DataContractError("Cached content hash differs; do not reuse this artifact.")
        return frame

    @staticmethod
    def _validate_name(name):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise DataContractError("Artifact names must be simple lowercase identifiers.")
