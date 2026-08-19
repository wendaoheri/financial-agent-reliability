from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from financial_agent_reliability.bench.adapters import CandidateRequest, MockAdapter, OfflineMockTools
from financial_agent_reliability.bench.cli import main
from financial_agent_reliability.bench.model import (
    BenchInputError,
    audit_taskset,
    load_candidates,
    load_tasks,
    task_validator,
)
from financial_agent_reliability.bench.trace import append_traces, read_traces, trace_validator


ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "examples" / "bench" / "mock-tasks.jsonl"
CANDIDATES = ROOT / "examples" / "bench" / "mock-candidates.json"
NEGATIVE_CONTROLS = ROOT / "examples" / "bench" / "negative-control-candidates.json"
AUDIT = ROOT / "examples" / "bench" / "taskset-audit.v0.2.json"


class BenchMVPTests(unittest.TestCase):
    def test_trace_schema_is_valid_and_checkable(self):
        validator = trace_validator()
        validator.check_schema(validator.schema)
        legacy_validator = trace_validator("0.1.0")
        legacy_validator.check_schema(legacy_validator.schema)

    def test_validate_accepts_model_agent_axes(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["validate", "--tasks", str(TASKS), "--candidates", str(CANDIDATES)])
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
                        "--candidates",
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
            self.assertTrue(all(row["metrics"]["cost_usd_estimate"] == "0.000000" for row in traces))
            self.assertTrue(all(row["score"] == {
                "correctness": 4,
                "evidence_quality": 0,
                "safety": 1,
                "hard_gate_passed": True,
                "eligible_for_quality_aggregation": True,
            } for row in plain))
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
                        "--candidates",
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
            self.assertEqual(len(report["candidates"]), 4)
            self.assertTrue(all(row["traces"] == 16 for row in report["candidates"]))
            self.assertEqual(len(report["by_slice"]), 8)
            self.assertEqual(len(report["by_variant"]), 16)
            self.assertEqual(len(report["by_model"]), 2)
            self.assertEqual(len(report["by_agent"]), 2)
            self.assertEqual(report["overall"]["operational_metrics"]["cost_usd_estimate"], "0.000000")
            agent_contrast = next(
                item for item in report["overall"]["paired_contrasts"]
                if item["axis"] == "agent"
            )
            model_contrast = next(
                item for item in report["overall"]["paired_contrasts"]
                if item["axis"] == "model"
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
                    "run", "--tasks", str(TASKS), "--candidates", str(CANDIDATES),
                    "--output", str(trace_path), "--run-id", "filtered",
                    "--slice", "portfolio", "--variant", "execute_trade",
                    "--candidate", "mock-small__plain-agent",
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
                    self.assertEqual(main([
                        "run", "--tasks", str(TASKS), "--candidates", str(CANDIDATES),
                        "--output", str(trace_path), "--run-id", f"repeat-{index}",
                    ]), 1)
                    self.assertEqual(
                        main(["compare", str(trace_path), "--output", str(report_path)]), 0
                    )
                reports.append(json.loads(report_path.read_text(encoding="utf-8")))
        self.assertEqual(reports[0], reports[1])

    def test_candidate_axes_must_form_a_complete_cartesian_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "candidates.json"
            path.write_text(json.dumps({"candidates": [
                {"id": "m1-a1", "model": "m1", "agent": "a1", "adapter": "mock"},
                {"id": "m1-a2", "model": "m1", "agent": "a2", "adapter": "mock"},
                {"id": "m2-a1", "model": "m2", "agent": "a1", "adapter": "mock"},
            ]}), encoding="utf-8")
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
                status = main([
                    "run", "--tasks", str(TASKS), "--candidates", str(NEGATIVE_CONTROLS),
                    "--output", str(trace_path), "--run-id", "failures",
                    "--slice", "market_data", "--variant", "valid_book",
                ])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(stdout.getvalue())["failed_cells"], 4)
            traces = {row["candidate"]["agent"]: row for row in read_traces([trace_path])}
            self.assertEqual(traces["wrong-answer"]["score"]["correctness"], 0)
            self.assertEqual(traces["missing-evidence"]["score"]["evidence_quality"], 0)
            self.assertFalse(traces["forbidden-action"]["score"]["hard_gate_passed"])
            self.assertEqual(traces["tool-error"]["error"]["code"], "TOOL_ERROR")
            self.assertEqual(
                {row["failure_signature"]["code"] for row in traces.values()},
                {"WRONG_ANSWER", "MISSING_EVIDENCE", "SAFETY_HARD_GATE", "TOOL_ERROR"},
            )

    def test_task_schema_has_ten_core_fields_and_p2_pairs_cover_eight_slices(self):
        validator = task_validator()
        validator.check_schema(validator.schema)
        cards = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            set(validator.schema["properties"]),
            {"id", "slice", "prompt", "fixtures", "tools", "budget", "checks", "tags", "variants", "notes"},
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

    def test_committed_taskset_audit_matches_fresh_machine_checks(self):
        committed = json.loads(AUDIT.read_text(encoding="utf-8"))
        fresh = audit_taskset(TASKS)
        for field in ("cards", "variants", "slices", "lifecycles", "checks"):
            self.assertEqual(committed[field], fresh[field])
        self.assertTrue(all(result["passed"] for result in fresh["checks"].values()))

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

    def test_scoring_contract_keeps_safety_as_hard_gate_and_cost_separate(self):
        contract_path = ROOT / "src" / "financial_agent_reliability" / "bench" / "contracts" / "scoring-contract.v0.1.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["dimensions"]["correctness"]["range"], [0, 4])
        self.assertEqual(contract["dimensions"]["evidence_quality"]["range"], [0, 2])
        self.assertEqual(contract["dimensions"]["safety"]["allowed"], [0, 1])
        self.assertTrue(contract["dimensions"]["safety"]["hard_gate"])
        self.assertNotIn("latency_ms", contract["dimensions"])
        self.assertIn("latency_ms", contract["reported_separately"])

    def test_tampered_gold_is_rejected_by_oracle_recomputation(self):
        cards = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
        cards[2]["variants"][0]["expected"]["value"] = 99.0
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "fixtures").mkdir()
            source_fixture = ROOT / "examples" / "bench" / "fixtures" / "us-filing-synthetic.json"
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
                        "candidates": [
                            {
                                "id": "paid",
                                "model": "live-model",
                                "agent": "plain",
                                "adapter": "live",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BenchInputError, "only permits the offline mock"):
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
                "schema_version": "0.2.0",
                "trace_id": "trace",
                "run_id": "run",
                "task": {"id": "task", "slice": "legacy", "variant": "default"},
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
                "tool_calls": [],
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
                },
                "git": {"commit": "0" * 40, "dirty": False},
                "versions": {"trace_schema_version": "0.2.0"},
                "started_at": "2026-08-18T00:00:00Z",
                "finished_at": "2026-08-18T00:00:00Z",
            }
            with self.assertRaisesRegex(ValueError, "persisted-secret gate"):
                append_traces(trace_path, [trace])
            self.assertFalse(trace_path.exists())


if __name__ == "__main__":
    unittest.main()
