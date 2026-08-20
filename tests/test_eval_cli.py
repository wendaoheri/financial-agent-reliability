from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from financial_agent_reliability.adapters.core import AdapterResult
from financial_agent_reliability.cli import main
from financial_agent_reliability.models import Candidate, load_candidates
from financial_agent_reliability.report_eval_pack import (
    _derive_mock_output,
    load_eval_cases,
    run_eval,
)
from financial_agent_reliability.report_eval_pack import (
    replay_report_eval as replay_eval,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "per424" / "tasks.jsonl"
PACK = TASKS.parent
CONFIG = ROOT / "configs" / "per424-mock.json"
LIVE_CONFIG = ROOT / "configs" / "pi-bailian-calibration-v3.json"
LIVE_CANDIDATE_ID = "qwen3.8-max__pi-agent-0.73.1"
APPROVED_LIVE_CASE_IDS = [
    "D1-F01-normal",
    "D1-F01-challenge",
    "D2-F01-normal",
    "D2-F01-challenge",
    "D3-F01-normal",
    "D4-F01-normal",
    "D5-F01-challenge",
    "D6-F01-normal",
    "D7-F01-challenge",
    "D8-F01-normal",
]


def _live_case_ids() -> list[str]:
    candidate = next(item for item in load_candidates(LIVE_CONFIG) if item.id == LIVE_CANDIDATE_ID)
    return list(candidate.config["calibration_case_ids"])


def _candidate(candidate_id: str, behavior: str) -> Candidate:
    return Candidate(
        id=candidate_id,
        model="offline-contract-fixture",
        agent="bounded-mock-agent",
        adapter="mock",
        config={"behavior": behavior, "execution_mode": "tool", "latency_ms": 1},
    )


class ReportEvalCLITests(unittest.TestCase):
    def test_report_live_plan_requires_the_approved_explicit_case_slice(self):
        live_case_ids = _live_case_ids()
        self.assertEqual(live_case_ids, APPROVED_LIVE_CASE_IDS)
        stdout = StringIO()
        arguments = [
            "plan-live",
            "--tasks",
            str(TASKS),
            "--config",
            str(LIVE_CONFIG),
            "--candidate",
            LIVE_CANDIDATE_ID,
        ]
        for case_id in live_case_ids:
            arguments.extend(["--case-id", case_id])
        with redirect_stdout(stdout):
            status = main(arguments)
        self.assertEqual(status, 0)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["network_calls_performed"], 0)
        self.assertEqual(plan["matrix_cells"], 10)
        self.assertEqual(
            plan["request_ceiling"],
            {
                "preflight": 1,
                "matrix": 20,
                "total": 21,
                "retries_per_request": 0,
            },
        )
        self.assertEqual(plan["token_ceiling"]["input_contract"], 480256)
        self.assertEqual(plan["token_ceiling"]["output_hard_cap"], 10304)
        self.assertEqual(plan["token_ceiling"]["total_planned"], 490560)

        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            rejected = main(
                [
                    "plan-live",
                    "--tasks",
                    str(TASKS),
                    "--config",
                    str(LIVE_CONFIG),
                    "--candidate",
                    LIVE_CANDIDATE_ID,
                    "--case-id",
                    "D1-F02-normal",
                ]
            )
        self.assertEqual(rejected, 2)
        self.assertIn("approved calibration cases", stderr.getvalue())

    def test_report_live_run_requires_preflight_before_adapter_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "live-bundle"
            arguments = [
                "eval-run",
                "--pack",
                str(PACK),
                "--config",
                str(LIVE_CONFIG),
                "--candidate",
                LIVE_CANDIDATE_ID,
                "--output-dir",
                str(output),
            ]
            for case_id in _live_case_ids():
                arguments.extend(["--case-id", case_id])
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                with patch("financial_agent_reliability.report_eval_pack.get_adapter") as adapter:
                    status = main(arguments)
            self.assertEqual(status, 2)
            self.assertIn("requires --preflight", stderr.getvalue())
            adapter.assert_not_called()
            self.assertFalse(output.exists())

    def test_live_report_cells_share_mock_scoring_and_redact_invalid_output(self):
        cases = load_eval_cases(TASKS)
        candidate = next(
            item for item in load_candidates(LIVE_CONFIG) if item.id == LIVE_CANDIDATE_ID
        )

        class FixtureAdapter:
            version = "fixture"

            def __init__(self, behavior: str) -> None:
                self.behavior = behavior
                self.requests = []

            def execute(self, request, _candidate, tools):
                self.requests.append(request)
                fixture = dict(request.resources[0])
                tools.invoke("read_fixture")
                output = _derive_mock_output(fixture)
                error = None
                if self.behavior == "candidate_failure":
                    output["cited_record_ids"] = []
                elif self.behavior == "invalid_protocol":
                    output = {"unexpected": "BENCH_BAILIAN_API_KEY=should-never-be-persisted"}
                elif self.behavior == "provider_failure":
                    output = None
                    error = {
                        "code": "PROVIDER_UNAVAILABLE",
                        "message": "fixture provider failure",
                        "retryable": False,
                    }
                return AdapterResult(
                    output=output,
                    error=error,
                    latency_ms=7,
                    input_tokens=101,
                    output_tokens=17,
                    provider_identity={"exact_match": True},
                    cost_basis="token_plan_unpriced",
                    agent_events=({"type": "agent_start"}, {"type": "agent_end"}),
                )

        expected = {
            "pass": "candidate_success",
            "candidate_failure": "candidate_failure",
            "invalid_protocol": "invalid_run",
            "provider_failure": "invalid_run",
        }
        for behavior, outcome in expected.items():
            with self.subTest(behavior=behavior):
                adapter = FixtureAdapter(behavior)
                with patch(
                    "financial_agent_reliability.report_eval_pack.get_adapter",
                    return_value=adapter,
                ):
                    trace = run_eval(
                        TASKS,
                        cases[:1],
                        [candidate],
                        run_id=f"live-{behavior}",
                        repository_root=ROOT,
                        preflight_sha256="f" * 64,
                    )[0]
                self.assertEqual(trace["outcome"], outcome)
                self.assertEqual(trace["candidate"]["preflight_sha256"], "f" * 64)
                self.assertEqual(trace["metrics"]["input_tokens_estimate"], 101)
                self.assertEqual(trace["metrics"]["output_tokens_estimate"], 17)
                request = adapter.requests[0]
                self.assertIn("prompt", request.input)
                self.assertEqual(request.resources[0]["fixture_id"], "per424-family-001")
                self.assertNotIn("gold", json.dumps(request.input, ensure_ascii=False))
                if behavior == "invalid_protocol":
                    self.assertIsNone(trace["output"])
                    self.assertEqual(trace["error"]["code"], "INVALID_MODEL_OUTPUT")
                    self.assertEqual(len(trace["error"]["output_summary"]["sha256"]), 64)
                    self.assertNotIn("should-never-be-persisted", json.dumps(trace))
                if behavior == "pass":
                    with tempfile.TemporaryDirectory() as temporary:
                        trace_path = pathlib.Path(temporary) / "live.jsonl"
                        trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
                        replay = replay_eval(
                            TASKS,
                            cases,
                            load_candidates(LIVE_CONFIG),
                            trace_path,
                        )
                    self.assertEqual(replay["status"], "verified")

    def test_eval_validate_enforces_the_exact_report_pack(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["eval-validate", "--pack", str(PACK), "--config", str(CONFIG)])
        self.assertEqual(status, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["cases"], 100)
        self.assertEqual(report["variants"], {"challenge": 40, "normal": 60})
        self.assertEqual(report["eval_pack_id"], "per424-report-eight-gates-100-dev-v2.1")
        self.assertEqual(report["network_calls_performed"], 0)
        self.assertEqual(set(report["gates"]), {f"D{number}" for number in range(1, 9)})
        self.assertEqual(set(report["root_causes"]), {f"R{number}" for number in range(1, 6)})

    def test_eval_run_strips_gold_and_replays_deterministically(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "bundle"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "eval-run",
                        "--pack",
                        str(PACK),
                        "--config",
                        str(CONFIG),
                        "--output-dir",
                        str(output),
                        "--run-id",
                        "per424-test",
                    ]
                )
            self.assertEqual(status, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["trace_count"], 100)
            traces = [
                json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()
            ]
            self.assertEqual({trace["outcome"] for trace in traces}, {"candidate_success"})
            self.assertTrue(all(trace["reliability_pass"] for trace in traces))
            first = traces[0]
            for evaluator_field in (
                "gold",
                "tags",
                "notes",
                "family_id",
                "variant",
                "primary_gate",
                "root_causes",
            ):
                self.assertNotIn(evaluator_field, first["candidate_input"])
            self.assertNotIn("path", first["candidate_input"]["resources"][0])
            self.assertIn("records", first["tool_calls"][0]["response"])
            for forbidden in (
                "git",
                "git_commit",
                "worktree",
                "operating_system",
                "python_lock_sha256",
                "node_lock_sha256",
                "release_status",
            ):
                self.assertNotIn(forbidden, first)

            replay_stdout = StringIO()
            with redirect_stdout(replay_stdout):
                replay_status = main(
                    [
                        "eval-replay",
                        "--pack",
                        str(PACK),
                        "--config",
                        str(CONFIG),
                        "--bundle",
                        str(output),
                    ]
                )
            self.assertEqual(replay_status, 0)
            self.assertEqual(json.loads(replay_stdout.getvalue())["status"], "passed")

    def test_three_classes_and_safety_hard_gate_are_distinct(self):
        cases = load_eval_cases(TASKS)
        candidates = [
            _candidate("pass", "pass"),
            _candidate("missing", "missing_evidence"),
            _candidate("timeout", "timeout"),
            _candidate("unsafe", "safety_violation"),
        ]
        traces = run_eval(TASKS, cases[:1], candidates, run_id="classification-test")
        by_candidate = {trace["candidate"]["id"]: trace for trace in traces}
        self.assertEqual(by_candidate["pass"]["outcome"], "candidate_success")
        self.assertEqual(by_candidate["missing"]["outcome"], "candidate_failure")
        self.assertEqual(by_candidate["timeout"]["outcome"], "invalid_run")
        self.assertEqual(by_candidate["unsafe"]["outcome"], "candidate_failure")
        self.assertEqual(by_candidate["unsafe"]["score"]["safety"], 0)
        self.assertFalse(by_candidate["unsafe"]["score"]["hard_gate_passed"])

    def test_mock_candidate_derives_output_from_fixture_not_gold(self):
        cases = load_eval_cases(TASKS)
        case = json.loads(json.dumps(cases[0]))
        expected = case["gold"]["expected_output"]
        original_value = expected["value"]
        expected["value"] = "tampered evaluator Gold"
        traces = run_eval(TASKS, [case], [_candidate("pass", "pass")], run_id="gold-isolation")
        self.assertEqual(traces[0]["output"]["value"], original_value)
        self.assertEqual(traces[0]["outcome"], "candidate_failure")

    def test_replay_detects_score_tampering(self):
        cases = load_eval_cases(TASKS)
        candidates = load_candidates(CONFIG)
        traces = run_eval(TASKS, cases[:1], candidates, run_id="tamper-test")
        traces[0]["score"]["correctness"] = 0
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "tampered.jsonl"
            path.write_text(json.dumps(traces[0], ensure_ascii=False) + "\n", encoding="utf-8")
            report = replay_eval(TASKS, cases, candidates, path)
        self.assertEqual(report["status"], "mismatch")
        self.assertIn("score differs after regrade", report["mismatches"][0])

    def test_eval_commands_reject_non_mock_candidates(self):
        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = main(
                [
                    "eval-validate",
                    "--pack",
                    str(PACK),
                    "--config",
                    str(ROOT / "configs" / "pi-offline.json"),
                ]
            )
        self.assertEqual(status, 2)
        self.assertIn("unsupported adapter", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
