"""Baseline-v4 freeze, audit-hard-gate, and append-only tests."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest
from copy import deepcopy

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline" / "v4"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(BASELINE))

import validate_baseline_v4 as validator  # noqa: E402
from financial_agent_reliability.graders import baseline_v4 as grader_v4  # noqa: E402
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets  # noqa: E402
from financial_agent_reliability.oracles.public_filings import oracle, oracle_reference  # noqa: E402
from financial_agent_reliability.oracles.synthetic import oracle_reference_v3, oracle_v3  # noqa: E402


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(relative: str) -> str:
    lines = []
    for path in sorted((ROOT / relative).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            lines.append(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def bundle_hash(entries: list[dict]) -> str:
    lines = "".join(f"{item['sha256']}  {item['path']}\n" for item in entries)
    return hashlib.sha256(lines.encode()).hexdigest()


def cases() -> list[dict]:
    return [load(path) for path in sorted((BASELINE / "cases").glob("case-*.json"))]


def snapshots() -> dict[str, dict]:
    return {item["snapshot_id"]: item for item in (
        load(path) for path in sorted((BASELINE / "snapshots").glob("data_snapshot.*.json"))
    )}


class BaselineV4Tests(unittest.TestCase):
    def test_prior_generations_and_stage4_evidence_have_zero_drift(self):
        self.assertEqual(tree_hash("baseline/v2"), "d00c580c608e9e6341e0ea6959a15a1d9db48cdecc891338f8d33baee387583d")
        self.assertEqual(tree_hash("baseline/v3"), "1dfe73ce4c5d0c547b9b27c21e4463a64d8decbbf3661d765c75cc64c12ede20")
        self.assertEqual(tree_hash("validation/stage4/per329-baseline-v3-validation-v2"), "6b01f0706480dacb554674797ad0d4ccc77a94eaf04da384eaf5fcc22bbf9fd2")
        self.assertEqual(sha256(ROOT / "docs/contracts/acceptance-criteria-v2.md"), "5dd9529df4f11411b6b6717335ca65b323212eacc90f5c8382143898a73997f2")
        self.assertEqual(sha256(ROOT / "docs/contracts/acceptance-criteria-v3.md"), "c3fcde8227e8934c76161a50756c4569f2ccf19f00d541a74699a9a5b8452eda")

    def test_manifest_bundle_and_criteria_anchor(self):
        self.assertEqual(validator.verify_manifest(BASELINE), [])
        manifest = load(BASELINE / "baseline_manifest.frozen.v4.json")
        self.assertEqual(manifest["bundle_sha256"], bundle_hash(manifest["artifacts"]))
        self.assertEqual(manifest["acceptance_criteria"]["sha256"], sha256(ROOT / manifest["acceptance_criteria"]["path"]))

    def test_bundle_and_schemas(self):
        self.assertEqual(validator.validate_bundle(BASELINE), [])
        self.assertEqual((len(cases()), len(snapshots())), (12, 8))
        case_schema = load(BASELINE / "contracts/case_card.schema.v4.json")
        snapshot_schema = load(BASELINE / "contracts/data_snapshot.schema.v4.json")
        resolved = deepcopy(snapshot_schema)
        resolved["properties"]["financial_subject"] = case_schema["$defs"]["financial_subject"]
        resolved["properties"]["integrity"] = case_schema["$defs"]["integrity"]
        for card in cases():
            jsonschema.Draft202012Validator(case_schema).validate(card)
        for snapshot in snapshots().values():
            jsonschema.Draft202012Validator(resolved).validate(snapshot)

    def test_license_gate_and_dual_oracles(self):
        capture = load(BASELINE / "build/capture_manifest.v4.json")
        self.assertTrue(capture["license_gate"]["all_artifacts_redistributable"])
        self.assertFalse(capture["license_gate"]["licensed_market_data_included"])
        frozen = snapshots()
        for card in cases():
            self.assertTrue(card["source"]["license"]["redistributable"])
            snap = frozen[card["evidence_refs"][0]["snapshot_id"]]
            if card["variant"]["family_id"].startswith("FKW4"):
                left, right = oracle.evaluate(snap, card["task"]["inputs"]), oracle_reference.recompute(snap, card["task"]["inputs"])
            else:
                left, right = oracle_v3.evaluate(snap, card["task"]["inputs"]), oracle_reference_v3.recompute(snap, card["task"]["inputs"])
            self.assertEqual(left, right, card["case_id"])
            self.assertEqual(left["status"], card["oracle"]["expected_status"])
            self.assertEqual(left["value"], card["oracle"]["expected_value"])

    def test_grader_contract_policy_and_v6_schema_are_pinned(self):
        contract = load(BASELINE / "contracts/grader_contract.frozen.v4.json")
        for item in contract["files"]:
            self.assertEqual(sha256(ROOT / item["path"]), item["sha256"], item["path"])
        self.assertEqual(contract["contract_bundle_sha256"], bundle_hash(contract["files"]))
        policy = load(BASELINE / "grader/grader_policy.v4.json")
        self.assertEqual(policy["critical_success"]["allowed_invariants"], list(grader_v4.SUPPORTED_INVARIANTS))
        self.assertEqual(sha256(BASELINE / "contracts/run_trace.schema.v6.json"), sha256(ROOT / "src/financial_agent_reliability/harness/contracts/run_trace.schema.v6.json"))

    def test_registered_expectations_pass_and_claim_keys_are_exact(self):
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
                submission["claims"] = {"registered_conclusion": card["oracle"]["expected_value"]}
                submission["evidence_tier_labels"] = {"registered_conclusion": "research_direct_evidence"}
            row = grader_v4.grade_run(case=card, oracle_result={"status": card["oracle"]["expected_status"], "value": card["oracle"]["expected_value"], "reason_codes": card["oracle"]["reason_codes"]}, submission=submission, commitments={"candidate_sha256": "1"*64, "trace_sha256": "2"*64, "projection_sha256": "3"*64, "snapshot_sha256": "4"*64})
            self.assertTrue(row.critical_success, card["case_id"])

    def test_all_v4_files_pass_secret_scan(self):
        for path in sorted(BASELINE.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                value = load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
                self.assertEqual(scan_persisted_value_for_secrets(value), [], str(path))


if __name__ == "__main__":
    unittest.main()
