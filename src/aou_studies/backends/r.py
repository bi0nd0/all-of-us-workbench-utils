"""A subprocess boundary keeps R engine dependencies and data custody explicit."""

from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from ..errors import EngineError


def run_r(frame, request: dict, *, timeout=600) -> dict:
    executable = os.environ.get("AOU_RSCRIPT") or shutil.which("Rscript")
    if not executable:
        raise EngineError("Rscript is required. Follow docs/installation.md to install the locked R engines.")
    # For real data this directory must be on the authorized Workbench filesystem.
    with tempfile.TemporaryDirectory(prefix="aou-studies-") as directory:
        root = Path(directory)
        request_file, data_file, output_file = [root / v for v in ["request.json", "data.csv", "result.json"]]
        request_file.write_text(json.dumps(request))
        frame.to_csv(data_file, index=False)
        script = files("aou_studies").joinpath("backends/engine.R")
        try:
            env = dict(os.environ)
            if env.get("AOU_R_LIBRARY"):
                env["R_LIBS_USER"] = env["AOU_R_LIBRARY"]
            process = subprocess.run(
                [executable, str(script), str(request_file), str(data_file), str(output_file)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise EngineError("R engine could not finish. Check Rscript and the runtime resources.") from exc
        if not output_file.exists():
            raise EngineError(
                "R engine did not produce a result. Verify package installation and runtime compatibility."
            )
        result = json.loads(output_file.read_text())
        if process.returncode or result.get("status") != "ok":
            # Engine errors can contain participant-level values: do not echo raw stderr/message.
            raise EngineError(
                "R engine failed. Inspect the private Workbench runtime; no estimator was substituted."
            )
        result["engine_warning"] = bool(process.stderr.strip())
        return result
