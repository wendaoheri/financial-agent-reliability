"""PER-327 third-audit regression for frozen-input identity binding."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.harness.bundle import ImmutableBundle
from financial_agent_reliability.harness.run_trace_validator_v7 import verify_trace
from financial_agent_reliability.harness.runner_v7 import OfflineHarnessV7
from financial_agent_reliability.providers.bailian import BailianAdapter, BailianSettings


class FrozenInputIdentityBindingTests(unittest.TestCase):
    def _fixture(self, root: pathlib.Path):
        settings = BailianSettings.from_env(
            {"BENCH_BAILIAN_API_KEY": "fixture-never-persist"}
        )
        adapter = BailianAdapter(settings, "qwen3.8-max")
        source = root / "source"
        (source / "cases").mkdir(parents=True)
        case_a = source / "cases/case-a.json"
        case_b = source / "cases/case-b.json"
        case_a.write_text('{"case_id":"case-a","value":"A"}\n', encoding="utf-8")
        case_b.write_text('{"case_id":"case-b","value":"B"}\n', encoding="utf-8")
        bundle = ImmutableBundle.create(source, root / "bundle")
        harness = OfflineHarnessV7(adapter, bundle, root / "checkpoints")

        def successful(request):
            return {
                "model": request["model"],
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": True,
                "output": "synthetic",
                "action": "answer",
            }

        trace = harness.run(
            case_id="case-a",
            variant_id="normal",
            repeat=1,
            seed=20260811,
            frozen_input_path="cases/case-a.json",
            preflight_transport=successful,
            inference_transport=successful,
        )
        registry = {
            ("case-a", "normal"): "cases/case-a.json",
            ("case-b", "normal"): "cases/case-b.json",
        }
        return trace, registry, case_b

    def test_correct_case_variant_path_and_sha_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            trace, registry, _case_b = self._fixture(root)
            path = root / "trace.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            self.assertEqual(verify_trace(path, registered_inputs=registry), [])

    def test_case_a_cannot_point_to_case_b_real_path_and_sha_in_same_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            trace, registry, case_b = self._fixture(root)
            tampered = copy.deepcopy(trace)
            tampered["context"]["frozen_input_path"] = "cases/case-b.json"
            tampered["context"]["frozen_input_sha256"] = hashlib.sha256(
                case_b.read_bytes()
            ).hexdigest()
            path = root / "cross-case.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            errors = verify_trace(path, registered_inputs=registry)
            self.assertTrue(errors)
            self.assertTrue(any("registered frozen input" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
