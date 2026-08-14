import json
import pathlib
import unittest

from financial_agent_reliability.harness.acceptance_v3_5 import build_acceptance_plan, build_contract_manifest, verify_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "runs" / "stage3" / "acceptance-20260812-v3.4" / "preflight.auto_split.v3.4.json"


class FinancialAcceptanceV35Tests(unittest.TestCase):
    def test_execution_bundle_is_new_and_preserves_old_results(self):
        manifest = build_contract_manifest()
        self.assertEqual(manifest["contract_version"], "3.5.0")
        self.assertFalse(manifest["retroactive_regrading"])
        self.assertFalse(manifest["candidate_visible_model_specific_changes"])
        self.assertEqual(verify_manifest(manifest), [])

    def test_plan_has_exact_new_36_run_scope(self):
        plan = build_acceptance_plan(PREFLIGHT, write=False)
        self.assertEqual(len(plan["tasks"]), 12)
        self.assertEqual(len(plan["runs"]), 36)
        self.assertEqual(len({row["run_id"] for row in plan["runs"]}), 36)
        self.assertEqual({row["model_id"] for row in plan["runs"]}, {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"})
        self.assertEqual(plan["authorization"]["approval_comment_id"], "fb2cbcf2-99dc-4c30-82d7-9adf13e81547")
        self.assertFalse(plan["full_matrix_authorized"])
        old_ids = set()
        for path in (ROOT / "runs" / "stage3").glob("**/traces/*.json"):
            old_ids.add(path.stem)
        self.assertFalse(old_ids & {row["run_id"] for row in plan["runs"]})

    def test_plan_requires_the_frozen_3_of_3_preflight(self):
        artifact = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
        self.assertEqual(artifact["counts"], {"requested": 3, "passed": 3, "blocked": 0})
        self.assertEqual(artifact["decision"], "split_protocol_passed_3_of_3")


if __name__ == "__main__":
    unittest.main()
