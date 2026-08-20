from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from financial_agent_reliability.adapters.core import (
    AdapterResult,
    BailianLiveAdapter,
    CandidateRequest,
    MockAdapter,
    OfflineMockTools,
)
from financial_agent_reliability.adapters.http import BailianHTTPError
from financial_agent_reliability.cli import main
from financial_agent_reliability.models import (
    BenchInputError,
    audit_taskset,
    load_candidates,
    load_tasks,
    task_validator,
)
from financial_agent_reliability.runner import run_matrix, version_coordinates
from financial_agent_reliability.trace import append_traces, read_traces, trace_validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "dev" / "tasks.jsonl"
CANDIDATES = ROOT / "configs" / "mock.json"
NEGATIVE_CONTROLS = ROOT / "tests" / "fixtures" / "negative-control.json"
LIVE_CANDIDATES = ROOT / "configs" / "bailian-token-plan.json"


class BenchMVPTests(unittest.TestCase):
    def test_version_coordinates_exclude_framework_provenance(self):
        versions = version_coordinates(tasks_path=TASKS, config_path=CANDIDATES)
        self.assertEqual(
            set(versions),
            {
                "eval_pack_id",
                "runner_protocol_version",
                "taskset_sha256",
                "config_sha256",
                "trace_schema_version",
            },
        )

    def test_trace_schema_is_valid_and_checkable(self):
        validator = trace_validator()
        validator.check_schema(validator.schema)
        with self.assertRaisesRegex(ValueError, "unsupported trace"):
            trace_validator("0.3.0")

    def test_bailian_live_candidate_boundary_and_exact_identity(self):
        candidates = load_candidates(LIVE_CANDIDATES)
        self.assertEqual(len(candidates), 4)
        self.assertEqual({candidate.agent for candidate in candidates}, {"plain-agent"})
        candidate = candidates[0]
        captured = []

        def transport_factory(_settings, *, timeout_seconds):
            self.assertEqual(timeout_seconds, 120)

            def transport(request):
                captured.append(request)
                return {
                    "model": candidate.model,
                    "output": json.dumps({"status": "answer", "value": 1.5, "reason_codes": []}),
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                }

            return transport

        adapter = BailianLiveAdapter(
            ROOT,
            env={"BENCH_BAILIAN_API_KEY": "memory-only-test-value"},
            transport_factory=transport_factory,
        )
        preflight = adapter.preflight(candidate)
        self.assertEqual(preflight["status"], "passed")
        self.assertTrue(preflight["identity"]["exact_match"])
        task = load_tasks(TASKS)[0]
        request = CandidateRequest.from_payload(task["candidate_payload"])
        result = adapter.execute(request, candidate, OfflineMockTools(request))
        self.assertIsNone(result.error)
        self.assertEqual(result.output, {"status": "answer", "value": 1.5, "reason_codes": []})
        self.assertEqual(result.input_tokens, 11)
        self.assertEqual(result.output_tokens, 7)
        self.assertTrue(result.provider_identity["exact_match"])
        rendered_request = json.dumps(captured[1], sort_keys=True)
        self.assertNotIn("expected_output", rendered_request)
        self.assertNotIn("oracle", rendered_request)
        self.assertNotIn("memory-only-test-value", rendered_request)

    def test_live_profile_controls_stream_and_reasoning_without_network(self):
        candidate = load_candidates(LIVE_CANDIDATES)[0]
        captured = []

        def transport_factory(_settings, *, timeout_seconds):
            self.assertEqual(timeout_seconds, 120)

            def transport(request):
                captured.append(request)
                return {
                    "model": candidate.model,
                    "output": json.dumps({"status": "answer", "value": 1.5, "reason_codes": []}),
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                    "stream_metrics": {
                        "mode": "streaming",
                        "ttft_reasoning_ms": 2,
                        "ttft_content_ms": 4,
                        "e2e_ms": 7,
                    },
                    "reasoning_summary": {"characters": 3, "sha256": "a" * 64},
                    "http_observation": {
                        "status": 200,
                        "provider_code": None,
                        "request_id": "fixture-request",
                        "error_origin": None,
                    },
                }

            return transport

        adapter = BailianLiveAdapter(
            ROOT,
            env={"BENCH_BAILIAN_API_KEY": "memory-only-test-value"},
            transport_factory=transport_factory,
        )
        task = load_tasks(TASKS)[0]
        request = CandidateRequest.from_payload(task["candidate_payload"])
        result = adapter.execute(request, candidate, OfflineMockTools(request))
        self.assertIsNone(result.error)
        self.assertTrue(captured[0]["parameters"]["stream"])
        self.assertEqual(captured[0]["parameters"]["reasoning_effort"], "low")
        profile = result.provider_observability["generation_profile"]
        self.assertEqual(profile["requested"]["stream"], "on")
        self.assertEqual(profile["resolved"]["reasoning"]["mode"], "on")
        self.assertEqual(result.provider_observability["http"]["request_id"], "fixture-request")

    def test_live_error_retains_sanitized_429_evidence(self):
        candidate = load_candidates(LIVE_CANDIDATES)[1]

        def transport_factory(_settings, *, timeout_seconds):
            def transport(_request):
                raise BailianHTTPError(
                    "rate_limited", True, 429, "QuotaExceeded", "request-123", "provider_http"
                )

            return transport

        adapter = BailianLiveAdapter(
            ROOT,
            env={"BENCH_BAILIAN_API_KEY": "memory-only-test-value"},
            transport_factory=transport_factory,
        )
        task = load_tasks(TASKS)[0]
        request = CandidateRequest.from_payload(task["candidate_payload"])
        result = adapter.execute(request, candidate, OfflineMockTools(request))
        self.assertEqual(result.error["code"], "RATE_LIMITED")
        self.assertEqual(result.error["http_status"], 429)
        self.assertEqual(result.error["provider_code"], "QuotaExceeded")
        self.assertEqual(result.error["error_origin"], "provider_http")
        self.assertEqual(result.provider_observability["http"]["request_id"], "request-123")

    def test_live_matrix_rotates_models_and_waits_for_minimum_error_sample(self):
        candidates = load_candidates(LIVE_CANDIDATES)
        tasks = load_tasks(TASKS)[:3]
        first_task = tasks[0]["task_id"]
        failing = {candidates[0].id, candidates[1].id}

        class FixtureAdapter:
            version = "fixture"

            def execute(self, request, candidate, tools):
                if request.task_id == first_task and candidate.id in failing:
                    return AdapterResult(
                        output=None,
                        error={"code": "TIMEOUT", "message": "fixture", "retryable": True},
                        latency_ms=1,
                        cost_basis="token_plan_unpriced",
                    )
                return MockAdapter().execute(request, candidate, tools)

        with patch(
            "financial_agent_reliability.runner.get_adapter",
            return_value=FixtureAdapter(),
        ):
            traces = run_matrix(
                tasks,
                candidates,
                repository_root=ROOT,
                run_id="round-robin-fixture",
                versions={"trace_schema_version": "0.6.0"},
            )
        self.assertEqual(len(traces), 10)
        self.assertEqual(
            {trace["candidate"]["model"] for trace in traces[:4]},
            {candidate.model for candidate in candidates},
        )

    def test_bailian_live_run_requires_bound_preflight_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "trace.jsonl"
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                status = main(
                    [
                        "run",
                        "--tasks",
                        str(TASKS),
                        "--config",
                        str(LIVE_CANDIDATES),
                        "--output",
                        str(output),
                        "--run-id",
                        "missing-preflight",
                    ]
                )
            self.assertEqual(status, 2)
            self.assertIn("requires --preflight", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_validate_accepts_model_agent_axes(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["validate", "--tasks", str(TASKS), "--config", str(CANDIDATES)])
        self.assertEqual(status, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["tasks"], 16)
        self.assertEqual(result["candidates"], 4)
        self.assertEqual(result["audit"]["cards"], 8)
        self.assertEqual(result["audit"]["variants"], 16)
        self.assertTrue(all(check["passed"] for check in result["audit"]["checks"].values()))

    def test_mock_smoke_emits_schema_valid_jsonl_without_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = pathlib.Path(temporary) / "trace.jsonl"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--tasks",
                        str(TASKS),
                        "--config",
                        str(CANDIDATES),
                        "--output",
                        str(trace_path),
                        "--run-id",
                        "test-run",
                    ]
                )
            self.assertEqual(status, 1)
            traces = list(read_traces([trace_path]))
            self.assertEqual(len(traces), 64)
            self.assertEqual(
                {row["candidate"]["model"] for row in traces}, {"mock-small", "mock-large"}
            )
            self.assertEqual(
                {row["candidate"]["agent"] for row in traces},
                {"plain-agent", "tool-agent"},
            )
            self.assertEqual(
                {row["task"]["id"] for row in traces},
                {
                    "market-orderbook-integrity::valid_book",
                    "market-orderbook-integrity::crossed_book",
                    "fundamentals-valuation-multiple::positive_earnings",
                    "fundamentals-valuation-multiple::loss_company",
                    "earnings-revenue-growth::forward_periods",
                    "earnings-revenue-growth::reversed_periods",
                    "news-cutoff-evidence::published_before_cutoff",
                    "news-cutoff-evidence::published_after_cutoff",
                    "portfolio-permission-boundary::analyze_weight",
                    "portfolio-permission-boundary::execute_trade",
                    "options-parity-check::complete_inputs",
                    "options-parity-check::missing_discount",
                    "technical-moving-average-direction::fast_above_slow",
                    "technical-moving-average-direction::fast_below_slow",
                    "rules-settlement-cutoff::before_availability",
                    "rules-settlement-cutoff::at_availability",
                },
            )
            plain = [row for row in traces if row["candidate"]["agent"] == "plain-agent"]
            tool = [row for row in traces if row["candidate"]["agent"] == "tool-agent"]
            self.assertTrue(all(row["tool_calls"] == [] for row in plain))
            self.assertTrue(all(len(row["tool_calls"]) == 1 for row in tool))
            self.assertTrue(all(row["tool_calls"][0]["action"] == "read" for row in tool))
            self.assertTrue(all(row["tool_calls"][0]["status"] == "ok" for row in tool))
            self.assertTrue(
                all(row["metrics"]["cost_usd_estimate"] == "0.000000" for row in traces)
            )
            self.assertTrue(
                all(
                    row["score"]
                    == {
                        "correctness": 4,
                        "evidence_quality": 0,
                        "safety": 1,
                        "hard_gate_passed": True,
                        "eligible_for_quality_aggregation": True,
                    }
                    for row in plain
                )
            )
            self.assertTrue(all(row["score"]["evidence_quality"] == 2 for row in tool))
            self.assertTrue(all(len(row["versions"]["taskset_sha256"]) == 64 for row in traces))

    def test_compare_does_not_modify_raw_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = pathlib.Path(temporary) / "trace.jsonl"
            report_path = pathlib.Path(temporary) / "report.json"
            self.assertEqual(
                main(
                    [
                        "run",
                        "--tasks",
                        str(TASKS),
                        "--config",
                        str(CANDIDATES),
                        "--output",
                        str(trace_path),
                        "--run-id",
                        "immutable-source-test",
                    ]
                ),
                1,
            )
            before = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(["compare", str(trace_path), "--output", str(report_path)])
            after = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            self.assertEqual(status, 0)
            self.assertEqual(before, after)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["by_candidate"]), 4)
            self.assertTrue(all(row["runs"] == 16 for row in report["by_candidate"]))
            self.assertEqual(len(report["by_slice"]), 8)
            self.assertEqual(len(report["by_variant"]), 16)
            self.assertEqual(len(report["by_model"]), 2)
            self.assertEqual(len(report["by_agent"]), 2)
            self.assertEqual(
                report["overall"]["operational_metrics"]["cost_usd_estimate"], "0.000000"
            )
            agent_contrast = next(
                item for item in report["overall"]["paired_contrasts"] if item["axis"] == "agent"
            )
            model_contrast = next(
                item for item in report["overall"]["paired_contrasts"] if item["axis"] == "model"
            )
            self.assertEqual(agent_contrast["status"], "identifiable")
            self.assertEqual(agent_contrast["delta_intervals_95"]["evidence_quality"]["mean"], 2.0)
            self.assertEqual(model_contrast["status"], "non_identifiable")
            self.assertLess(report["overall"]["uncertainty_95"]["safety_pass_rate"]["lower"], 1.0)
            self.assertEqual(
                report["overall"]["uncertainty_95"]["safety_pass_rate"]["method"], "wilson"
            )
            self.assertTrue(all("paired_contrasts" in row for row in report["by_slice"]))
            self.assertTrue(all("paired_contrasts" in row for row in report["by_variant"]))

    def test_run_filters_slice_variant_and_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = pathlib.Path(temporary) / "trace.jsonl"
            status = main(
                [
                    "run",
                    "--tasks",
                    str(TASKS),
                    "--config",
                    str(CANDIDATES),
                    "--output",
                    str(trace_path),
                    "--run-id",
                    "filtered",
                    "--slice",
                    "portfolio",
                    "--variant",
                    "execute_trade",
                    "--candidate",
                    "mock-small__plain-agent",
                ]
            )
            self.assertEqual(status, 1)
            traces = list(read_traces([trace_path]))
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0]["task"]["slice"], "portfolio")
            self.assertEqual(traces[0]["task"]["variant"], "execute_trade")

    def test_repeated_mock_runs_produce_identical_structured_comparison(self):
        reports = []
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for index in range(2):
                trace_path = root / f"trace-{index}.jsonl"
                report_path = root / f"report-{index}.json"
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "run",
                                "--tasks",
                                str(TASKS),
                                "--config",
                                str(CANDIDATES),
                                "--output",
                                str(trace_path),
                                "--run-id",
                                f"repeat-{index}",
                            ]
                        ),
                        1,
                    )
                    self.assertEqual(
                        main(["compare", str(trace_path), "--output", str(report_path)]), 0
                    )
                reports.append(json.loads(report_path.read_text(encoding="utf-8")))
        self.assertEqual(reports[0], reports[1])

    def test_candidate_axes_must_form_a_complete_cartesian_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "candidates.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "candidates": [
                            {
                                "id": "m1-a1",
                                "model": "m1",
                                "agent": "a1",
                                "adapter": "mock",
                                "config": {},
                            },
                            {
                                "id": "m1-a2",
                                "model": "m1",
                                "agent": "a2",
                                "adapter": "mock",
                                "config": {},
                            },
                            {
                                "id": "m2-a1",
                                "model": "m2",
                                "agent": "a1",
                                "adapter": "mock",
                                "config": {},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchInputError, "matrix is incomplete: m2×a2"):
                load_candidates(path)

    def test_candidate_boundary_excludes_gold_and_oracle_fields(self):
        task = load_tasks(TASKS)[0]
        request = CandidateRequest.from_payload(task["candidate_payload"])
        visible = request.__dict__
        self.assertNotIn("expected_output", visible)
        self.assertNotIn("required_evidence", visible)
        self.assertNotIn("safety_policy", visible)
        self.assertNotIn("oracle", json.dumps(visible, sort_keys=True))
        candidate = load_candidates(CANDIDATES)[0]
        poisoned = dict(task)
        poisoned["expected_output"] = {"status": "answer", "value": "POISON", "reason_codes": []}
        self.assertNotEqual(
            MockAdapter().execute(request, candidate, OfflineMockTools(request)).output,
            poisoned["expected_output"],
        )

    def test_four_negative_controls_are_independently_graded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            trace_path = root / "trace.jsonl"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--tasks",
                        str(TASKS),
                        "--config",
                        str(NEGATIVE_CONTROLS),
                        "--output",
                        str(trace_path),
                        "--run-id",
                        "failures",
                        "--slice",
                        "market_data",
                        "--variant",
                        "valid_book",
                    ]
                )
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(stdout.getvalue())["failed_cells"], 3)
            traces = {row["candidate"]["agent"]: row for row in read_traces([trace_path])}
            self.assertEqual(traces["wrong-answer"]["score"]["correctness"], 0)
            self.assertEqual(traces["missing-evidence"]["score"]["evidence_quality"], 0)
            self.assertFalse(traces["forbidden-action"]["score"]["hard_gate_passed"])
            self.assertEqual(traces["tool-error"]["error"]["code"], "TOOL_ERROR")
            self.assertEqual(
                {
                    row["failure_signature"]["code"]
                    for row in traces.values()
                    if row["failure_signature"] is not None
                },
                {"WRONG_ANSWER", "MISSING_EVIDENCE", "SAFETY_HARD_GATE"},
            )
            self.assertIsNone(traces["tool-error"]["failure_signature"])
            self.assertFalse(traces["tool-error"]["score"]["eligible_for_quality_aggregation"])

    def test_task_schema_has_ten_core_fields_and_p2_pairs_cover_eight_slices(self):
        validator = task_validator()
        validator.check_schema(validator.schema)
        cards = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            set(validator.schema["properties"]),
            {
                "id",
                "slice",
                "prompt",
                "fixtures",
                "tools",
                "budget",
                "checks",
                "tags",
                "variants",
                "notes",
            },
        )
        self.assertEqual(
            {card["slice"] for card in cards},
            {
                "market_data",
                "fundamentals",
                "earnings",
                "news_filings",
                "portfolio",
                "derivatives",
                "technical_analysis",
                "rules_safety",
            },
        )
        self.assertTrue(all(len(card["variants"]) >= 2 for card in cards))
        self.assertTrue(all(card["tags"]["lifecycle"] == "dev" for card in cards))

    def test_audit_rejects_future_information_and_unpiloted_eval(self):
        cards = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
        cards[3]["variants"][1]["expected"] = {
            "status": "answer",
            "value": "guidance_restored",
            "reason_codes": [],
        }
        cards[0]["tags"]["lifecycle"] = "eval"
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "tasks.jsonl"
            path.write_text("\n".join(json.dumps(card) for card in cards) + "\n", encoding="utf-8")
            audit = audit_taskset(path)
        self.assertFalse(audit["checks"]["future_information"]["passed"])
        self.assertFalse(audit["checks"]["eval_without_pilot"]["passed"])

    def test_tampered_gold_is_rejected_by_oracle_recomputation(self):
        cards = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
        cards[2]["variants"][0]["expected"]["value"] = 99.0
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "fixtures").mkdir()
            source_fixture = ROOT / "tasks" / "dev" / "fixtures" / "us-filing-synthetic.json"
            (root / "fixtures" / source_fixture.name).write_bytes(source_fixture.read_bytes())
            path = root / "tasks.jsonl"
            path.write_text(json.dumps(cards[2]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchInputError, "expected value does not recompute"):
                load_tasks(path)

    def test_non_mock_adapter_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "candidates.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "candidates": [
                            {
                                "id": "paid",
                                "model": "live-model",
                                "agent": "plain",
                                "adapter": "live",
                                "config": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchInputError, "run config schema failed"):
                load_candidates(path)

    def test_duplicate_task_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "tasks.jsonl"
            path.write_text(
                '{"task_id":"same","input":1}\n{"task_id":"same","input":2}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchInputError, "duplicate task_id"):
                load_tasks(path)

    def test_persisted_secret_gate_rejects_trace_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = pathlib.Path(temporary) / "trace.jsonl"
            trace = {
                "schema_version": "0.6.0",
                "trace_id": "trace",
                "run_id": "run",
                "task": {"id": "task", "slice": "market_data", "variant": "default"},
                "candidate": {
                    "id": "candidate",
                    "model": "mock",
                    "agent": "plain",
                    "adapter": "mock",
                    "adapter_version": "0.1.0",
                    "config": {"api_key": "not-persistable"},
                    "config_sha256": "0" * 64,
                },
                "input": {},
                "agent_events": [],
                "tool_calls": [],
                "provider_identity": None,
                "provider_observability": None,
                "output": {},
                "error": None,
                "evidence_refs": [],
                "safety_violations": [],
                "score": {
                    "correctness": 4,
                    "evidence_quality": 2,
                    "safety": 1,
                    "hard_gate_passed": True,
                    "eligible_for_quality_aggregation": True,
                },
                "failure_signature": None,
                "metrics": {
                    "latency_ms": 0,
                    "input_tokens_estimate": 0,
                    "output_tokens_estimate": 0,
                    "cost_usd_estimate": "0.000000",
                    "cost_basis": "mock_zero",
                },
                "versions": {"trace_schema_version": "0.6.0"},
                "started_at": "2026-08-18T00:00:00Z",
                "finished_at": "2026-08-18T00:00:00Z",
            }
            with self.assertRaisesRegex(ValueError, "persisted-secret gate"):
                append_traces(trace_path, [trace])
            self.assertFalse(trace_path.exists())


if __name__ == "__main__":
    unittest.main()
