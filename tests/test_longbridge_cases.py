import json
import pathlib
import unittest

from contracts.validate_case_data import (
    ContractValidationError,
    file_sha256,
    load_json,
    validate_case_card,
    validate_data_snapshot,
    validate_variant_relation,
    verify_manifest,
)
from financial_agent_reliability.oracles.longbridge.oracle import evaluate
from financial_agent_reliability.oracles.longbridge.oracle_reference import recompute
from financial_agent_reliability.pipelines.longbridge.freeze import FAMILIES, VARIANTS, check


ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "catalog" / "longbridge"
CASES_DIR = ROOT / "cases" / "longbridge"
SNAPSHOTS_DIR = ROOT / "snapshots" / "longbridge"
RAW_DIR = SNAPSHOTS_DIR / "raw"


class LongbridgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG_DIR / "seed_catalog.v1.json")
        cls.snapshots = {item["snapshot_id"]:item for item in (load_json(path) for path in sorted(SNAPSHOTS_DIR.glob("data_snapshot.FTW-*.json")))}
        cls.cases = {item["case_id"]:item for item in (load_json(path) for path in sorted(CASES_DIR.glob("case_card.FTW-*.json")))}

    def test_frozen_quota_and_exact_three_variants(self):
        self.assertEqual(len(self.catalog["families"]), 15)
        self.assertEqual(len(self.snapshots), 15)
        self.assertEqual(len(self.cases), 45)
        self.assertEqual(sum(x["quality"]["frozen_target"] == "Gold_candidate" for x in self.catalog["families"]), 12)
        grouped = {}
        for case in self.cases.values():
            grouped.setdefault(case["variant"]["family_id"], set()).add(case["variant"]["kind"])
        self.assertEqual(set(grouped), {f"FTW-{number:02d}" for number in range(1, 16)})
        self.assertTrue(all(kinds == set(VARIANTS) for kinds in grouped.values()))

    def test_contract_time_hash_and_single_factor_rules(self):
        for snapshot in self.snapshots.values():
            validate_data_snapshot(snapshot)
        for case in self.cases.values():
            parent = self.cases.get(case["variant"]["parent_case_id"])
            validate_case_card(case, snapshots=self.snapshots, parent_case=parent)

    def test_offline_replay_matches_frozen_files(self):
        check()

    def test_raw_lineage_schema_and_read_only_boundary(self):
        schema_hash = file_sha256(CATALOG_DIR / "quote.schema.v0.26.0.json")
        forbidden_commands = {"order", "assets", "positions", "portfolio", "statement", "cash-flow"}
        for family in FAMILIES:
            raw_path = RAW_DIR / f"{family['id']}.json"
            raw = load_json(raw_path)
            snapshot = next(x for x in self.snapshots.values() if x["records"][0]["payload"]["symbol"] == family["symbol"])
            self.assertEqual(raw["response_schema_sha256"], schema_hash)
            self.assertEqual(file_sha256(raw_path), snapshot["lineage"]["raw_response_sha256"])
            self.assertEqual(raw["command"][0:2], ["longbridge", "quote"])
            self.assertFalse(forbidden_commands.intersection(raw["command"]))
            self.assertEqual(snapshot["access"]["mode"], "public_read_only")
            self.assertFalse(snapshot["source"]["license"]["redistributable"])

    def test_no_credentials_or_real_account_state(self):
        forbidden_keys = {"token", "secret", "password", "access_token", "refresh_token", "account_id"}
        for path in [*RAW_DIR.glob("*.json"), *SNAPSHOTS_DIR.glob("data_snapshot.*.json"), *CASES_DIR.glob("case_card.*.json")]:
            doc = load_json(path)
            stack = [doc]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    self.assertFalse(forbidden_keys.intersection(map(str.lower, value.keys())), path.name)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
            text = json.dumps(doc, ensure_ascii=False).lower()
            self.assertNotIn("bearer ", text)
        for case in self.cases.values():
            ledger = case["task"]["initial_state"]["simulated_ledger"]
            if ledger:
                self.assertFalse(ledger["real_account_data"])
                self.assertFalse(ledger["real_execution"])

    def test_gold_oracles_match_independent_code(self):
        for case in self.cases.values():
            refs = case["evidence_refs"]
            snapshot = self.snapshots[refs[0]["snapshot_id"]] if refs else None
            actual = evaluate(snapshot, case["task"]["inputs"])
            self.assertEqual(actual["status"], case["oracle"]["expected_status"], case["case_id"])
            self.assertEqual(actual["value"], case["oracle"]["expected_value"], case["case_id"])
            self.assertEqual(actual["reason_codes"], case["oracle"]["reason_codes"], case["case_id"])
            if case["quality"]["tier"] == "Gold":
                self.assertEqual(actual, recompute(snapshot, case["task"]["inputs"]), case["case_id"])
            else:
                self.assertEqual(actual["status"], "abstain")

    def test_high_loss_gates_reject_or_escalate(self):
        expected = {
            "case-longbridge-ftw-02-single-factor-perturbation-v1":("reject_action","PUBLIC_READ_ONLY_BOUNDARY"),
            "case-longbridge-ftw-03-single-factor-perturbation-v1":("escalate","UNKNOWN_ACTION_STATE"),
            "case-longbridge-ftw-04-single-factor-perturbation-v1":("reject_action","IDEMPOTENCY_KEY_MISMATCH"),
            "case-longbridge-ftw-06-single-factor-perturbation-v1":("reject_action","SIMULATED_IDENTITY_MISMATCH"),
            "case-longbridge-ftw-12-single-factor-perturbation-v1":("escalate","FINAL_STATE_UNCONFIRMED"),
        }
        for case_id, (status, reason) in expected.items():
            oracle = self.cases[case_id]["oracle"]
            self.assertEqual(oracle["expected_status"], status)
            self.assertIn(reason, oracle["reason_codes"])

    def test_deduplication_keys_are_unique(self):
        for field in ("upstream_record_key","primary_evidence_key","cross_source_task_key","family_key"):
            values = [item["deduplication"][field] for item in self.catalog["families"]]
            self.assertEqual(len(values), len(set(values)), field)

    def test_oracle_hashes_manifest_and_release_gate(self):
        production = file_sha256(ROOT / "oracles" / "longbridge" / "oracle.py")
        independent = file_sha256(ROOT / "oracles" / "longbridge" / "oracle_reference.py")
        for family in self.catalog["families"]:
            self.assertEqual(family["oracle"]["production_sha256"], production)
            self.assertEqual(family["oracle"]["independent_sha256"], independent)
        verify_manifest(CATALOG_DIR / "frozen_manifest.v1.json")
        self.assertFalse(self.catalog["release"]["candidate_runs_allowed"])

    def test_rejects_undeclared_second_factor(self):
        normal = self.cases["case-longbridge-ftw-01-normal-v1"]
        variant = json.loads(json.dumps(self.cases["case-longbridge-ftw-01-single-factor-perturbation-v1"]))
        variant["task"]["permissions"] = ["public_data_read"]
        with self.assertRaises(ContractValidationError):
            validate_variant_relation(variant, normal)


if __name__ == "__main__":
    unittest.main()
