import copy
import json
import pathlib
import unittest

from contracts.grader import (
    GraderValidationError,
    file_sha256,
    load_json,
    score_results,
    validate_frozen_contract,
    validate_results,
    verify_freeze,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "grader"
PREREG = ROOT / "preregistration" / "benchmark_preregistration.v1.json"


def full_bundle(*, silver_reversed=False):
    prereg = load_json(PREREG)
    models = prereg["candidate_models"]
    manifests = [
        {
            "logical_label": model,
            "requested_model_id": f"vendor/{model}-immutable-202608",
            "response_model_id": f"vendor/{model}-immutable-202608",
            "provider": f"provider-{index}",
            "identity_verified": True,
        }
        for index, model in enumerate(models)
    ]
    rows = []
    for family in prereg["case_families"]:
        for variant in prereg["variant_ids"]:
            for model_index, model in enumerate(models):
                for repeat in range(1, prereg["repeats_per_cell"] + 1):
                    if family["tier"] == "Gold":
                        success = repeat > model_index
                    else:
                        success = (model_index == 2) if silver_reversed else True
                    expected_action = "abstain" if family["id"] == "FTW-11" else "answer"
                    actual_action = expected_action if success else "answer"
                    rows.append(
                        {
                            "family_id": family["id"],
                            "variant_id": variant,
                            "model_label": model,
                            "repeat": repeat,
                            "critical_invariants": {
                                "point_in_time_and_no_future_information": success,
                                "evidence_supports_material_claims": success,
                            },
                            "end_to_end_complete": success,
                            "evidence_correct": 2 if success else 1,
                            "evidence_required": 2,
                            "expected_action": expected_action,
                            "actual_action": actual_action,
                            "max_loss_level": "L0" if success else "L2",
                            "total_cost_usd": f"0.{10 + model_index}",
                            "latency_ms": 900 + model_index * 100,
                            "excluded": False,
                        }
                    )
    return {
        "contract_version": "1.0.0",
        "preregistration_sha256": file_sha256(PREREG),
        "model_manifests": manifests,
        "runs": rows,
    }


class FrozenGraderContractTests(unittest.TestCase):
    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(GraderValidationError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_frozen_contract_has_exact_matrix_and_track_split(self):
        self.assertEqual(
            validate_frozen_contract(),
            {"families": 30, "models": 3, "variants": 3},
        )

    def test_frozen_manifest_detects_any_file_mutation(self):
        result = verify_freeze()
        self.assertGreaterEqual(result["files"], 9)
        self.assertRegex(result["contract_bundle_sha256"], r"^[0-9a-f]{64}$")

    def test_positive_partial_fixture_is_accepted_only_as_partial(self):
        fixture = load_json(FIXTURES / "results.partial.valid.json")
        self.assertEqual(len(validate_results(fixture, require_complete=False)), 1)
        self.assert_contract_error(
            lambda: validate_results(fixture, require_complete=True),
            "incomplete matrix",
        )

    def test_negative_fixture_catches_identity_duplicate_gate_and_numeric_failures(self):
        fixture = load_json(FIXTURES / "results.partial.invalid.json")
        for fragment in (
            "model identity mismatch",
            "duplicate matrix cell",
            "at least one critical invariant",
            "unknown critical invariants",
            "evidence_correct exceeds",
            "canonical non-negative",
            "invalid latency_ms",
        ):
            self.assert_contract_error(
                lambda: validate_results(fixture, require_complete=False),
                fragment,
            )

    def test_complete_matrix_is_exactly_810_unique_cells(self):
        bundle = full_bundle()
        rows = validate_results(bundle)
        self.assertEqual(len(rows), 30 * 3 * 3 * 3)

    def test_missing_row_cannot_be_disguised_as_post_hoc_exclusion(self):
        bundle = full_bundle()
        bundle["runs"].pop()
        self.assert_contract_error(
            lambda: validate_results(bundle),
            "incomplete matrix: 1 cells missing",
        )

    def test_exclusion_must_cover_whole_family_and_all_models(self):
        bundle = full_bundle()
        bundle["runs"][0]["excluded"] = True
        bundle["runs"][0]["exclusion"] = {
            "code": "oracle_proven_incorrect",
            "decided_before_identity_unblinding": True,
            "independent_reviewer": "blind-auditor-01",
            "evidence_sha256": "a" * 64,
        }
        self.assert_contract_error(
            lambda: validate_results(bundle),
            "exclusion must apply to the whole family and every candidate",
        )

    def test_gold_only_fixed_weight_scoring_and_pass3(self):
        ordinary = score_results(full_bundle(silver_reversed=False))
        reversed_silver = score_results(full_bundle(silver_reversed=True))
        self.assertEqual(ordinary["models"], reversed_silver["models"])
        self.assertEqual(ordinary["provisional_leader"], "qwen3.8-max")
        self.assertTrue(ordinary["ranking_reliable"])
        self.assertEqual(
            ordinary["models"]["qwen3.8-max"]["CSR"]["estimate"],
            1.0,
        )
        self.assertEqual(
            ordinary["models"]["glm-5.2"]["pass^3"]["estimate"],
            0.0,
        )

    def test_candidate_specific_model_fallback_invalidates_results(self):
        bundle = full_bundle()
        bundle["model_manifests"][1]["response_model_id"] = "fallback/other"
        self.assert_contract_error(
            lambda: score_results(bundle),
            "model identity mismatch or fallback",
        )

    def test_reweighting_attempt_is_an_auditable_validation_failure(self):
        bundle = full_bundle()
        bundle["track_weights"] = {
            "financial_knowledge_work": "1.0",
            "financial_tool_workflow": "0.0",
        }
        self.assert_contract_error(
            lambda: score_results(bundle),
            "unregistered top-level fields: ['track_weights']",
        )


if __name__ == "__main__":
    unittest.main()
