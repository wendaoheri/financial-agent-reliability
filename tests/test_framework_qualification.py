from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.models import load_candidates, load_tasks
from financial_agent_reliability.qualification import (
    QualificationError,
    replay_qualification,
    run_qualification,
)
from financial_agent_reliability.runner import version_coordinates

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
                versions=version_coordinates(
                    repository_root=ROOT, tasks_path=TASKS, config_path=CONFIG
                ),
            )
            self.assertEqual(manifest["status"], "passed")
            report = replay_qualification(tasks, candidates, bundle)
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
            matrix = json.loads((bundle / "calibration_matrix.json").read_text(encoding="utf-8"))
            by_mutation = {row["mutation"]: row for row in matrix}
            baseline = by_mutation["NONE"]["actual"]["components"]
            for mutation, component in {
                "ACTION": "action",
                "VALUE": "value",
                "REASON": "reason",
                "CITATION": "citation",
                "SAFETY": "safety",
            }.items():
                changed = by_mutation[mutation]["actual"]["components"]
                differences = {key for key in baseline if baseline[key] != changed[key]}
                self.assertEqual(differences, {component})

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
                versions=version_coordinates(
                    repository_root=ROOT, tasks_path=TASKS, config_path=CONFIG
                ),
            )
            with (bundle / "aggregate.json").open("a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(QualificationError, "hash mismatch"):
                replay_qualification(tasks, candidates, bundle)


if __name__ == "__main__":
    unittest.main()
