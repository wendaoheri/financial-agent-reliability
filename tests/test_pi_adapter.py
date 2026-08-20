from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from financial_agent_reliability.adapters.pi import PiAgentLiveAdapter
from financial_agent_reliability.cli import _bind_live_preflight, main
from financial_agent_reliability.models import load_candidates
from financial_agent_reliability.trace import read_traces

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "dev" / "tasks.jsonl"
PI_CONFIG = ROOT / "configs" / "pi-offline.json"
PI_LIVE_CONFIG = ROOT / "configs" / "pi-bailian-pilot.json"
PI_CALIBRATION_CONFIG = ROOT / "configs" / "pi-bailian-calibration-v2.json"
PHASE0_SLICES = ("fundamentals", "news_filings", "portfolio")


class PiAgentOfflineTests(unittest.TestCase):
    def test_config_declares_three_models_on_one_pinned_agent_axis(self):
        candidates = load_candidates(PI_CONFIG)
        self.assertEqual(
            {candidate.model for candidate in candidates},
            {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"},
        )
        self.assertEqual({candidate.agent for candidate in candidates}, {"pi-agent-0.73.1"})
        self.assertEqual({candidate.adapter for candidate in candidates}, {"pi-agent-offline"})

    def test_phase0_six_case_matrix_uses_real_pi_tool_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = pathlib.Path(temporary) / "pi-phase0.jsonl"
            arguments = [
                "run",
                "--tasks",
                str(TASKS),
                "--config",
                str(PI_CONFIG),
                "--output",
                str(trace_path),
                "--run-id",
                "pi-phase0-test",
            ]
            for slice_name in PHASE0_SLICES:
                arguments.extend(["--slice", slice_name])
            with redirect_stdout(StringIO()):
                self.assertEqual(main(arguments), 0)
            traces = list(read_traces([trace_path]))
            self.assertEqual(len(traces), 18)
            self.assertEqual(len({row["task"]["id"] for row in traces}), 6)
            self.assertEqual(
                {row["candidate"]["model"] for row in traces},
                {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"},
            )
            for row in traces:
                event_types = [event["type"] for event in row["agent_events"]]
                self.assertEqual(event_types[0], "agent_start")
                self.assertEqual(event_types[-1], "agent_end")
                self.assertIn("tool_execution_start", event_types)
                self.assertIn("tool_execution_end", event_types)
                self.assertEqual(len(row["tool_calls"]), 1)
                self.assertEqual(row["tool_calls"][0]["action"], "read")
                self.assertEqual(row["score"]["correctness"], 4)
                self.assertEqual(row["score"]["evidence_quality"], 2)
                self.assertEqual(row["score"]["safety"], 1)
                self.assertEqual(row["metrics"]["cost_usd_estimate"], "0.000000")
                self.assertEqual(len(row["versions"]["node_lock_sha256"]), 64)

    def test_wrong_answer_fixture_produces_failure_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config_path = root / "negative.json"
            trace_path = root / "negative.jsonl"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "candidates": [
                            {
                                "id": "diagnostic__pi-agent-0.73.1",
                                "model": "diagnostic",
                                "agent": "pi-agent-0.73.1",
                                "adapter": "pi-agent-offline",
                                "config": {"behavior": "wrong_answer"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "run",
                        "--tasks",
                        str(TASKS),
                        "--config",
                        str(config_path),
                        "--output",
                        str(trace_path),
                        "--run-id",
                        "pi-negative",
                        "--slice",
                        "portfolio",
                        "--variant",
                        "analyze_weight",
                    ]
                )
            self.assertEqual(status, 1)
            trace = next(read_traces([trace_path]))
            self.assertEqual(trace["failure_signature"]["code"], "WRONG_ANSWER")
            self.assertIn(
                "portfolio-permission-boundary::analyze_weight",
                trace["failure_signature"]["trigger_condition"],
            )
            self.assertIn("run_id=pi-negative", trace["failure_signature"]["reproduction_evidence"])
            self.assertEqual(trace["score"]["correctness"], 0)
            self.assertEqual(trace["score"]["evidence_quality"], 2)
            self.assertTrue(trace["score"]["hard_gate_passed"])

    def test_live_pi_plan_is_no_network_and_has_hard_request_ceiling(self):
        candidates = load_candidates(PI_LIVE_CONFIG)
        self.assertEqual({candidate.adapter for candidate in candidates}, {"pi-agent-live"})
        stdout = StringIO()
        arguments = [
            "plan-live",
            "--tasks",
            str(TASKS),
            "--config",
            str(PI_LIVE_CONFIG),
        ]
        for slice_name in PHASE0_SLICES:
            arguments.extend(["--slice", slice_name])
        with redirect_stdout(stdout):
            self.assertEqual(main(arguments), 0)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["network_calls_performed"], 0)
        self.assertEqual(len(candidates), 4)
        self.assertEqual(plan["matrix_cells"], 24)
        self.assertEqual(plan["request_ceiling"]["preflight"], 4)
        self.assertEqual(plan["request_ceiling"]["matrix"], 48)
        self.assertEqual(plan["request_ceiling"]["total"], 52)
        self.assertEqual(plan["request_ceiling"]["retries_per_request"], 0)
        self.assertEqual(plan["token_ceiling"]["output_hard_cap"], 24832)
        self.assertIsNone(plan["cost_usd_upper_bound"])
        self.assertTrue(plan["approval_required"])

    def test_live_pi_preflight_delegates_to_exact_sse_identity_transport(self):
        candidate = load_candidates(PI_LIVE_CONFIG)[0]
        expected = {"model": candidate.model, "status": "passed"}
        with patch("financial_agent_reliability.adapters.core.BailianLiveAdapter") as adapter_class:
            adapter_class.return_value.preflight.return_value = expected
            result = PiAgentLiveAdapter(
                ROOT, env={"BENCH_BAILIAN_API_KEY": "memory-only"}
            ).preflight(candidate)
        self.assertEqual(result, expected)
        adapter_class.return_value.preflight.assert_called_once_with(candidate)

    def test_phase11_plan_has_eight_isolated_calibration_cells(self):
        stdout = StringIO()
        arguments = [
            "plan-live",
            "--tasks",
            str(TASKS),
            "--config",
            str(PI_CALIBRATION_CONFIG),
            "--slice",
            "fundamentals",
            "--slice",
            "portfolio",
            "--variant",
            "positive_earnings",
            "--variant",
            "execute_trade",
        ]
        with redirect_stdout(stdout):
            self.assertEqual(main(arguments), 0)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["matrix_cells"], 8)
        self.assertEqual(plan["request_ceiling"]["preflight"], 4)
        self.assertEqual(plan["request_ceiling"]["matrix"], 16)

    def test_filtered_model_run_accepts_bound_preflight_superset(self):
        candidates = load_candidates(PI_CALIBRATION_CONFIG)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "preflight.json"
            versions = {"config_sha256": "a" * 64}
            path.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "config_sha256": "a" * 64,
                        "models": [
                            {
                                "model": candidate.model,
                                "status": "passed",
                                "identity": {"exact_match": True},
                            }
                            for candidate in candidates
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _bind_live_preflight(path, [candidates[0]], versions)
        self.assertEqual(len(versions["preflight_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
