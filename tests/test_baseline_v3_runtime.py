"""Executable run_trace v5 bridge for baseline v3 (PER-329)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "v3"))

import validate_baseline_v3 as validator  # noqa: E402

from financial_agent_reliability.harness.bundle import ImmutableBundle  # noqa: E402
from financial_agent_reliability.harness.hashing import file_sha256  # noqa: E402
from financial_agent_reliability.harness.runner import OfflineHarness  # noqa: E402
from financial_agent_reliability.providers.bailian import (  # noqa: E402
    BailianAdapter,
    BailianSettings,
)


class BaselineV3RunTraceTests(unittest.TestCase):
    def test_offline_runner_emits_trace_v5_with_actual_config_hashes(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-value-never-persist",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": json.dumps(
                ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
            ),
        }
        adapter = BailianAdapter(BailianSettings.from_env(env), "qwen3.8-max")

        def preflight(request):
            return {
                "model": request["model"],
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": True,
            }

        def inference(request):
            return {
                "model": request["model"],
                "output": "Synthetic fixture answer; no external action.",
                "action": "answer",
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "cost": {"input_usd": "0.000000", "output_usd": "0.000000"},
            }

        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            source = temp / "source"
            source.mkdir()
            case_path = ROOT / "baseline/v3/cases/case-ftw3-syn-01-normal-v3.json"
            (source / "case.json").write_bytes(case_path.read_bytes())
            bundle = ImmutableBundle.create(source, temp / "bundle")
            harness = OfflineHarness(
                adapter,
                bundle,
                temp / "checkpoints",
                baseline_generation="v3",
            )
            trace = harness.run(
                case_id="case-ftw3-syn-01-normal-v3",
                variant_id="normal",
                repeat=1,
                seed=20260811,
                frozen_input_path="case.json",
                preflight_transport=preflight,
                inference_transport=inference,
            )
            trace_path = temp / "trace.json"
            trace_path.write_text(
                json.dumps(trace, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )

            self.assertEqual(validator.verify_trace(trace_path), [])
            self.assertEqual(trace["contract_version"], "5.0.0")
            self.assertEqual(
                trace["run_identity"]["benchmark_id"],
                "financial-agent-reliability-v3",
            )
            self.assertEqual(
                trace["run_identity"]["inference_config_sha256"],
                file_sha256(ROOT / "configs/inference.json"),
            )
            self.assertEqual(
                trace["run_identity"]["harness_contract_sha256"],
                file_sha256(ROOT / "configs/harness_contract.v1.json"),
            )
            self.assertEqual(
                trace["run_identity"]["immutable_bundle_sha256"],
                bundle.bundle_sha256,
            )

    def test_unknown_baseline_generation_is_rejected(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-value-never-persist",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
        }
        adapter = BailianAdapter(BailianSettings.from_env(env), "qwen3.8-max")
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            source = temp / "source"
            source.mkdir()
            (source / "case.json").write_text("{}", encoding="utf-8")
            bundle = ImmutableBundle.create(source, temp / "bundle")
            with self.assertRaisesRegex(ValueError, "baseline_generation"):
                OfflineHarness(
                    adapter,
                    bundle,
                    temp / "checkpoints",
                    baseline_generation="v4",
                )


if __name__ == "__main__":
    unittest.main()
