import json
import pathlib
import unittest

from contracts.run_trace_validator import file_sha256
from financial_agent_reliability.harness.acceptance_v3_3 import BASE_CONFIG, build_contract_manifest, verify_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AcceptanceV33Tests(unittest.TestCase):
    def test_contract_is_model_neutral_and_capped_before_paid_preflight(self):
        manifest = build_contract_manifest()
        self.assertEqual(manifest["contract_version"], "3.3.0")
        self.assertFalse(manifest["model_specific_changes"])
        self.assertFalse(manifest["retroactive_regrading"])
        self.assertEqual(manifest["preflight_execution"]["maximum_model_units"], 6)
        self.assertFalse(manifest["preflight_execution"]["acceptance_runs_authorized"])
        self.assertEqual(verify_manifest(manifest), [])

    def test_v32_is_referenced_by_hash_and_not_rewritten(self):
        config = json.loads((ROOT / "contracts" / "run_trace_harness_config.v3.3.json").read_text(encoding="utf-8"))
        self.assertEqual(config["base_config"]["sha256"], file_sha256(BASE_CONFIG))
        self.assertEqual(config["supersedes"]["version"], "3.2.0")

    def test_trace_policy_never_persists_raw_arguments_or_errors(self):
        config = json.loads((ROOT / "contracts" / "run_trace_harness_config.v3.3.json").read_text(encoding="utf-8"))
        self.assertFalse(config["trace_policy"]["persist_arguments"])
        self.assertFalse(config["trace_policy"]["persist_raw_validation_error"])
        self.assertTrue(config["trace_policy"]["persist_arguments_sha256"])
        self.assertTrue(config["trace_policy"]["persist_validation_category_and_path"])


if __name__ == "__main__":
    unittest.main()
