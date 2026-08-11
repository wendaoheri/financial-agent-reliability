import copy
import json
import pathlib
import unittest

from contracts.run_trace_validator_v2 import (
    HarnessContractV2Error,
    validate_harness_config_v2,
    validate_model_manifest_v2,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


class HarnessContractV2Tests(unittest.TestCase):
    def test_v2_corrects_qwen_identity_without_rewriting_v1(self):
        v1 = json.loads((CONTRACTS / "model_manifest.frozen.v1.json").read_text())
        v2 = json.loads((CONTRACTS / "model_manifest.frozen.v2.json").read_text())
        self.assertEqual(v1["models"][0]["requested_model_id"], "qwen-3.8-max")
        self.assertEqual(
            validate_model_manifest_v2(v2),
            ["deepseek-v4-pro", "glm-5.2", "qwen3.8-max"],
        )
        wrong = copy.deepcopy(v2)
        wrong["models"][0]["requested_model_id"] = "qwen-3.8-max"
        with self.assertRaisesRegex(HarnessContractV2Error, "candidate model ids"):
            validate_model_manifest_v2(wrong)

    def test_v2_freezes_bailian_compatible_tool_choice_auto(self):
        result = validate_harness_config_v2()
        self.assertEqual(result["contract_version"], "2.0.0")
        self.assertEqual(result["candidate_models"], 3)
        self.assertEqual(result["tool_choice"], "auto")


if __name__ == "__main__":
    unittest.main()
