"""Frozen PER-420 evaluation-pack validation and replay tests."""

from __future__ import annotations

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from financial_agent_reliability.cli import main
from financial_agent_reliability.contracts import validate_candidate_output
from financial_agent_reliability.eval_pack import (
    FAMILIES,
    PILOT_FAMILIES,
    EvalPackError,
    replay_eval_pack,
    run_eval_pack,
    validate_eval_pack,
)
from financial_agent_reliability.security import (
    scan_persisted_file,
    scan_persisted_value_for_secrets,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "tasks" / "per420"
TASKS = PACK / "task-contract.v2.json"
FIXTURES = PACK / "fixtures.v2.json"


class EvalPackTests(unittest.TestCase):
    def test_pack_passes_all_offline_asset_gates(self):
        validation = validate_eval_pack(PACK)
        self.assertEqual(validation["errors"], [])
        self.assertEqual(validation["status"], "passed")
        self.assertEqual(validation["task_count"], 16)
        self.assertEqual(validation["fixture_count"], 16)
        self.assertEqual(validation["family_count"], 8)
        self.assertEqual(validation["pilot_task_count"], 8)
        self.assertEqual(validation["oracle_cross_checks"], 16)
        self.assertEqual(validation["single_factor_pairs"], 8)
        self.assertEqual(
            set(validation["asset_hashes"]),
            {"tasks", "fixtures", "candidates", "harness", "scoring", "schema"},
        )

    def test_tasks_keep_all_dimensions_and_candidate_contracts(self):
        task_set = json.loads(TASKS.read_text(encoding="utf-8"))
        self.assertEqual(task_set["claim_level"], "diagnostic_only_no_ranking")
        self.assertEqual(len(task_set["candidate_models"]), 3)
        self.assertEqual(task_set["agent_variants"], ["A0", "A1"])
        self.assertEqual(task_set["candidate_output_contract"]["version"], "2.0.0")
        self.assertEqual(set(task_set["family_output_contracts"]), set(FAMILIES))
        self.assertEqual(set(task_set["pilot_families"]), set(PILOT_FAMILIES))
        self.assertEqual(
            {task["notes"]["dimension"] for task in task_set["tasks"]},
            {f"D{index}" for index in range(1, 9)},
        )
        pilot_cards = [
            task for task in task_set["tasks"] if task["notes"]["family_id"] in PILOT_FAMILIES
        ]
        self.assertEqual(len(pilot_cards) * 3 * 2, 48)

    def test_gold_uses_the_central_protocol_validator(self):
        task_set = json.loads(TASKS.read_text(encoding="utf-8"))
        task = task_set["tasks"][0]
        checks = task["checks"]
        output = {
            "action": checks["expected_action"],
            "value": checks["expected_value"],
            "reason_codes": checks["reason_codes"],
            "cited_record_ids": checks["cited_record_ids"],
        }
        errors = validate_candidate_output(
            task_set["candidate_output_contract"],
            output,
            family_contract=task_set["family_output_contracts"]["GOAL-01"],
        )
        self.assertEqual(errors, [])
        output["extra"] = True
        self.assertEqual(
            validate_candidate_output(
                task_set["candidate_output_contract"],
                output,
                family_contract=task_set["family_output_contracts"]["GOAL-01"],
            ),
            ["output keys must exactly match the declared contract"],
        )

    def test_pack_sources_are_secret_clean(self):
        for path in PACK.glob("*.json"):
            self.assertEqual(scan_persisted_file(path), [], path.name)

    def test_replay_is_deterministic_and_excludes_invalid_runs(self):
        with tempfile.TemporaryDirectory() as raw:
            temporary = pathlib.Path(raw)
            first = temporary / "first"
            second = temporary / "second"
            summary = run_eval_pack(PACK, first)
            run_eval_pack(PACK, second)

            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["network_calls_performed"], 0)
            self.assertEqual(summary["trace_count"], 48)
            self.assertEqual(summary["failure_signature_count"], 4)
            self.assertEqual(
                summary["outcome_counts"],
                {
                    "candidate_success": 28,
                    "candidate_failure": 4,
                    "invalid_run": 16,
                },
            )
            self.assertEqual(summary["csr_denominator"], 32)
            self.assertEqual(summary["invalid_runs_excluded"], 16)
            for filename in (
                "validation.json",
                "trace.jsonl",
                "aggregate.json",
                "failure_signatures.json",
                "manifest.json",
            ):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

            rows = [
                json.loads(line)
                for line in (first / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            invalid = [row for row in rows if row["outcome"] == "invalid_run"]
            self.assertEqual(len(invalid), 16)
            self.assertTrue(all(row["output"] is None for row in invalid))
            self.assertTrue(all(row["failure_signature"] is None for row in invalid))
            self.assertTrue(all(row["invalid_output"]["sha256"] for row in invalid))
            self.assertEqual(scan_persisted_value_for_secrets(rows), [])

            aggregate = json.loads((first / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["overall"]["csr"], 0.875)
            self.assertEqual(aggregate["claim_level"], "synthetic_diagnostic_only_no_ranking")
            replay = replay_eval_pack(PACK, first)
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["traces_regraded"], 48)
            self.assertEqual(replay["artifacts_verified"], 4)

    def test_replay_rejects_a_tampered_trace_before_regrade(self):
        with tempfile.TemporaryDirectory() as raw:
            bundle = pathlib.Path(raw) / "bundle"
            run_eval_pack(PACK, bundle)
            trace = bundle / "trace.jsonl"
            trace.write_text(trace.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(EvalPackError, "hash mismatch"):
                replay_eval_pack(PACK, bundle)

    def test_runner_version_is_informational_during_regrade(self):
        with tempfile.TemporaryDirectory() as raw:
            bundle = pathlib.Path(raw) / "bundle"
            run_eval_pack(PACK, bundle)
            with mock.patch(
                "financial_agent_reliability.eval_pack.RUNNER_PROTOCOL_VERSION",
                "99.0.0",
            ):
                report = replay_eval_pack(PACK, bundle)
            self.assertEqual(report["recorded_runner_protocol_version"], "1.0.0")
            self.assertEqual(report["regrade_runner_protocol_version"], "99.0.0")

    def test_eval_validate_is_exposed_only_through_bench(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["eval-validate", "--pack", str(PACK)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")


if __name__ == "__main__":
    unittest.main()
