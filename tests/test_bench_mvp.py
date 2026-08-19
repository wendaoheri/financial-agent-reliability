from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

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
AUDIT = ROOT / "examples" / "bench" / "taskset-audit.v0.2.json"


class BenchMVPTests(unittest.TestCase):
    def test_trace_schema_is_valid_and_checkable(self):
        validator = trace_validator()
        validator.check_schema(validator.schema)

    def test_validate_accepts_model_agent_axes(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["validate", "--tasks", str(TASKS), "--candidates", str(CANDIDATES)])
        self.assertEqual(status, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["tasks"], 16)
        self.assertEqual(result["candidates"], 2)
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
            self.assertEqual(status, 0)
            traces = list(read_traces([trace_path]))
            self.assertEqual(len(traces), 32)
            self.assertEqual({row["candidate"]["model"] for row in traces}, {"mock-base"})
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
            self.assertTrue(all(row["tool_calls"] == [] for row in traces))
            self.assertTrue(all(row["metrics"]["cost_usd_estimate"] == "0.000000" for row in traces))

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
                0,
            )
            before = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(["compare", str(trace_path), "--output", str(report_path)])
            after = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            self.assertEqual(status, 0)
            self.assertEqual(before, after)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["candidates"]), 2)
            self.assertTrue(all(row["traces"] == 16 for row in report["candidates"]))

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
                "schema_version": "0.1.0",
                "trace_id": "trace",
                "run_id": "run",
                "task": {"id": "task"},
                "candidate": {
                    "id": "candidate",
                    "model": "mock",
                    "agent": "plain",
                    "adapter": "mock",
                    "config": {"api_key": "not-persistable"},
                    "config_sha256": "0" * 64,
                },
                "input": {},
                "tool_calls": [],
                "output": {},
                "error": None,
                "metrics": {
                    "latency_ms": 0,
                    "input_tokens_estimate": 0,
                    "output_tokens_estimate": 0,
                    "cost_usd_estimate": "0.000000",
                },
                "git": {"commit": "0" * 40, "dirty": False},
                "started_at": "2026-08-18T00:00:00Z",
                "finished_at": "2026-08-18T00:00:00Z",
            }
            with self.assertRaisesRegex(ValueError, "persisted-secret gate"):
                append_traces(trace_path, [trace])
            self.assertFalse(trace_path.exists())


if __name__ == "__main__":
    unittest.main()
