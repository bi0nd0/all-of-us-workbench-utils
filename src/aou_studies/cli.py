import argparse
import json
from .specs import StudySpec
from .runner import StudyRun
from .synthetic import synthetic_features
from .provenance import environment_versions


def main():
    parser = argparse.ArgumentParser(
        description="Validate or run a synthetic study. Real extraction runs inside Workbench."
    )
    parser.add_argument("command", choices=["validate", "synthetic", "versions"])
    parser.add_argument("--config")
    parser.add_argument("--output", default="outputs/synthetic")
    args = parser.parse_args()
    if args.command == "versions":
        print(json.dumps(environment_versions(), indent=2))
        return
    if not args.config:
        parser.error("--config is required")
    spec = StudySpec.load(args.config)
    if args.command == "validate":
        print("Study configuration is valid.")
        return
    run = StudyRun(spec, args.output, synthetic=True)
    run.use_synthetic(synthetic_features(spec))
    for stage in [run.build_groups, run.match, run.analyze, run.report]:
        print(json.dumps(stage()))
