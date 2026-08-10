import copy
import hashlib
import importlib.util
import json
import pathlib
import unittest

from contracts.validate_case_data import (
    ContractValidationError,
    content_sha256,
    file_sha256,
    load_json,
    validate_bundle,
    validate_case_card,
    validate_data_snapshot,
    validate_variant_relation,
    verify_manifest,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "case_data"
CONTRACTS = ROOT / "contracts"


def load_fixture(name):
    return load_json(FIXTURES / name)


def rehash(document):
    document["integrity"]["content_sha256"] = content_sha256(document)
    return document


class CaseDataContractTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = load_fixture("data_snapshot.normal.json")
        self.normal = load_fixture("case_card.normal.json")
        self.variant = load_fixture("case_card.single_factor.json")
        self.missing = load_fixture("case_card.missing_evidence.json")
        self.snapshots = {self.snapshot["snapshot_id"]: self.snapshot}

    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(ContractValidationError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_frozen_bundle_accepts_normal_single_factor_and_missing_evidence(self):
        self.assertEqual(validate_bundle(FIXTURES), {"snapshots": 1, "cases": 3})

    def test_schema_artifacts_are_valid_json_and_versioned(self):
        for name in ("case_card.schema.v1.json", "data_snapshot.schema.v1.json"):
            schema = load_json(CONTRACTS / name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith(name))

    def test_independent_oracle_recomputes_both_gold_results(self):
        oracle_path = FIXTURES / "oracle_materiality.py"
        spec = importlib.util.spec_from_file_location("oracle_materiality", oracle_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(file_sha256(oracle_path), self.normal["oracle"]["implementation_sha256"])
        for case in (self.normal, self.variant):
            actual = module.evaluate(
                self.snapshot,
                case["task"]["inputs"]["materiality_threshold_pct"],
            )
            self.assertEqual(actual, case["oracle"]["expected_value"])

    def test_snapshot_raw_input_lineage_hash_is_reproducible(self):
        self.assertEqual(
            file_sha256(FIXTURES / "raw_market_input.json"),
            self.snapshot["lineage"]["raw_response_sha256"],
        )

    def test_rejects_time_inversion(self):
        invalid = copy.deepcopy(self.snapshot)
        invalid["temporal"]["event_time"] = "2026-07-31T16:20:00+08:00"
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_data_snapshot(invalid),
            "event_time must not be after available_at",
        )

    def test_rejects_future_information_relative_to_case_cutoff(self):
        future = copy.deepcopy(self.snapshot)
        future["temporal"]["available_at"] = "2026-07-31T17:00:00+08:00"
        rehash(future)
        case = copy.deepcopy(self.normal)
        case["evidence_refs"][0]["snapshot_sha256"] = future["integrity"]["content_sha256"]
        rehash(case)
        self.assert_contract_error(
            lambda: validate_case_card(case, snapshots={future["snapshot_id"]: future}),
            "future information",
        )

    def test_rejects_missing_lineage(self):
        invalid = copy.deepcopy(self.snapshot)
        del invalid["lineage"]
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_data_snapshot(invalid),
            "$/lineage: required field is missing",
        )

    def test_rejects_hash_mismatch(self):
        invalid = copy.deepcopy(self.snapshot)
        invalid["records"][0]["payload"]["close"] = "999.000"
        self.assert_contract_error(
            lambda: validate_data_snapshot(invalid),
            "hash mismatch",
        )

    def test_rejects_case_without_gold_or_silver_mark(self):
        invalid = copy.deepcopy(self.normal)
        invalid["quality"]["tier"] = "Bronze"
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_case_card(invalid, snapshots=self.snapshots),
            "explicitly marked Gold or Silver",
        )

    def test_rejects_single_factor_variant_that_changes_two_factors(self):
        invalid = copy.deepcopy(self.variant)
        invalid["financial_subject"]["currency"]["code"] = "USD"
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_variant_relation(invalid, self.normal),
            "more than one key factor changed",
        )

    def test_rejects_single_factor_variant_with_two_declarations(self):
        invalid = copy.deepcopy(self.variant)
        invalid["variant"]["changed_factors"].append("/financial_subject/currency")
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_variant_relation(invalid, self.normal),
            "must declare exactly one factor",
        )

    def test_rejects_longbridge_non_public_access(self):
        invalid = copy.deepcopy(self.snapshot)
        invalid["source"]["provider"] = "longbridge"
        invalid["access"]["mode"] = "trade"
        rehash(invalid)
        self.assert_contract_error(
            lambda: validate_data_snapshot(invalid),
            "Longbridge sources must use public_read_only",
        )

    def test_silver_case_is_excluded_and_requires_abstention(self):
        self.assertFalse(self.missing["quality"]["ranking_eligible"])
        invalid = copy.deepcopy(self.missing)
        invalid["quality"]["ranking_eligible"] = True
        invalid["oracle"]["expected_status"] = "answer"
        rehash(invalid)
        errors = validate_case_card(invalid, snapshots=self.snapshots, raise_on_error=False)
        self.assertTrue(any("Silver cases must be excluded" in error for error in errors))
        self.assertTrue(any("Silver case must expect abstention" in error for error in errors))

    def test_canonical_hash_ignores_key_and_whitespace_order(self):
        original = json.loads((FIXTURES / "case_card.normal.json").read_text(encoding="utf-8"))
        reordered = json.loads(json.dumps(original, sort_keys=True, indent=4, ensure_ascii=False))
        self.assertEqual(content_sha256(original), content_sha256(reordered))

    def test_manifest_hashes_are_frozen(self):
        verify_manifest(CONTRACTS / "case_data_contracts.frozen.v1.json")


if __name__ == "__main__":
    unittest.main()
