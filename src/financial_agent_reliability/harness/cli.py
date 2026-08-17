"""Configuration-driven preflight CLI for the benchmark harness.

PER-323 Stage 2: the baseline-v1 subcommands tied to the removed frozen
directories (``build-manifest``, ``build-smoke-plan``, ``smoke``) retired with
the v3.x acceptance chain (cleanup list M2). ``preflight`` now runs from
``configs/inference.json`` (+ ``configs/harness_contract.v1.json``);
configuration failures exit with a structured error instead of a raw
traceback (Stage 1b finding F7).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib

from financial_agent_reliability.harness.stage3 import (
    freeze_preflight_evidence,
    run_live_preflights,
)
from financial_agent_reliability.providers.bailian import BailianConfigError, BailianSettings


def _emit_config_error(message: str) -> int:
    print(
        json.dumps(
            {"status": "config_error", "error": message},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    from financial_agent_reliability.inference_config import (
        InferenceConfigError,
        load_inference_config,
    )

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--output", type=pathlib.Path, required=True)
    preflight.add_argument("--config", type=pathlib.Path, default=None)
    freeze_preflight = subparsers.add_parser("freeze-preflight")
    freeze_preflight.add_argument(
        "--preflight", type=pathlib.Path, action="append", required=True
    )
    freeze_preflight.add_argument("--destination", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "preflight":
        try:
            config = load_inference_config(args.config, env=os.environ)
            settings = BailianSettings.from_config(config, os.environ)
        except (InferenceConfigError, BailianConfigError) as exc:
            return _emit_config_error(str(exc))
        result = run_live_preflights(settings, config=config)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "counts": result["counts"],
                    "endpoint_id": result["endpoint_id"],
                    "inference_config_sha256": result["inference_config_sha256"],
                    "harness_contract_sha256": result["harness_contract_sha256"],
                    "output": args.output.as_posix(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result["status"] == "passed" else 2
    if args.command == "freeze-preflight":
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
