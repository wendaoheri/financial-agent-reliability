"""Baseline-v3 bundle, licensing, oracle, grader, and append-only tests."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest
from copy import deepcopy

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline" / "v3"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(BASELINE))

import validate_baseline_v3 as validator  # noqa: E402
from financial_agent_reliability.graders import baseline_v3 as grader_v3  # noqa: E402
from financial_agent_reliability.harness.secret_scan import (  # noqa: E402
    scan_persisted_value_for_secrets,
)
from financial_agent_reliability.oracles.public_filings import oracle  # noqa: E402
from financial_agent_reliability.oracles.public_filings import oracle_reference  # noqa: E402
from financial_agent_reliability.oracles.synthetic import oracle_reference_v3  # noqa: E402
from financial_agent_reliability.oracles.synthetic import oracle_v3  # noqa: E402


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_hash(entries: list[dict]) -> str:
    lines = "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def cases() -> list[dict]:
    return [load(path) for path in sorted((BASELINE / "cases").glob("case-*.json"))]


def snapshots() -> dict[str, dict]:
    result = {}
    for path in sorted((BASELINE / "snapshots").glob("data_snapshot.*.json")):
        item = load(path)
        result[item["snapshot_id"]] = item
    return result


class BaselineV3FreezeTests(unittest.TestCase):
    def test_v2_has_zero_drift(self):
        self.assertEqual(
            sha256(ROOT / "baseline/v2/baseline_manifest.frozen.v2.json"),
            "02b91c8bd80d1c3b80ed1dd924c45c3a454bcb4780a8edad9b7cbf15a6d6e428",
        )
        self.assertEqual(
            sha256(ROOT / "docs/contracts/acceptance-criteria-v2.md"),
            "5dd9529df4f11411b6b6717335ca65b323212eacc90f5c8382143898a73997f2",
        )

    def test_manifest_and_bundle_are_complete(self):
        self.assertEqual(validator.verify_manifest(BASELINE), [])
        manifest = load(BASELINE / "baseline_manifest.frozen.v3.json")
        self.assertEqual(manifest["contract_version"], "3.0.0")
        self.assertEqual(manifest["bundle_sha256"], bundle_hash(manifest["artifacts"]))
        paths = {entry["path"] for entry in manifest["artifacts"]}
        for required in (
            "baseline/v3/contracts/case_card.schema.v3.json",
            "baseline/v3/contracts/data_snapshot.schema.v3.json",
            "baseline/v3/contracts/run_trace.schema.v5.json",
            "baseline/v3/contracts/grader_contract.frozen.v3.json",
            "baseline/v3/grader/grader_policy.v3.json",
            "baseline/v3/build/capture_manifest.v3.json",
            "baseline/v3/validate_baseline_v3.py",
        ):
            self.assertIn(required, paths)

    def test_bundle_semantics(self):
        self.assertEqual(validator.validate_bundle(BASELINE), [])
        self.assertEqual(len(cases()), 12)
        self.assertEqual(len(snapshots()), 8)

    def test_cases_and_snapshots_validate_against_v3_schemas(self):
        case_schema = load(BASELINE / "contracts/case_card.schema.v3.json")
        snapshot_schema = load(BASELINE / "contracts/data_snapshot.schema.v3.json")
        resolved_snapshot_schema = deepcopy(snapshot_schema)
        resolved_snapshot_schema["properties"]["financial_subject"] = case_schema["$defs"]["financial_subject"]
        resolved_snapshot_schema["properties"]["integrity"] = case_schema["$defs"]["integrity"]
        for card in cases():
            jsonschema.Draft202012Validator(case_schema).validate(card)
        for snapshot in snapshots().values():
            jsonschema.Draft202012Validator(resolved_snapshot_schema).validate(snapshot)

    def test_only_redistributable_or_synthetic_data_is_present(self):
        capture_manifest = load(BASELINE / "build/capture_manifest.v3.json")
        self.assertTrue(capture_manifest["license_gate"]["all_artifacts_redistributable"])
        self.assertFalse(capture_manifest["license_gate"]["licensed_market_data_included"])
        self.assertTrue(all(item["redistributable"] for item in capture_manifest["captures"]))
        self.assertEqual(
            {item["source_provider"] for item in capture_manifest["captures"]},
            {"sec_edgar", "project_synthetic"},
        )
        for item in snapshots().values():
            self.assertTrue(item["source"]["license"]["redistributable"])
            self.assertIn(item["source"]["provider"], {"sec_edgar", "project_synthetic"})
        for card in cases():
            self.assertTrue(card["source"]["license"]["redistributable"])

    def test_grader_contract_recomputes(self):
        contract = load(BASELINE / "contracts/grader_contract.frozen.v3.json")
        for entry in contract["files"]:
            self.assertEqual(sha256(ROOT / entry["path"]), entry["sha256"])
        self.assertEqual(contract["contract_bundle_sha256"], bundle_hash(contract["files"]))

    def test_policy_invariants_equal_executable_invariants(self):
        policy = load(BASELINE / "grader/grader_policy.v3.json")
        self.assertEqual(
            policy["critical_success"]["allowed_invariants"],
            list(grader_v3.SUPPORTED_INVARIANTS),
        )
        for card in cases():
            self.assertEqual(
                card["applicable_critical_invariants"],
                list(grader_v3.SUPPORTED_INVARIANTS),
            )

    def test_gold_and_silver_expectations_have_two_equal_oracles(self):
        frozen_snapshots = snapshots()
        for card in cases():
            snapshot = frozen_snapshots[card["evidence_refs"][0]["snapshot_id"]]
            inputs = card["task"]["inputs"]
            if card["variant"]["family_id"].startswith("FKW3"):
                production = oracle.evaluate(snapshot, inputs)
                independent = oracle_reference.recompute(snapshot, inputs)
            else:
                production = oracle_v3.evaluate(snapshot, inputs)
                independent = oracle_reference_v3.recompute(snapshot, inputs)
            expected = {
                "status": card["oracle"]["expected_status"],
                "value": card["oracle"]["expected_value"],
                "reason_codes": card["oracle"]["reason_codes"],
            }
            self.assertEqual(production, independent, card["case_id"])
            self.assertEqual(production, expected, card["case_id"])

    def test_registered_expectations_pass_all_grader_invariants(self):
        for card in cases():
            submission = {
                "action": card["oracle"]["expected_status"],
                "value": card["oracle"]["expected_value"],
                "reason_codes": card["oracle"]["reason_codes"],
                "cited_record_ids": card["evidence_contract"]["material_record_ids"],
                "method_id": card["task"]["method_id"],
                "observed_operations": ["read_snapshot"],
                "final_environment_state": card["task"]["expected_final_environment_state"],
            }
            if card["evidence_tier_requirement"]:
                submission["evidence_tier_labels"] = {
                    "registered_conclusion": "research_direct_evidence"
                }
            row = grader_v3.grade_run(
                case=card,
                oracle_result={
                    "status": card["oracle"]["expected_status"],
                    "value": card["oracle"]["expected_value"],
                    "reason_codes": card["oracle"]["reason_codes"],
                },
                submission=submission,
                commitments={
                    "candidate_sha256": "1" * 64,
                    "trace_sha256": "2" * 64,
                    "projection_sha256": "3" * 64,
                    "snapshot_sha256": "4" * 64,
                },
            )
            self.assertTrue(row.critical_success, card["case_id"])

    def test_every_baseline_file_passes_secret_scan(self):
        for path in sorted(BASELINE.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                persisted = load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
                self.assertEqual(
                    scan_persisted_value_for_secrets(persisted),
                    [],
                    str(path),
                )

    def test_contract_versions_are_new(self):
        self.assertEqual(
            load(BASELINE / "contracts/run_trace.schema.v5.json")["properties"]["contract_version"]["const"],
            "5.0.0",
        )
        self.assertEqual(
            load(BASELINE / "contracts/case_card.schema.v3.json")["$id"],
            "baseline/v3/contracts/case_card.schema.v3.json",
        )
        self.assertEqual(
            load(BASELINE / "contracts/data_snapshot.schema.v3.json")["$id"],
            "baseline/v3/contracts/data_snapshot.schema.v3.json",
        )


if __name__ == "__main__":
    unittest.main()
