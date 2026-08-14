import hashlib
import json
import pathlib
import unittest

from contracts import grader_v2
from contracts.grader_v2 import (
    GraderValidationError,
    file_sha256,
    load_json,
    score_results,
    validate_frozen_contract,
    validate_results,
    verify_freeze,
)
from contracts.sealed_row_bridge_v2 import build_bundle


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "grader"
PREREG_V1 = ROOT / "preregistration" / "benchmark_preregistration.v1.json"
PREREG_V11 = ROOT / "preregistration" / "benchmark_preregistration.v1.1.json"

# Hashes committed in contracts/grader_contract.frozen.v1.json (PER-24).
V1_COMMITTED = {
    "preregistration/benchmark_preregistration.v1.json":
        "9cc19b6dad9873e78c78a324c304c43050f7e9e5099cb8fb5f026818041aa31e",
    "contracts/grader.py":
        "fc59f71f771402be538c404bbcab4c12640218c95d35d3a37bd1360568a82af6",
    "contracts/grader_policy.v1.json":
        "49aa4367a7761afe9e0275250700856605f346a8d35b7bc8d550c9cf1126d7b7",
}


def sha256_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_bundle(*, silver_reversed: bool = False) -> dict:
    """A deterministic complete v2 bundle where qwen3.8-max dominates Gold."""

    prereg = load_json(PREREG_V11)
    models = prereg["candidate_models"]
    cells = prereg["recorded_pre_execution_changes"]["case_tier_registry"]["cells"]
    rows = []
    for cell in cells:
        for model_index, model in enumerate(models):
            for repeat in range(1, prereg["repeats_per_cell"] + 1):
                if cell["tier"] == "Gold":
                    success = model_index == 0
                else:
                    success = (model_index == 2) if silver_reversed else True
                rows.append(
                    {
                        "family_id": cell["family_id"],
                        "variant_id": cell["variant_id"],
                        "model_label": model,
                        "repeat": repeat,
                        "critical_invariants": {
                            "point_in_time_and_no_future_information": success,
                            "evidence_supports_material_claims": success,
                        },
                        "end_to_end_complete": success,
                        "evidence_correct": 2 if success else 1,
                        "evidence_required": 2,
                        "expected_action": "answer",
                        "actual_action": "answer" if success else "abstain",
                        "max_loss_level": "L0" if success else "L2",
                        "total_cost_usd": f"0.{10 + model_index}",
                        "latency_ms": 900 + model_index * 100,
                        "excluded": False,
                    }
                )
    return {
        "contract_version": "2.0.0",
        "preregistration_sha256": file_sha256(PREREG_V11),
        "model_manifests": [
            {
                "logical_label": model,
                "requested_model_id": f"vendor/{model}-immutable-202608",
                "response_model_id": f"vendor/{model}-immutable-202608",
                "provider": f"provider-{index}",
                "identity_verified": True,
            }
            for index, model in enumerate(models)
        ],
        "runs": rows,
    }


class ZeroDriftTests(unittest.TestCase):
    """v1 frozen artifacts must remain byte-identical (PER-80 prohibition)."""

    def test_v1_frozen_files_match_v1_bundle_commitments(self):
        for rel, expected in V1_COMMITTED.items():
            self.assertEqual(file_sha256(ROOT / rel), expected, rel)

    def test_v1_grader_freeze_still_validates_and_verifies(self):
        from contracts.grader import validate_frozen_contract as v1_validate
        from contracts.grader import verify_freeze as v1_verify
        self.assertEqual(v1_validate(), {"families": 30, "models": 3, "variants": 3})
        result = v1_verify()
        self.assertEqual(
            result["contract_bundle_sha256"],
            "a40ad4444e0954c1e86103f370815a5bca63db3ebd51afc00638a4eab64fe4c9",
        )


class AddendumConsistencyTests(unittest.TestCase):
    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(GraderValidationError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_addendum_supersedes_commitment_matches_frozen_v1(self):
        addendum = load_json(PREREG_V11)
        self.assertEqual(addendum["revision_type"], "addendum")
        self.assertEqual(addendum["status"], "frozen_addendum")
        self.assertEqual(addendum["supersedes"]["sha256"], file_sha256(PREREG_V1))

    def test_addendum_roster_equals_manifest_v2_and_rejects_kimi(self):
        addendum = load_json(PREREG_V11)
        manifest_v2 = load_json(ROOT / "contracts" / "model_manifest.frozen.v2.json")
        labels = [model["logical_label"] for model in manifest_v2["models"]]
        requested = [model["requested_model_id"] for model in manifest_v2["models"]]
        self.assertEqual(addendum["candidate_models"], labels)
        self.assertEqual(addendum["candidate_models"], requested)
        self.assertNotIn("kimi-k3", addendum["candidate_models"])
        self.assertEqual(
            file_sha256(ROOT / "contracts" / "model_manifest.frozen.v1.json"),
            "6df4c5b8615c55b6db06a970e16bd19345ecbada691c6737e59be5f2bba166e2",
        )
        self.assertEqual(
            file_sha256(ROOT / "contracts" / "model_manifest.frozen.v2.json"),
            "8b727749db3e29a081a4f48aae7bdf98149ac2f602bf10bda1220a330d5cd763",
        )

    def test_addendum_decision_chain_citations_resolve(self):
        addendum = load_json(PREREG_V11)
        substitution = addendum["recorded_pre_execution_changes"]["model_substitution_addendum"]
        self.assertEqual(substitution["substituted_out"], "kimi-k3")
        self.assertEqual(substitution["substituted_in"], "deepseek-v4-pro")
        chain = substitution["decision_chain"]
        self.assertGreaterEqual(len(chain), 6)
        owner_comments = {
            step["comment_id"] for step in chain if step.get("comment_id")
        }
        self.assertIn("d0a0bc7f-f3a4-443e-b757-29cdcaeb8b64", owner_comments)
        self.assertIn("bb788d11-a6a1-4fd7-a4aa-5113f9551a01", owner_comments)
        report_hash = addendum["audit_report"]["sha256"]
        self.assertEqual(
            report_hash,
            file_sha256(ROOT / addendum["audit_report"]["path"]),
        )

    def test_addendum_variants_equal_protocol_v2_execution_ids(self):
        addendum = load_json(PREREG_V11)
        protocol = load_json(ROOT / "catalog" / "public" / "preregistration_variant_protocol.v2.json")
        execution_ids = [v["execution_id"] for v in protocol["canonical_execution_variants"]]
        self.assertEqual(addendum["variant_ids"], execution_ids)
        crosswalk = addendum["recorded_pre_execution_changes"]["variant_vocabulary_addendum"]
        self.assertEqual(
            crosswalk["protocol"]["sha256"],
            file_sha256(ROOT / "catalog" / "public" / "preregistration_variant_protocol.v2.json"),
        )
        self.assertNotIn("single_factor_control", addendum["variant_ids"])

    def test_case_tier_registry_matches_frozen_plans(self):
        addendum = load_json(PREREG_V11)
        registry = addendum["recorded_pre_execution_changes"]["case_tier_registry"]
        cells = {(c["family_id"], c["variant_id"]): (c["tier"], c["track"]) for c in registry["cells"]}
        self.assertEqual(len(registry["cells"]), 90)
        for plan_rel in (
            "contracts/stage3_acceptance_plan.v3.10.json",
            "contracts/stage3_acceptance_plan.v3.11.json",
        ):
            plan = load_json(ROOT / plan_rel)
            plan_cells = {
                (t["family_id"], t["variant_id"]): (t["tier"], t["track"])
                for t in plan["tasks"]
            }
            self.assertEqual(cells, plan_cells, plan_rel)

    def test_loss_mapping_action_and_exemption_clauses_registered(self):
        addendum = load_json(PREREG_V11)
        rules = addendum["new_registrations"]["loss_level_mapping"]["rules"]
        self.assertEqual(set(rules), {"L0", "L1", "L2", "L3", "L4"})
        self.assertTrue(all(rules[level] for level in rules))
        self.assertTrue(addendum["new_registrations"]["action_vocabulary_addendum"])
        clause = addendum["new_registrations"]["single_factor_rule_derived_change_exemption"]["clause"]
        self.assertIn("single_factor_rule", clause)

    def test_v2_frozen_contract_validates(self):
        self.assertEqual(
            validate_frozen_contract(),
            {"families": 30, "models": 3, "variants": 3},
        )

    def test_v2_manifest_freeze_verifies_with_v1_lineage(self):
        result = verify_freeze()
        self.assertGreaterEqual(result["files"], 14)
        self.assertRegex(result["contract_bundle_sha256"], r"^[0-9a-f]{64}$")
        manifest = load_json(grader_v2.MANIFEST_PATH)
        self.assertEqual(
            manifest["supersedes"]["sha256"],
            file_sha256(grader_v2.MANIFEST_V1_PATH),
        )


class V2FixtureTests(unittest.TestCase):
    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(GraderValidationError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_positive_partial_fixture_is_accepted_only_as_partial(self):
        fixture = load_json(FIXTURES / "results.partial.valid.v2.json")
        self.assertEqual(len(validate_results(fixture, require_complete=False)), 2)
        self.assert_contract_error(
            lambda: validate_results(fixture, require_complete=True),
            "incomplete matrix",
        )

    def test_negative_fixture_rejects_identity_and_legacy_roster_drift(self):
        fixture = load_json(FIXTURES / "results.partial.invalid.v2.json")
        for fragment in (
            "model identity mismatch",
            "unregistered logical_label",
            "duplicate matrix cell",
            "at least one critical invariant",
            "unknown critical invariants",
            "evidence_correct exceeds",
            "canonical non-negative",
            "invalid latency_ms",
            "unregistered variant_id",
            "unregistered model_label",
        ):
            self.assert_contract_error(
                lambda: validate_results(fixture, require_complete=False),
                fragment,
            )

    def test_v1_bundle_is_rejected_by_v2_contract(self):
        fixture = load_json(FIXTURES / "results.partial.valid.json")
        self.assert_contract_error(
            lambda: validate_results(fixture, require_complete=False),
            "unsupported result contract_version",
        )

    def test_complete_synthetic_matrix_is_exactly_810_unique_cells(self):
        rows = validate_results(synthetic_bundle())
        self.assertEqual(len(rows), 90 * 3 * 3)


class V2ScoringTests(unittest.TestCase):
    def test_dominant_candidate_is_reliable_and_silver_never_moves_estimates(self):
        ordinary = score_results(synthetic_bundle(silver_reversed=False))
        reversed_silver = score_results(synthetic_bundle(silver_reversed=True))
        self.assertEqual(ordinary["models"], reversed_silver["models"])
        self.assertEqual(ordinary["contract_version"], "2.0.0")
        self.assertEqual(ordinary["provisional_leader"], "qwen3.8-max")
        self.assertTrue(ordinary["ranking_reliable"])
        self.assertEqual(ordinary["models"]["qwen3.8-max"]["CSR"]["estimate"], 1.0)
        self.assertEqual(ordinary["models"]["glm-5.2"]["pass^3"]["estimate"], 0.0)
        self.assertEqual(ordinary["excluded_families"], [])

    def test_model_fallback_invalidates_results(self):
        bundle = synthetic_bundle()
        bundle["model_manifests"][1]["response_model_id"] = "fallback/other"
        with self.assertRaises(GraderValidationError) as caught:
            score_results(bundle)
        self.assertIn("model identity mismatch or fallback", str(caught.exception))

    def test_unregistered_top_level_field_is_an_auditable_failure(self):
        bundle = synthetic_bundle()
        bundle["track_weights"] = {
            "financial_knowledge_work": "1.0",
            "financial_tool_workflow": "0.0",
        }
        with self.assertRaises(GraderValidationError) as caught:
            score_results(bundle)
        self.assertIn("unregistered top-level fields", str(caught.exception))


class ExecutedMatrixConsumptionTests(unittest.TestCase):
    """The v2 contract must consume the executed 810 matrix as-is and
    reproduce the PER-32 audited statistics exactly (no caliber change)."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()
        cls.reference = load_json(ROOT / "audit" / "per32_part4_ranking_results.json")
        cls.result = score_results(cls.bundle)

    def test_bundle_validates_as_complete_810_matrix(self):
        rows = validate_results(self.bundle, require_complete=True)
        self.assertEqual(len(rows), 810)

    def test_point_estimates_intervals_and_top_probabilities_match_audit(self):
        for model, reference in self.reference["models"].items():
            actual = self.result["models"][model]
            for metric, values in reference.items():
                if metric == "bootstrap_top_probability":
                    self.assertEqual(actual[metric], values, f"{model}/{metric}")
                else:
                    self.assertEqual(actual[metric]["estimate"], values["estimate"], f"{model}/{metric}")
                    self.assertEqual(actual[metric]["ci95"], values["ci95"], f"{model}/{metric}")

    def test_pairwise_tests_match_audit(self):
        self.assertEqual(self.result["pairwise_csr"], self.reference["pairwise_csr"])

    def test_leader_gates_and_conclusion_match_audit(self):
        self.assertEqual(self.result["provisional_leader"], self.reference["provisional_leader"])
        self.assertEqual(self.result["leader_gates"], self.reference["leader_gates"])
        self.assertEqual(self.result["ranking_reliable"], self.reference["ranking_reliable"])
        self.assertFalse(self.result["ranking_reliable"])
        self.assertEqual(
            self.result["leave_one_family_out_leader_agreement"],
            self.reference["leave_one_family_out_leader_agreement"],
        )
        self.assertEqual(
            self.result["ranking_conclusion"],
            "No reliable global leader may be claimed",
        )

    def test_registered_loss_mapping_reproduces_audit_loss_distribution(self):
        actual = {}
        for row in self.bundle["runs"]:
            model = row["model_label"]
            actual.setdefault(model, {lvl: 0 for lvl in ("L0", "L1", "L2", "L3", "L4")})
            actual[model][row["max_loss_level"]] += 1
        self.assertEqual(actual, self.reference["loss_levels_by_model"])


if __name__ == "__main__":
    unittest.main()
