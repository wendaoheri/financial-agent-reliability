import copy
import importlib.util
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
from cases.public.oracle import evaluate
from cases.public.oracle_reference import recompute


ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "public"
CASES = ROOT / "cases" / "public"
SNAPSHOTS = ROOT / "snapshots" / "public"
RAW = SNAPSHOTS / "raw"


class PublicCaseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG / "seed_catalog.v1.json")
        cls.crosswalk = load_json(CATALOG / "preregistration_variant_protocol.v2.json")
        cls.snapshots = {
            snapshot["snapshot_id"]: snapshot
            for snapshot in (
                load_json(path) for path in sorted(SNAPSHOTS.glob("data_snapshot.FKW-*.json"))
            )
        }
        cls.cases = {
            case["case_id"]: case
            for case in (load_json(path) for path in sorted(CASES.glob("case_card.FKW-*.json")))
        }

    def test_frozen_public_allocation_and_source_quota(self):
        self.assertEqual(len(self.catalog["families"]), 15)
        self.assertEqual(len(self.snapshots), 15)
        self.assertEqual(len(self.cases), 45)
        sources = [family["source_id"] for family in self.catalog["families"]]
        self.assertEqual(
            {source: sources.count(source) for source in sorted(set(sources))},
            {"bizbench": 4, "financebench": 3, "finqa": 4, "tatqa": 4},
        )
        self.assertEqual(
            sum(family["quality"]["frozen_target"] == "Gold_candidate" for family in self.catalog["families"]),
            12,
        )
        self.assertEqual(
            sum(family["quality"]["frozen_target"] == "Silver_diagnostic_only" for family in self.catalog["families"]),
            3,
        )

    def test_every_family_has_exactly_three_variants(self):
        expected = {"normal", "single_factor_perturbation", "missing_or_anomalous"}
        grouped = {}
        for case in self.cases.values():
            grouped.setdefault(case["variant"]["family_id"], set()).add(case["variant"]["kind"])
        self.assertEqual(set(grouped), {f"FKW-{number:02d}" for number in range(1, 16)})
        self.assertTrue(all(kinds == expected for kinds in grouped.values()))

    def test_contract_time_hash_and_single_factor_validation(self):
        for snapshot in self.snapshots.values():
            validate_data_snapshot(snapshot)
        for case in self.cases.values():
            parent_id = case["variant"]["parent_case_id"]
            validate_case_card(
                case,
                snapshots=self.snapshots,
                parent_case=self.cases.get(parent_id),
            )

    def test_missing_variant_changes_only_evidence_and_control_metadata(self):
        permitted_roots = (
            "/case_id",
            "/quality",
            "/evidence_policy",
            "/evidence_refs",
            "/variant",
            "/oracle",
            "/lineage",
            "/integrity",
        )
        validator_module = importlib.import_module("contracts.validate_case_data")
        for family_id in {case["variant"]["family_id"] for case in self.cases.values()}:
            family_cases = [case for case in self.cases.values() if case["variant"]["family_id"] == family_id]
            normal = next(case for case in family_cases if case["variant"]["kind"] == "normal")
            missing = next(case for case in family_cases if case["variant"]["kind"] == "missing_or_anomalous")
            diffs = validator_module._leaf_diffs(normal, missing)
            outside = [path for path in diffs if not any(path == root or path.startswith(root + "/") for root in permitted_roots)]
            self.assertEqual(outside, [], family_id)
            self.assertEqual(missing["quality"]["tier"], "Silver")
            self.assertFalse(missing["quality"]["ranking_eligible"])
            self.assertEqual(missing["oracle"]["expected_status"], "abstain")

    def test_raw_lineage_hash_and_conservative_availability(self):
        for family in self.catalog["families"]:
            snapshot = self.snapshots[family["primary_evidence"]["snapshot_id"]]
            raw_path = RAW / f"{family['family_id']}.json"
            self.assertEqual(file_sha256(raw_path), snapshot["lineage"]["raw_response_sha256"])
            self.assertEqual(snapshot["temporal"]["available_at"], snapshot["temporal"]["retrieved_at"])
            self.assertEqual(family["primary_evidence"]["license"], "CC-BY-4.0")
            self.assertFalse(family["prohibitions"]["benchmark_answer_used_as_oracle"])
            self.assertFalse(family["prohibitions"]["candidate_output_used_as_oracle"])
            self.assertFalse(family["prohibitions"]["original_benchmark_row_redistributed"])

    def test_four_level_deduplication_keys_are_unique(self):
        fields = ("upstream_record_key", "primary_evidence_key", "cross_source_task_key", "family_key")
        for field in fields:
            values = [family["deduplication"][field] for family in self.catalog["families"]]
            self.assertEqual(len(values), len(set(values)), field)

    def test_gold_oracles_match_independent_implementation(self):
        for case in self.cases.values():
            refs = case["evidence_refs"]
            snapshot = self.snapshots[refs[0]["snapshot_id"]] if refs else None
            production = evaluate(snapshot, case["task"]["inputs"])
            self.assertEqual(production["status"], case["oracle"]["expected_status"], case["case_id"])
            self.assertEqual(production["value"], case["oracle"]["expected_value"], case["case_id"])
            self.assertEqual(production["reason_codes"], case["oracle"]["reason_codes"], case["case_id"])
            if case["quality"]["tier"] == "Gold":
                self.assertEqual(production, recompute(snapshot, case["task"]["inputs"]), case["case_id"])

    def test_oracle_hashes_and_manifest_are_frozen(self):
        oracle_hash = file_sha256(CASES / "oracle.py")
        reference_hash = file_sha256(CASES / "oracle_reference.py")
        for case in self.cases.values():
            self.assertEqual(case["oracle"]["implementation_sha256"], oracle_hash)
        for family in self.catalog["families"]:
            self.assertEqual(family["oracle"]["production_sha256"], oracle_hash)
            self.assertEqual(family["oracle"]["independent_sha256"], reference_hash)
        verify_manifest(CATALOG / "frozen_manifest.v1.json")

    def test_crosswalk_retires_control_and_never_maps_missing_to_it(self):
        canonical = self.crosswalk["canonical_execution_variants"]
        self.assertEqual(
            {(item["execution_id"], item["case_card_kind"]) for item in canonical},
            {
                ("baseline", "normal"),
                ("single_factor_stress", "single_factor_perturbation"),
                ("missing_or_anomalous_diagnostic", "missing_or_anomalous"),
            },
        )
        legacy_control = next(item for item in self.crosswalk["legacy_v1_crosswalk"] if item["legacy_id"] == "single_factor_control")
        self.assertIsNone(legacy_control["case_card_kind"])
        self.assertEqual(legacy_control["mapping_status"], "retired_unmapped")
        self.assertTrue(self.crosswalk["non_equivalence_assertions"][0]["silent_mapping_prohibited"])
        self.assertTrue(self.crosswalk["harness_contract"]["reject_legacy_single_factor_control"])

    def test_public_release_stays_blocked_until_two_person_review(self):
        self.assertFalse(self.catalog["release"]["candidate_runs_allowed"])
        self.assertIn("Two-person", self.catalog["release"]["blocking_gate"])

    def test_rejects_an_undeclared_second_factor(self):
        normal = next(case for case in self.cases.values() if case["case_id"] == "case-public-fkw-03-normal-v1")
        variant = copy.deepcopy(next(case for case in self.cases.values() if case["case_id"] == "case-public-fkw-03-single-factor-perturbation-v1"))
        variant["task"]["inputs"]["target_year"] = "2022"
        with self.assertRaises(ContractValidationError):
            validate_variant_relation(variant, normal)


if __name__ == "__main__":
    unittest.main()
