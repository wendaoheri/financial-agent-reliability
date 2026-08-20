from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from financial_agent_reliability.adapters.core import AdapterResult
from financial_agent_reliability.compare import compare_traces
from financial_agent_reliability.contracts import (
    candidate_output_contract,
    validate_candidate_output,
)
from financial_agent_reliability.models import load_candidates, load_tasks
from financial_agent_reliability.qualification import (
    QualificationError,
    replay_qualification,
    run_qualification,
)
from financial_agent_reliability.runner import run_matrix, version_coordinates
from financial_agent_reliability.trace import read_traces

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "dev" / "tasks.jsonl"
CONFIG = ROOT / "configs" / "framework-qualification.v1.json"


class FrameworkQualificationTests(unittest.TestCase):
    def _selection(self):
        tasks = [
            task
            for task in load_tasks(TASKS)
            if task["task_card"]
            == {
                "id": "market-orderbook-integrity",
                "slice": "market_data",
                "variant": "valid_book",
            }
        ]
        return tasks, load_candidates(CONFIG)

    def test_candidate_contract_is_complete_and_gold_free(self):
        task = load_tasks(TASKS)[0]
        contract = task["candidate_payload"]["output_contract"]
        self.assertEqual(contract["required_fields"], ["status", "value", "reason_codes"])
        self.assertIn("MARKET_DATA_ANOMALY", contract["reason_code_enum"])
        self.assertEqual(contract["value_schema"], {"type": ["number", "null"]})
        rendered = json.dumps(task["candidate_payload"], sort_keys=True)
        self.assertNotIn("expected_output", rendered)
        self.assertNotIn('"checks"', rendered)
        self.assertNotIn('"oracle"', rendered)

    def test_matrix_replays_and_excludes_invalid_runs(self):
        tasks, candidates = self._selection()
        with tempfile.TemporaryDirectory() as temporary:
            bundle = pathlib.Path(temporary) / "bundle"
            manifest = run_qualification(
                tasks,
                candidates,
                repository_root=ROOT,
                output_directory=bundle,
                run_id="qualification-test",
                versions=version_coordinates(tasks_path=TASKS, config_path=CONFIG),
            )
            self.assertEqual(manifest["status"], "passed")
            self.assertRegex(manifest["eval_pack_id"], r"^[0-9a-f]{64}$")
            self.assertEqual(manifest["runner_protocol_version"], "1.0.0")
            report = replay_qualification(tasks, candidates, bundle)
            self.assertEqual(report["eval_pack_id"], manifest["eval_pack_id"])
            self.assertEqual(report["runner_protocol_version"], "1.0.0")
            self.assertEqual(
                report["outcome_counts"],
                {"candidate_success": 1, "candidate_failure": 6, "invalid_run": 3},
            )
            aggregate = json.loads((bundle / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["classification_accuracy"], 1.0)
            self.assertEqual(aggregate["csr_denominator"], 7)
            self.assertEqual(aggregate["invalid_runs_excluded"], 3)
            failures = json.loads((bundle / "failure_signatures.json").read_text(encoding="utf-8"))
            self.assertEqual(len(failures), 6)
            comparison = compare_traces(read_traces([bundle / "traces.jsonl"]))
            self.assertEqual(comparison["schema_version"], "0.4.0")
            self.assertEqual(comparison["overall"]["valid_runs"], 7)
            self.assertEqual(comparison["overall"]["invalid_runs_excluded"], 3)
            self.assertEqual(comparison["overall"]["scores"]["eligible_quality_runs"], 6)
            self.assertEqual(comparison["overall"]["scores"]["average_correctness"], 2.0)
            self.assertEqual(comparison["overall"]["scores"]["average_evidence_quality"], 1.333)
            self.assertEqual(
                comparison["overall"]["uncertainty_95"]["safety_effective_sample_size"], 7
            )
            matrix = json.loads((bundle / "calibration_matrix.json").read_text(encoding="utf-8"))
            by_mutation = {row["mutation"]: row for row in matrix}
            self.assertTrue(all(row["matched"] for row in matrix))
            for mutation in ("ACTION", "VALUE", "REASON"):
                case_id = by_mutation[mutation]["case_id"]
                trace = next(
                    row
                    for row in read_traces([bundle / "traces.jsonl"])
                    if row["candidate"]["id"] == case_id
                )
                contract_errors = validate_candidate_output(
                    tasks[0]["candidate_payload"]["output_contract"], trace["output"]
                )
                self.assertEqual(contract_errors, [], mutation)

    def test_output_contract_vectors(self):
        contract = candidate_output_contract("orderbook_spread")
        vectors = [
            ({"status": "answer", "value": 0.04, "reason_codes": []}, True),
            ({"status": "abstain", "value": None, "reason_codes": ["MARKET_DATA_ANOMALY"]}, True),
            ({"status": "refuse", "value": None, "reason_codes": ["REAL_TRADE_FORBIDDEN"]}, True),
            ({"status": "answer", "value": "WRONG", "reason_codes": []}, False),
            ({"status": "answer", "value": 0.04, "reason_codes": ["INSUFFICIENT_EVIDENCE"]}, False),
            ({"status": "abstain", "value": None, "reason_codes": ["UNKNOWN"]}, False),
        ]
        for output, valid in vectors:
            with self.subTest(output=output):
                self.assertEqual(not validate_candidate_output(contract, output), valid)

    def test_central_gate_excludes_protocol_error_from_model_failures(self):
        tasks, candidates = self._selection()

        class InvalidOutputAdapter:
            version = "fixture"

            def execute(self, request, candidate, tools):
                return AdapterResult(
                    output={"status": "answer", "value": "WRONG", "reason_codes": []},
                    error=None,
                    latency_ms=1,
                )

        with patch(
            "financial_agent_reliability.runner.get_adapter",
            return_value=InvalidOutputAdapter(),
        ):
            traces = run_matrix(
                tasks,
                candidates[:1],
                repository_root=ROOT,
                run_id="central-protocol-gate",
                versions=version_coordinates(tasks_path=TASKS, config_path=CONFIG),
            )
        self.assertEqual(traces[0]["error"]["code"], "INVALID_MODEL_OUTPUT")
        self.assertFalse(traces[0]["score"]["eligible_for_quality_aggregation"])
        self.assertIsNone(traces[0]["failure_signature"])

    def test_manifest_detects_tampering_before_regrade(self):
        tasks, candidates = self._selection()
        with tempfile.TemporaryDirectory() as temporary:
            bundle = pathlib.Path(temporary) / "bundle"
            run_qualification(
                tasks,
                candidates,
                repository_root=ROOT,
                output_directory=bundle,
                run_id="tamper-test",
                versions=version_coordinates(tasks_path=TASKS, config_path=CONFIG),
            )
            with (bundle / "aggregate.json").open("a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(QualificationError, "hash mismatch"):
                replay_qualification(tasks, candidates, bundle)


if __name__ == "__main__":
    unittest.main()
