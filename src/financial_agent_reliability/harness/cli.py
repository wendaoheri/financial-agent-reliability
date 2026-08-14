"""Offline utilities for manifest generation and fixture-only validation."""

from __future__ import annotations

import argparse
import json
import os
import pathlib

from financial_agent_reliability.harness.matrix import build_run_manifest
from financial_agent_reliability.harness.smoke import (
    freeze_smoke_evidence,
    run_live_smoke,
    seed_corrected_v1_block,
    validate_smoke_outputs,
    write_smoke_plan,
)
from financial_agent_reliability.harness.stage3 import freeze_preflight_evidence, run_live_preflights
from financial_agent_reliability.providers.bailian import BailianSettings


ROOT = pathlib.Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("build-manifest")
    manifest.add_argument("--output", type=pathlib.Path)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--output", type=pathlib.Path, required=True)
    freeze_preflight = subparsers.add_parser("freeze-preflight")
    freeze_preflight.add_argument(
        "--preflight", type=pathlib.Path, action="append", required=True
    )
    freeze_preflight.add_argument("--destination", type=pathlib.Path, required=True)
    smoke_plan = subparsers.add_parser("build-smoke-plan")
    smoke_plan.add_argument("--output", type=pathlib.Path, required=True)
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--plan", type=pathlib.Path, required=True)
    smoke.add_argument("--output-dir", type=pathlib.Path, required=True)
    smoke.add_argument("--freeze-destination", type=pathlib.Path, required=True)
    smoke.add_argument("--correct-from-v1", type=pathlib.Path)
    args = parser.parse_args()
    if args.command == "build-manifest":
        result = build_run_manifest(ROOT)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    elif args.command == "preflight":
        settings = BailianSettings.from_env(os.environ)
        result = run_live_preflights(settings)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "counts": result["counts"],
                    "endpoint_id": result["endpoint_id"],
                    "output": args.output.as_posix(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result["status"] == "passed" else 2
    elif args.command == "freeze-preflight":
        bundle = freeze_preflight_evidence(args.preflight, args.destination)
        print(
            json.dumps(
                {
                    "bundle_sha256": bundle.bundle_sha256,
                    "artifacts": len(bundle.artifacts),
                    "destination": args.destination.as_posix(),
                },
                sort_keys=True,
            )
        )
    elif args.command == "build-smoke-plan":
        plan = write_smoke_plan(args.output, ROOT)
        print(
            json.dumps(
                {
                    "plan_sha256": plan["plan_sha256"],
                    "tasks": len(plan["tasks"]),
                    "runs": len(plan["runs"]),
                    "output": args.output.as_posix(),
                },
                sort_keys=True,
            )
        )
    elif args.command == "smoke":
        if args.correct_from_v1:
            correction = seed_corrected_v1_block(
                args.correct_from_v1, args.output_dir, root=ROOT
            )
            print(
                json.dumps(
                    {
                        "corrected_runs": len(correction["corrections"]),
                        "additional_provider_requests": 0,
                        "source_bundle_sha256": correction["source_bundle_sha256"],
                    },
                    sort_keys=True,
                )
            )
        process = run_live_smoke(args.plan, args.output_dir, root=ROOT)
        if not (args.output_dir / "summary.json").is_file():
            return process.returncode or 2
        summary = validate_smoke_outputs(args.plan, args.output_dir, root=ROOT)
        bundle = freeze_smoke_evidence(
            args.plan, args.output_dir, args.freeze_destination, root=ROOT
        )
        print(
            json.dumps(
                {
                    "status": summary["status"],
                    "counts": summary["counts"],
                    "decision": summary["decision"],
                    "bundle_sha256": bundle.bundle_sha256,
                    "bundle_artifacts": len(bundle.artifacts),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return process.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
