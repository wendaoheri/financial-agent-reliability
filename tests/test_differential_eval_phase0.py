"""Phase 0 differential-evaluation contract and replay tests."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.experiments.phase0 import (
    FIXTURES_PATH,
    PILOT_FAMILIES,
    TASK_SET_PATH,
    assess_pilot_admission,
    run_phase0_dev,
    validate_phase0,
)
from financial_agent_reliability.security import scan_persisted_file


class DifferentialEvalPhase0Tests(unittest.TestCase):
    def test_task_set_passes_all_offline_admission_gates(self):
        validation = validate_phase0()
        self.assertEqual(validation["errors"], [])
        self.assertEqual(validation["status"], "passed")
        self.assertEqual(validation["task_count"], 16)
        self.assertEqual(validation["family_count"], 8)
        self.assertEqual(validation["pilot_task_count"], 8)
        self.assertEqual(validation["oracle_cross_checks"], 16)
        self.assertEqual(validation["single_factor_pairs"], 8)

    def test_task_cards_remain_lightweight_and_pilot_is_48_units(self):
        task_set = json.loads(TASK_SET_PATH.read_text(encoding="utf-8"))
        self.assertEqual(task_set["claim_level"], "diagnostic_only_no_ranking")
        self.assertEqual(len(task_set["candidate_models"]), 3)
        self.assertEqual(task_set["agent_variants"], ["A0", "A1"])
        self.assertEqual(task_set["candidate_output_contract"]["version"], "2.0.0")
        self.assertEqual(
            set(task_set["family_output_contracts"]),
            {
                "GOAL-01",
                "EVID-01",
                "CALC-01",
                "METHOD-01",
                "CLAIM-01",
                "UNCERT-01",
                "SAFE-01",
                "SUIT-01",
            },
        )
        self.assertEqual(set(task_set["pilot_families"]), set(PILOT_FAMILIES))
        pilot_cards = [
            task for task in task_set["tasks"] if task["notes"]["family_id"] in PILOT_FAMILIES
        ]
        self.assertEqual(len(pilot_cards) * 3 * 2, 48)
        for task in task_set["tasks"]:
            self.assertLessEqual(len(task), 10)
            self.assertEqual(task["budget"]["a0_model_requests"], 1)
            self.assertEqual(task["budget"]["a1_model_requests"], 4)

    def test_task_and_fixture_sources_are_secret_clean(self):
        self.assertEqual(scan_persisted_file(TASK_SET_PATH), [])
        self.assertEqual(scan_persisted_file(FIXTURES_PATH), [])

    def test_synthetic_replay_is_deterministic_and_diagnostic_only(self):
        with (
            tempfile.TemporaryDirectory() as first_raw,
            tempfile.TemporaryDirectory() as second_raw,
        ):
            first = pathlib.Path(first_raw)
            second = pathlib.Path(second_raw)
            first_summary = run_phase0_dev(first)
            run_phase0_dev(second)
            self.assertEqual(first_summary["status"], "passed")
            self.assertTrue(first_summary["offline_admission_passed"])
            self.assertFalse(first_summary["pilot_ready"])
            self.assertEqual(first_summary["pending_gates"], ["live_identity_preflight"])
            self.assertEqual(first_summary["trace_count"], 32)
            self.assertEqual(first_summary["failure_signature_count"], 4)
            for filename in (
                "phase0.validation.json",
                "trace.jsonl",
                "aggregate.json",
                "failure_signatures.json",
            ):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
                if filename != "trace.jsonl":
                    self.assertEqual(scan_persisted_file(first / filename), [])

            aggregate = json.loads((first / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["claim_level"], "synthetic_diagnostic_only")
            overall = aggregate["results"]["overall"]
            self.assertEqual(overall["A0"]["critical_success_rate"], 0.75)
            self.assertEqual(overall["A1"]["critical_success_rate"], 1.0)
            challenge = aggregate["results"]["variant"]["challenge"]
            self.assertEqual(challenge["A0"]["critical_success_rate"], 0.5)
            self.assertEqual(challenge["A1"]["critical_success_rate"], 1.0)
            self.assertEqual(overall["A0"]["tokens"], 0)
            self.assertEqual(overall["A1"]["cost_usd"], "0.000000")

            trace_rows = [
                json.loads(line)
                for line in (first / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(all(row["candidate_kind"] == "synthetic_mock" for row in trace_rows))
            self.assertTrue(
                all(row["network_scope"] == "none_offline_fixture" for row in trace_rows)
            )
            self.assertEqual(
                scan_persisted_file(first / "aggregate.json"),
                [],
            )

    def test_pilot_admission_requires_matching_three_model_preflight(self):
        with tempfile.TemporaryDirectory() as raw:
            output = pathlib.Path(raw)
            summary = run_phase0_dev(output)
            preflight = {
                "status": "passed",
                "counts": {"blocked": 0, "invalidated": 0, "passed": 3, "requested": 3},
                "config_sha256": summary["version"]["pilot_config_sha256"],
                "models": [
                    {
                        "status": "passed",
                        "identity": {"exact_match": True},
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    }
                    for _ in range(3)
                ],
            }
            preflight_path = output / "live-preflight.json"
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            admission = assess_pilot_admission(output, preflight_path)
            self.assertEqual(admission["status"], "passed")
            self.assertTrue(admission["pilot_ready"])
            self.assertEqual(admission["matrix_units"], 48)
            self.assertEqual(admission["preflight_usage"]["total_tokens"], 6)
            self.assertEqual(scan_persisted_file(output / "pilot.admission.json"), [])

            preflight["config_sha256"] = "0" * 64
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            rejected = assess_pilot_admission(output, preflight_path)
            self.assertFalse(rejected["pilot_ready"])
            self.assertFalse(rejected["gates"]["pilot_config_hash_match"])


if __name__ == "__main__":
    unittest.main()
