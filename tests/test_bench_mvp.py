from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from financial_agent_reliability.bench.cli import main
from financial_agent_reliability.bench.model import BenchInputError, load_candidates, load_tasks
from financial_agent_reliability.bench.trace import append_traces, read_traces, trace_validator


ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "examples" / "bench" / "mock-tasks.jsonl"
CANDIDATES = ROOT / "examples" / "bench" / "mock-candidates.json"


class BenchMVPTests(unittest.TestCase):
    def test_trace_schema_is_valid_and_checkable(self):
        validator = trace_validator()
        validator.check_schema(validator.schema)

    def test_validate_accepts_model_agent_axes(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["validate", "--tasks", str(TASKS), "--candidates", str(CANDIDATES)])
        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"status": "valid", "tasks": 2, "candidates": 2},
        )

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
            self.assertEqual(len(traces), 4)
            self.assertEqual({row["candidate"]["model"] for row in traces}, {"mock-base"})
            self.assertEqual(
                {row["candidate"]["agent"] for row in traces},
                {"plain-agent", "tool-agent"},
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
            self.assertTrue(all(row["traces"] == 2 for row in report["candidates"]))

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
