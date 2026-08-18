"""PER-327 fourth-audit regressions for external registry commitments."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.harness.bundle import ImmutableBundle
from financial_agent_reliability.harness.hashing import build_run_id
from financial_agent_reliability.harness.run_trace_validator_v7 import (
    verify_trace as verify_v7_trace,
)
from financial_agent_reliability.harness.run_trace_validator_v8 import (
    load_frozen_input_registry,
    verify_trace,
)
from financial_agent_reliability.harness.runner_v8 import OfflineHarnessV8
from financial_agent_reliability.providers.bailian import BailianAdapter, BailianSettings


def _bundle_sha256(artifacts: list[dict]) -> str:
    commitments = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(artifacts, key=lambda item: item["path"])
    )
    return hashlib.sha256(commitments.encode("utf-8")).hexdigest()


class RegistryCommitmentTests(unittest.TestCase):
    def _fixture(self, root: pathlib.Path):
        source = root / "source"
        (source / "cases").mkdir(parents=True)
        case_a = source / "cases/case-a.json"
        case_b = source / "cases/case-b.json"
        case_a.write_text(
            '{"case_id":"case-a","variant":{"kind":"normal"}}\n',
            encoding="utf-8",
        )
        case_b.write_text(
            '{"case_id":"case-b","variant":{"kind":"normal"}}\n',
            encoding="utf-8",
        )
        bundle = ImmutableBundle.create(source, root / "bundle")
        registry_path = source / "contracts/frozen_input_registry.json"
        registry_path.parent.mkdir()
        registry_path.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "case_id": "case-a",
                            "variant_id": "normal",
                            "path": "cases/case-a.json",
                            "sha256": hashlib.sha256(case_a.read_bytes()).hexdigest(),
                        },
                        {
                            "case_id": "case-b",
                            "variant_id": "normal",
                            "path": "cases/case-b.json",
                            "sha256": hashlib.sha256(case_b.read_bytes()).hexdigest(),
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        settings = BailianSettings.from_env(
            {"BENCH_BAILIAN_API_KEY": "fixture-never-persist"}
        )
        harness = OfflineHarnessV8(
            BailianAdapter(settings, "qwen3.8-max"), bundle, root / "checkpoints"
        )

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
            seed=20260818,
            frozen_input_path="cases/case-a.json",
            preflight_transport=successful,
            inference_transport=successful,
        )
        return trace, registry_path

    def test_run_trace_verify_accepts_exact_external_commitment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            trace, registry_path = self._fixture(root)
            trace_path = root / "trace.json"
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            self.assertEqual(verify_trace(trace_path, registry_path=registry_path), [])

    def test_internally_reanchored_artifact_sha_still_hard_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            trace, registry_path = self._fixture(root)
            forged = copy.deepcopy(trace)
            target = next(
                item
                for item in forged["immutable_bundle"]["artifacts"]
                if item["path"] == "cases/case-a.json"
            )
            target["sha256"] = "f" * 64
            forged["immutable_bundle"]["bundle_sha256"] = _bundle_sha256(
                forged["immutable_bundle"]["artifacts"]
            )
            forged["run_identity"]["immutable_bundle_sha256"] = forged[
                "immutable_bundle"
            ]["bundle_sha256"]
            forged["context"]["frozen_input_sha256"] = target["sha256"]
            forged["run_id"] = build_run_id(forged["run_identity"])
            trace_path = root / "internally-reanchored.json"
            trace_path.write_text(json.dumps(forged), encoding="utf-8")

            commitments, registry_errors = load_frozen_input_registry(registry_path)
            self.assertEqual(registry_errors, [])
            legacy = copy.deepcopy(forged)
            legacy["contract_version"] = "7.0.0"
            legacy_path = root / "legacy-v7.json"
            legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
            weak_paths = {key: value.path for key, value in commitments.items()}
            self.assertEqual(
                verify_v7_trace(legacy_path, registered_inputs=weak_paths), []
            )

            errors = verify_trace(trace_path, registry_path=registry_path)
            self.assertTrue(errors)
            self.assertTrue(
                any("registry sha256 != bundle artifact" in error for error in errors),
                errors,
            )

    def test_cross_case_wrong_registry_sha_and_unregistered_case_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            trace, registry_path = self._fixture(root)
            mutations = []
            cross_case = copy.deepcopy(trace)
            cross_case["context"]["frozen_input_path"] = "cases/case-b.json"
            mutations.append(cross_case)
            unregistered = copy.deepcopy(trace)
            unregistered["run_identity"]["case_id"] = "case-unregistered"
            unregistered["run_id"] = build_run_id(unregistered["run_identity"])
            mutations.append(unregistered)
            for index, candidate in enumerate(mutations):
                path = root / f"identity-mismatch-{index}.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                self.assertTrue(verify_trace(path, registry_path=registry_path))

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["entries"][0]["sha256"] = "0" * 64
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            commitments, errors = load_frozen_input_registry(registry_path)
            self.assertTrue(commitments)
            self.assertTrue(any("actual frozen file" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
