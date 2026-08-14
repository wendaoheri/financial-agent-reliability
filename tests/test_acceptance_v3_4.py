import json
import pathlib
import unittest

from contracts.run_trace_validator import file_sha256
from harness.acceptance_v3_4 import BASE_CONFIG, build_contract_manifest, verify_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AcceptanceV34Tests(unittest.TestCase):
    def test_contract_is_new_model_neutral_and_strictly_capped(self):
        manifest = build_contract_manifest()
        self.assertEqual(manifest["contract_version"], "3.4.0")
        self.assertFalse(manifest["candidate_visible_model_specific_changes"])
        self.assertFalse(manifest["retroactive_regrading"])
        self.assertEqual(manifest["preflight_execution"]["maximum_model_units"], 3)
        self.assertFalse(manifest["preflight_execution"]["acceptance_runs_authorized"])
        self.assertEqual(verify_manifest(manifest), [])

    def test_v33_is_referenced_by_hash_and_not_rewritten(self):
        config = json.loads((ROOT / "contracts" / "run_trace_harness_config.v3.4.json").read_text(encoding="utf-8"))
        self.assertEqual(config["base_config"]["sha256"], file_sha256(BASE_CONFIG))
        self.assertEqual(config["supersedes"]["version"], "3.3.0")

    def test_bailian_controls_and_redaction_are_frozen(self):
        config = json.loads((ROOT / "contracts" / "run_trace_harness_config.v3.4.json").read_text(encoding="utf-8"))
        controls = config["provider"]["common_request_controls"]
        self.assertEqual(controls["tool_choice"], "auto")
        self.assertFalse(controls["tool_stream"])
        self.assertFalse(controls["parallel_tool_calls"])
        self.assertFalse(config["provider"]["qwen3.8-max"]["wire_control"]["enable_thinking"])
        self.assertFalse(config["trace_policy"]["persist_arguments"])
        self.assertTrue(config["trace_policy"]["persist_known_field_types"])


if __name__ == "__main__":
    unittest.main()
