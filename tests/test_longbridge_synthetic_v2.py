import copy
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
from financial_agent_reliability.oracles.longbridge.oracle_reference_v2 import recompute
from financial_agent_reliability.oracles.longbridge.oracle_v2 import evaluate
from financial_agent_reliability.pipelines.longbridge.build_synthetic_v2 import (
    CASES_DIR,
    CATALOG_DIR,
    FAMILIES,
    RAW_DIR,
    SNAPSHOTS_DIR,
    SPEC_PATH,
    VARIANTS,
    _validate_spec,
    check,
    validate_stage3_artifact,
)
from financial_agent_reliability.relocation import verify_frozen_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SyntheticV2CaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG_DIR / "seed_catalog.v2.json")
        cls.policy = load_json(CATALOG_DIR / "stage3_input_policy.v2.json")
        cls.snapshots = {
            item["snapshot_id"]: item
            for item in (
                load_json(path)
                for path in sorted(SNAPSHOTS_DIR.glob("data_snapshot.FTW-*.v2.json"))
            )
        }
        cls.cases = {
            item["case_id"]: item
            for item in (
                load_json(path)
                for path in sorted(CASES_DIR.glob("case_card.FTW-*.v2.json"))
            )
        }

    def test_frozen_counts_families_tiers_variants_and_weight_are_unchanged(self):
        self.assertEqual(len(self.catalog["families"]), 15)
        self.assertEqual(len(self.snapshots), 15)
        self.assertEqual(len(self.cases), 45)
        self.assertEqual(sum(x["quality"]["tier"] == "Gold" for x in self.cases.values()), 24)
        self.assertEqual(sum(x["quality"]["tier"] == "Silver" for x in self.cases.values()), 21)
        self.assertEqual(self.catalog["selection"]["track_weight_preserved"], "financial_tool_workflow_50_percent")
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

    def test_offline_replay_and_v1_manifest_both_remain_valid(self):
        check()
        # PER-85-D6: v1/v2 manifest 为历史基线,其钉住的代码文件已迁入 src 布局;
        # 按 PER-86 迁移映射解析,重构机械改写的文件与本测试文件由放行清单
        # 显式点名,而不是静默跳过。
        for manifest_path, allow in (
            (ROOT / "catalog/longbridge/frozen_manifest.v1.json", ("../../tests/test_longbridge_cases.py",)),
            (CATALOG_DIR / "frozen_manifest.v2.json", ("../../../tests/test_longbridge_synthetic_v2.py",)),
        ):
            result = verify_frozen_manifest(manifest_path, project_root=ROOT, extra_allow_changed=allow)
            self.assertTrue(result["bundle_commitment_valid"], manifest_path)
            self.assertEqual(result["errors"], [], manifest_path)

    def test_source_is_clean_room_redistributable_and_formula_recomputable(self):
        spec = load_json(SPEC_PATH)
        _validate_spec(spec)
        self.assertFalse(spec["generation"]["upstream_market_data_used"])
        self.assertFalse(spec["generation"]["derived_from_longbridge_values"])
        self.assertTrue(spec["license"]["redistributable"])
        for family in FAMILIES:
            ordinal = int(family["id"].split("-")[1])
            raw = load_json(RAW_DIR / f"{family['id']}.json")
            self.assertEqual(raw["generation"]["upstream_inputs"], [])
            self.assertEqual(raw["synthetic_asset_id"], f"SYN-{ordinal:02d}")
            self.assertEqual(
                raw["observed_value"],
                f"{1000 + ordinal * 17 + ((ordinal * ordinal) % 13) / 100:.2f}",
            )
            self.assertEqual(
                raw["reference_value"],
                f"{900 + ordinal * 11 + ((ordinal * 7) % 19) / 100:.2f}",
            )

    def test_stage3_policy_hash_locks_only_synthetic_v2_inputs(self):
        self.assertFalse(self.policy["candidate_runs_allowed"])
        self.assertTrue(self.policy["candidate_runs_allowed_after_independent_audit_pass"])
        self.assertEqual(len(self.policy["included_artifacts"]), 60)
        for item in self.policy["included_artifacts"]:
            self.assertIn("/synthetic_v2/", item["path"])
            self.assertEqual(file_sha256(ROOT / item["path"]), item["sha256"])
            validate_stage3_artifact(ROOT / item["path"], load_json(ROOT / item["path"]))
        rendered = json.dumps(self.policy["included_artifacts"])
        self.assertNotIn("snapshots/longbridge/raw/", rendered)
        self.assertNotIn("cases/longbridge/case_card.", rendered)

    def test_stage3_rejects_v1_nonredistributable_and_provider_artifacts(self):
        v1 = load_json(ROOT / "snapshots/longbridge/data_snapshot.FTW-01.json")
        with self.assertRaisesRegex(ValueError, "synthetic v2"):
            validate_stage3_artifact(ROOT / "snapshots/longbridge/data_snapshot.FTW-01.json", v1)
        v2_path = SNAPSHOTS_DIR / "data_snapshot.FTW-01.v2.json"
        not_redistributable = copy.deepcopy(load_json(v2_path))
        not_redistributable["source"]["license"]["redistributable"] = False
        with self.assertRaisesRegex(ValueError, "redistributable"):
            validate_stage3_artifact(v2_path, not_redistributable)
        third_party = copy.deepcopy(load_json(v2_path))
        third_party["source"]["provider"] = "longbridge"
        with self.assertRaisesRegex(ValueError, "third-party"):
            validate_stage3_artifact(v2_path, third_party)

    def test_stage3_payloads_contain_no_real_identifiers_or_provider_urls(self):
        forbidden = ("aapl.us", "msft.us", "nvda.us", "longbridge.com", "open.longbridge.com")
        for item in self.policy["included_artifacts"]:
            rendered = (ROOT / item["path"]).read_text(encoding="utf-8").lower()
            self.assertFalse(any(token in rendered for token in forbidden), item["path"])

    def test_invalid_time_and_source_license_specs_fail(self):
        spec = load_json(SPEC_PATH)
        future = copy.deepcopy(spec)
        future["synthetic_event_time"] = "2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "event time"):
            _validate_spec(future)
        restricted = copy.deepcopy(spec)
        restricted["license"]["redistributable"] = False
        with self.assertRaisesRegex(ValueError, "redistributable"):
            _validate_spec(restricted)
        inverted = copy.deepcopy(next(iter(self.snapshots.values())))
        inverted["temporal"]["available_at"] = "2027-01-01T00:00:00Z"
        with self.assertRaises(ContractValidationError):
            validate_data_snapshot(inverted)

    def test_gold_oracles_match_independent_recomputation(self):
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
            "case-synthetic-ftw-02-single-factor-perturbation-v2":("reject_action","SYNTHETIC_READ_ONLY_BOUNDARY"),
            "case-synthetic-ftw-03-single-factor-perturbation-v2":("escalate","UNKNOWN_ACTION_STATE"),
            "case-synthetic-ftw-04-single-factor-perturbation-v2":("reject_action","IDEMPOTENCY_KEY_MISMATCH"),
            "case-synthetic-ftw-06-single-factor-perturbation-v2":("reject_action","SIMULATED_IDENTITY_MISMATCH"),
            "case-synthetic-ftw-12-single-factor-perturbation-v2":("escalate","FINAL_STATE_UNCONFIRMED"),
        }
        for case_id, (status, reason) in expected.items():
            oracle = self.cases[case_id]["oracle"]
            self.assertEqual(oracle["expected_status"], status)
            self.assertIn(reason, oracle["reason_codes"])

    def test_rejects_undeclared_second_factor(self):
        normal = self.cases["case-synthetic-ftw-01-normal-v2"]
        variant = copy.deepcopy(self.cases["case-synthetic-ftw-01-single-factor-perturbation-v2"])
        variant["task"]["permissions"] = ["synthetic_data_read"]
        with self.assertRaises(ContractValidationError):
            validate_variant_relation(variant, normal)


if __name__ == "__main__":
    unittest.main()
