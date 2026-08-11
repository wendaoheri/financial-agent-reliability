"""Offline utilities for manifest generation and fixture-only validation."""

from __future__ import annotations

import argparse
import json
import pathlib

from harness.matrix import build_run_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("build-manifest")
    manifest.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.command == "build-manifest":
        result = build_run_manifest(ROOT)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
