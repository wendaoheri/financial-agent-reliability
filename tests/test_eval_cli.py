from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from financial_agent_reliability.adapters.core import AdapterResult
from financial_agent_reliability.cli import main
from financial_agent_reliability.eval_pack import (
    aggregate_eval_bundles,
    analyze_eval_migration,
    replay_eval_pack,
    run_eval_pack,
)
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
CONFIG = ROOT / "configs" / "mock.json"
MOCK_CANDIDATE_ID = "mock-small__tool-agent"
LIVE_CONFIG = ROOT / "configs" / "pi-bailian-live.json"
LIVE_CANDIDATE_ID = "qwen3.8-max__pi-agent-0.73.1"
APPROVED_LIVE_CASE_IDS = [
    "D1-F01-normal",
    "D4-F03-normal",
    "D2-F03-normal",
    "D3-F01-normal",
    "D1-F04-normal",
    "D2-F07-normal",
    "D7-F05-normal",
    "D8-F06-normal",
    "D4-F03-challenge",
    "D7-F05-challenge",
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
            "--live-stage",
            "calibration",
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
        self.assertEqual(plan["token_ceiling"]["output_hard_cap"], 81984)
        self.assertEqual(plan["token_ceiling"]["total_planned"], 562240)

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
                    "--live-stage",
                    "calibration",
                    "--case-id",
                    "D1-F02-normal",
                ]
            )
        self.assertEqual(rejected, 2)
        self.assertIn("registered calibration cases", stderr.getvalue())

        baseline_stdout = StringIO()
        with redirect_stdout(baseline_stdout):
            baseline_status = main(
                [
                    "plan-live",
                    "--tasks",
                    str(TASKS),
                    "--config",
                    str(LIVE_CONFIG),
                    "--candidate",
                    LIVE_CANDIDATE_ID,
                    "--live-stage",
                    "baseline",
                ]
            )
        self.assertEqual(baseline_status, 0)
        baseline = json.loads(baseline_stdout.getvalue())
        self.assertEqual(baseline["matrix_cells"], 100)
        self.assertEqual(baseline["request_ceiling"]["total"], 201)
        self.assertEqual(baseline["token_ceiling"]["input_contract"], 4800256)
        self.assertEqual(baseline["token_ceiling"]["output_hard_cap"], 819264)
        self.assertEqual(baseline["token_ceiling"]["total_planned"], 5619520)

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
                "--live-stage",
                "calibration",
                "--run-id",
                "preflight-required",
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
                elif self.behavior == "shape_mismatch":
                    output["value"] = {"decision": output["value"]}
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
                    final_output_raw=(
                        json.dumps(output, ensure_ascii=False, sort_keys=True)
                        if error is None
                        else None
                    ),
                    input_tokens=101,
                    output_tokens=17,
                    provider_identity={"exact_match": True},
                    cost_basis="token_plan_unpriced",
                    agent_events=({"type": "agent_start"}, {"type": "agent_end"}),
                )

        expected = {
            "pass": "candidate_success",
            "candidate_failure": "candidate_failure",
            "shape_mismatch": "candidate_failure",
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
                    self.assertIsNone(trace["final_output_raw"])
                    self.assertEqual(trace["error"]["code"], "INVALID_MODEL_OUTPUT")
                    self.assertEqual(len(trace["error"]["output_summary"]["sha256"]), 64)
                    self.assertNotIn("should-never-be-persisted", json.dumps(trace))
                if behavior == "shape_mismatch":
                    self.assertEqual(
                        trace["value_diagnostic"]["mismatch_reason"],
                        "value_shape_mismatch",
                    )
                    self.assertEqual(trace["failure_signature"]["code"], "VALUE_SHAPE_MISMATCH")
                    self.assertIn("decision", trace["final_output_raw"])
                if behavior == "pass":
                    self.assertEqual(trace["value_diagnostic"]["shape_pass"], True)
                    self.assertEqual(trace["value_diagnostic"]["semantic_pass"], True)
                    self.assertEqual(
                        hashlib.sha256(trace["final_output_raw"].encode()).hexdigest(),
                        trace["final_output_sha256"],
                    )
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

    def test_live_report_baseline_resumes_from_atomic_case_checkpoints(self):
        candidate = next(
            item for item in load_candidates(LIVE_CONFIG) if item.id == LIVE_CANDIDATE_ID
        )

        class FixtureAdapter:
            version = "fixture"

            def __init__(self, *, interrupt_on: int | None = None) -> None:
                self.calls = 0
                self.interrupt_on = interrupt_on

            def execute(self, request, _candidate, tools):
                self.calls += 1
                if self.interrupt_on == self.calls:
                    raise KeyboardInterrupt
                fixture = dict(request.resources[0])
                tools.invoke("read_fixture")
                return AdapterResult(
                    output=(output := _derive_mock_output(fixture)),
                    error=None,
                    latency_ms=1,
                    final_output_raw=json.dumps(output, ensure_ascii=False, sort_keys=True),
                    input_tokens=10,
                    output_tokens=5,
                    provider_identity={"exact_match": True},
                    cost_basis="token_plan_unpriced",
                )

        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "durable-live"
            interrupted = FixtureAdapter(interrupt_on=2)
            with patch(
                "financial_agent_reliability.report_eval_pack.get_adapter",
                return_value=interrupted,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    run_eval_pack(
                        PACK,
                        output,
                        candidates=[candidate],
                        repository_root=ROOT,
                        run_id="durable-live",
                        preflight_sha256="f" * 64,
                        live_stage="baseline",
                    )
            self.assertEqual(len(list((output / ".checkpoint" / "cases").glob("*.json"))), 1)

            resumed = FixtureAdapter()
            with patch(
                "financial_agent_reliability.report_eval_pack.get_adapter",
                return_value=resumed,
            ):
                report = run_eval_pack(
                    PACK,
                    output,
                    candidates=[candidate],
                    repository_root=ROOT,
                    run_id="durable-live",
                    preflight_sha256="f" * 64,
                    live_stage="baseline",
                )
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["trace_count"], 100)
            self.assertEqual(resumed.calls, 99)
            self.assertFalse((output / ".checkpoint").exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "trace.jsonl").stat().st_mode & 0o777, 0o600)
            replay = replay_eval_pack(PACK, output, candidates=load_candidates(LIVE_CONFIG))
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(
                replay["claim_boundary"],
                "controlled_live_internal_diagnostic_no_model_or_agent_ranking",
            )
            aggregate = aggregate_eval_bundles(PACK, [output], candidates=[candidate])
            self.assertEqual(aggregate["status"], "completed")
            self.assertEqual(aggregate["first_attempt_cells"], 100)
            self.assertEqual(aggregate["candidates"][candidate.id]["unique_cases"], 100)
            migration = analyze_eval_migration(
                PACK,
                [output],
                [output],
                candidates=[candidate],
            )
            self.assertEqual(migration["status"], "completed")
            self.assertEqual(migration["paired_cells"], 100)
            self.assertEqual(migration["network_calls_performed"], 0)
            self.assertEqual(
                migration["comparisons"][candidate.id]["new_minus_old_success_rate"],
                0,
            )
            self.assertNotIn("output", migration["cells"][0])

    def test_live_calibration_fails_when_schema_adherence_is_below_nine_of_ten(self):
        candidate = next(
            item for item in load_candidates(LIVE_CONFIG) if item.id == LIVE_CANDIDATE_ID
        )

        class ShapeFailureAdapter:
            version = "fixture"

            def __init__(self) -> None:
                self.calls = 0

            def execute(self, request, _candidate, tools):
                self.calls += 1
                tools.invoke("read_fixture")
                output = _derive_mock_output(dict(request.resources[0]))
                if self.calls <= 2:
                    output["value"] = {"unexpected_wrapper": output["value"]}
                return AdapterResult(
                    output=output,
                    error=None,
                    latency_ms=1,
                    final_output_raw=json.dumps(output, ensure_ascii=False, sort_keys=True),
                    provider_identity={"exact_match": True},
                    cost_basis="token_plan_unpriced",
                )

        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "failed-calibration"
            adapter = ShapeFailureAdapter()
            with patch(
                "financial_agent_reliability.report_eval_pack.get_adapter",
                return_value=adapter,
            ):
                report = run_eval_pack(
                    PACK,
                    output,
                    candidates=[candidate],
                    case_ids=APPROVED_LIVE_CASE_IDS,
                    repository_root=ROOT,
                    run_id="failed-calibration",
                    preflight_sha256="f" * 64,
                    live_stage="calibration",
                )
            self.assertEqual(report["status"], "calibration_failed")
            aggregate = json.loads((output / "aggregate.json").read_text())
            self.assertEqual(
                aggregate["by_candidate"][candidate.id]["schema_adherence_rate"],
                0.8,
            )

    def test_eval_validate_enforces_the_exact_report_pack(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["eval-validate", "--pack", str(PACK), "--config", str(CONFIG)])
        self.assertEqual(status, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["cases"], 100)
        self.assertEqual(report["variants"], {"challenge": 40, "normal": 60})
        self.assertEqual(report["eval_pack_id"], "per424-report-eight-gates-100-dev-v3")
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
                        "--candidate",
                        MOCK_CANDIDATE_ID,
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
