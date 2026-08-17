"""Baseline-v5 freeze, input-binding, and append-only tests."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from copy import deepcopy

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline" / "v5"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(BASELINE))

import validate_baseline_v5 as validator  # noqa: E402
from financial_agent_reliability.graders import baseline_v5 as grader_v5  # noqa: E402
from financial_agent_reliability.harness.bundle import ImmutableBundle  # noqa: E402
from financial_agent_reliability.harness.hashing import build_run_id  # noqa: E402
from financial_agent_reliability.harness.runner_v7 import OfflineHarnessV7  # noqa: E402
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets  # noqa: E402
from financial_agent_reliability.oracles.public_filings import oracle, oracle_reference  # noqa: E402
from financial_agent_reliability.oracles.synthetic import oracle_reference_v3, oracle_v3  # noqa: E402
from financial_agent_reliability.providers.bailian import BailianAdapter, BailianSettings  # noqa: E402


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


class BaselineV5Tests(unittest.TestCase):
    def test_prior_generations_and_stage4_evidence_have_zero_drift(self):
        self.assertEqual(tree_hash("baseline/v2"), "d00c580c608e9e6341e0ea6959a15a1d9db48cdecc891338f8d33baee387583d")
        self.assertEqual(tree_hash("baseline/v3"), "1dfe73ce4c5d0c547b9b27c21e4463a64d8decbbf3661d765c75cc64c12ede20")
        self.assertEqual(tree_hash("baseline/v4"), "8cd2040b66ba8f8a7848f29004086e11166d75d368abfe8a74765ce2b2323b8d")
        self.assertEqual(tree_hash("validation/stage4"), "990c6339fd588c2eed6631c52204b5c03868b9d7b4406c1deb0520597e15a27c")
        self.assertEqual(sha256(ROOT / "docs/contracts/acceptance-criteria-v2.md"), "5dd9529df4f11411b6b6717335ca65b323212eacc90f5c8382143898a73997f2")
        self.assertEqual(sha256(ROOT / "docs/contracts/acceptance-criteria-v3.md"), "c3fcde8227e8934c76161a50756c4569f2ccf19f00d541a74699a9a5b8452eda")
        self.assertEqual(sha256(ROOT / "docs/contracts/acceptance-criteria-v4.md"), "baee53916aa82ffe229d2f76738c56ee8268a9d98ce60f92dfc5216cb82922e5")

    def test_manifest_bundle_and_criteria_anchor(self):
        self.assertEqual(validator.verify_manifest(BASELINE), [])
        manifest = load(BASELINE / "baseline_manifest.frozen.v5.json")
        self.assertEqual(manifest["bundle_sha256"], bundle_hash(manifest["artifacts"]))
        self.assertEqual(manifest["acceptance_criteria"]["sha256"], sha256(ROOT / manifest["acceptance_criteria"]["path"]))
        historical = manifest["historical_failed_generations"]
        self.assertEqual([item["generation"] for item in historical], ["v2", "v3", "v4"])
        for item in historical:
            self.assertEqual(item["manifest_sha256"], sha256(ROOT / item["manifest_path"]))
            self.assertTrue(item["failure_reason"])

    def test_bundle_and_schemas(self):
        self.assertEqual(validator.validate_bundle(BASELINE), [])
        self.assertEqual((len(cases()), len(snapshots())), (12, 8))
        case_schema = load(BASELINE / "contracts/case_card.schema.v5.json")
        snapshot_schema = load(BASELINE / "contracts/data_snapshot.schema.v5.json")
        resolved = deepcopy(snapshot_schema)
        resolved["properties"]["financial_subject"] = case_schema["$defs"]["financial_subject"]
        resolved["properties"]["integrity"] = case_schema["$defs"]["integrity"]
        for card in cases():
            jsonschema.Draft202012Validator(case_schema).validate(card)
        for snapshot in snapshots().values():
            jsonschema.Draft202012Validator(resolved).validate(snapshot)
        registry_schema = load(BASELINE / "contracts/frozen_input_registry.schema.v5.json")
        registry = load(BASELINE / "contracts/frozen_input_registry.frozen.v5.json")
        jsonschema.Draft202012Validator(registry_schema).validate(registry)

    def test_license_gate_and_dual_oracles(self):
        capture = load(BASELINE / "build/capture_manifest.v5.json")
        self.assertTrue(capture["license_gate"]["all_artifacts_redistributable"])
        self.assertFalse(capture["license_gate"]["licensed_market_data_included"])
        frozen = snapshots()
        for card in cases():
            self.assertTrue(card["source"]["license"]["redistributable"])
            snap = frozen[card["evidence_refs"][0]["snapshot_id"]]
            if card["variant"]["family_id"].startswith("FKW5"):
                left, right = oracle.evaluate(snap, card["task"]["inputs"]), oracle_reference.recompute(snap, card["task"]["inputs"])
            else:
                left, right = oracle_v3.evaluate(snap, card["task"]["inputs"]), oracle_reference_v3.recompute(snap, card["task"]["inputs"])
            self.assertEqual(left, right, card["case_id"])
            self.assertEqual(left["status"], card["oracle"]["expected_status"])
            self.assertEqual(left["value"], card["oracle"]["expected_value"])

    def test_grader_contract_policy_and_v7_schema_are_pinned(self):
        contract = load(BASELINE / "contracts/grader_contract.frozen.v5.json")
        for item in contract["files"]:
            self.assertEqual(sha256(ROOT / item["path"]), item["sha256"], item["path"])
        self.assertEqual(contract["contract_bundle_sha256"], bundle_hash(contract["files"]))
        policy = load(BASELINE / "grader/grader_policy.v5.json")
        self.assertEqual(policy["critical_success"]["allowed_invariants"], list(grader_v5.SUPPORTED_INVARIANTS))
        self.assertEqual(sha256(BASELINE / "contracts/run_trace.schema.v7.json"), sha256(ROOT / "src/financial_agent_reliability/harness/contracts/run_trace.schema.v7.json"))

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
            row = grader_v5.grade_run(case=card, oracle_result={"status": card["oracle"]["expected_status"], "value": card["oracle"]["expected_value"], "reason_codes": card["oracle"]["reason_codes"]}, submission=submission, commitments={"candidate_sha256": "1"*64, "trace_sha256": "2"*64, "projection_sha256": "3"*64, "snapshot_sha256": "4"*64})
            self.assertTrue(row.critical_success, card["case_id"])

    def test_registry_binds_case_variant_path_sha_and_rejects_all_mismatches(self):
        registry_doc = load(BASELINE / "contracts/frozen_input_registry.frozen.v5.json")
        registry = {
            (item["case_id"], item["variant_id"]): item["path"]
            for item in registry_doc["entries"]
        }
        cards = cases()
        card_a, card_b = cards[0], cards[1]
        path_a = registry[(card_a["case_id"], card_a["variant"]["kind"])]
        path_b = registry[(card_b["case_id"], card_b["variant"]["kind"])]
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            bundle = ImmutableBundle.create(BASELINE, temp / "bundle")
            adapter = BailianAdapter(
                BailianSettings.from_env({"BENCH_BAILIAN_API_KEY": "fixture-never-persist"}),
                "qwen3.8-max",
            )
            harness = OfflineHarnessV7(adapter, bundle, temp / "checkpoints")

            def successful(request):
                return {"model": request["model"], "accepted_parameters": list(request["parameters"]), "tool_call_supported": True, "output": "synthetic", "action": "answer"}

            trace = harness.run(
                case_id=card_a["case_id"],
                variant_id=card_a["variant"]["kind"],
                repeat=1,
                seed=20260818,
                frozen_input_path=path_a,
                preflight_transport=successful,
                inference_transport=successful,
            )
            trace_path = temp / "trace.json"
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            self.assertEqual(validator.verify_trace(trace_path, registered_inputs=registry), [])
            self.assertEqual(validator.verify_trace(trace_path), [])

            artifact_sha = {item["path"]: item["sha256"] for item in trace["immutable_bundle"]["artifacts"]}
            mismatches = []
            cross_case = deepcopy(trace)
            cross_case["context"]["frozen_input_path"] = path_b
            cross_case["context"]["frozen_input_sha256"] = artifact_sha[path_b]
            mismatches.append(cross_case)
            wrong_sha = deepcopy(trace)
            wrong_sha["context"]["frozen_input_sha256"] = artifact_sha[path_b]
            mismatches.append(wrong_sha)
            unregistered = deepcopy(trace)
            unregistered["run_identity"]["case_id"] = "case-not-registered"
            unregistered["run_id"] = build_run_id(unregistered["run_identity"])
            mismatches.append(unregistered)
            for index, tampered in enumerate(mismatches):
                candidate = temp / f"mismatch-{index}.json"
                candidate.write_text(json.dumps(tampered), encoding="utf-8")
                errors = validator.verify_trace(candidate, registered_inputs=registry)
                self.assertTrue(any("registered frozen input" in error for error in errors), errors)

            tampered_registry = deepcopy(registry_doc)
            first = next(item for item in tampered_registry["entries"] if item["case_id"] == card_a["case_id"] and item["variant_id"] == card_a["variant"]["kind"])
            first["path"] = path_b
            first["sha256"] = artifact_sha[path_b]
            registry_root = temp / "tampered-baseline"
            (registry_root / "contracts").mkdir(parents=True)
            (registry_root / "cases").mkdir()
            for source in (BASELINE / "cases").glob("*.json"):
                (registry_root / "cases" / source.name).write_bytes(source.read_bytes())
            registry_path = registry_root / "contracts/tampered-registry.json"
            registry_path.write_text(json.dumps(tampered_registry), encoding="utf-8")
            registry_errors = validator.verify_trace(trace_path, registry_path=registry_path)
            self.assertTrue(any("different case" in error or "different variant" in error for error in registry_errors), registry_errors)

    def test_all_v5_files_pass_secret_scan(self):
        for path in sorted(BASELINE.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                value = load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
                self.assertEqual(scan_persisted_value_for_secrets(value), [], str(path))


if __name__ == "__main__":
    unittest.main()
