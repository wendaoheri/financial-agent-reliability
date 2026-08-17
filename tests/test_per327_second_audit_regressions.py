"""PER-327 second-audit regressions: runtime, trace v6, freeze, and claims."""

from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.graders import baseline_v4 as grader_v4
from financial_agent_reliability.harness.bundle import ImmutableBundle
from financial_agent_reliability.harness.run_trace_validator_v6 import verify_trace
from financial_agent_reliability.harness.runner import OfflineHarness
from financial_agent_reliability.harness.stage3 import freeze_preflight_evidence
from financial_agent_reliability.inference_config import load_inference_config
from financial_agent_reliability.providers.bailian import BailianAdapter, BailianSettings


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMITMENTS = {
    "candidate_sha256": "1" * 64,
    "trace_sha256": "2" * 64,
    "projection_sha256": "3" * 64,
    "snapshot_sha256": "4" * 64,
}


def _second_provider_config(root: pathlib.Path):
    raw = json.loads((ROOT / "configs/inference.json").read_text(encoding="utf-8"))
    raw["providers"].append(
        {
            "name": "second",
            "api": "openai_chat_completions_compatible",
            "base_url": "https://second.example.invalid/v1",
            "credential_env": "SECOND_PROVIDER_ACCESS",
        }
    )
    raw["models"].append(
        {
            "model_id": "second-model",
            "provider": "second",
            "roles": ["candidate"],
            "allowed_response_model_ids": ["second-model", "second-alias"],
        }
    )
    path = root / "inference.custom.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_inference_config(path, env={})


def _trace_fixture(root: pathlib.Path):
    config = _second_provider_config(root)
    settings = BailianSettings.from_config(
        config, {"SECOND_PROVIDER_ACCESS": "fixture-only"}, "second"
    )
    adapter = BailianAdapter(settings, "second-model", config=config)
    source = root / "source"
    source.mkdir()
    (source / "case.json").write_text('{"fixture":true}\n', encoding="utf-8")
    bundle = ImmutableBundle.create(source, root / "bundle")
    harness = OfflineHarness(
        adapter,
        bundle,
        root / "checkpoints",
        inference_config_path=config.source_path,
        baseline_generation="v3",
        trace_contract_version="6.0.0",
    )

    def alias_response(request):
        return {
            "model": "second-alias",
            "accepted_parameters": list(request["parameters"]),
            "tool_call_supported": True,
            "output": "synthetic",
            "action": "answer",
        }

    trace = harness.run(
        case_id="case-second-provider",
        variant_id="normal",
        repeat=1,
        seed=20260811,
        frozen_input_path="case.json",
        preflight_transport=alias_response,
        inference_transport=alias_response,
    )
    path = root / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    return config, bundle, trace, path


class RuntimeAndTraceV6Tests(unittest.TestCase):
    def test_second_provider_and_alias_survive_run_trace_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, _bundle, trace, path = _trace_fixture(root)
            self.assertEqual(trace["status"], "succeeded")
            self.assertEqual(trace["provider"]["name"], "second")
            self.assertEqual(trace["provider"]["response_model_id"], "second-alias")
            self.assertEqual(
                trace["environment"]["network_scope"],
                "configured_provider_inference_only",
            )
            self.assertEqual(verify_trace(path, inference_config_path=config.source_path), [])

    def test_full_schema_rejects_omitted_required_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, _bundle, trace, _path = _trace_fixture(root)
            trace.pop("provider")
            path = root / "missing-provider.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            errors = verify_trace(path, inference_config_path=config.source_path)
            self.assertTrue(any("schema" in error and "provider" in error for error in errors))

    def test_full_schema_rejects_omitted_nested_required_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, _bundle, trace, _path = _trace_fixture(root)
            trace["retry"].pop("retries_used")
            path = root / "missing-retries-used.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            errors = verify_trace(path, inference_config_path=config.source_path)
            self.assertTrue(
                any("schema" in error and "retries_used" in error for error in errors)
            )

    def test_cross_block_anchors_reject_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config, _bundle, trace, _path = _trace_fixture(root)
            mutations = {
                "provider": lambda item: item["provider"].update({"name": "bailian"}),
                "requested_model": lambda item: item["provider"].update(
                    {"requested_model_id": "other-model"}
                ),
                "config_sha": lambda item: item["provider"].update(
                    {"inference_config_sha256": "0" * 64}
                ),
                "config_path": lambda item: item["provider"].update(
                    {"inference_config_path": "/wrong/config.json"}
                ),
                "bundle": lambda item: item["immutable_bundle"].update(
                    {"bundle_sha256": "0" * 64}
                ),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    candidate = copy.deepcopy(trace)
                    mutate(candidate)
                    path = root / f"tampered-{name}.json"
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    self.assertTrue(
                        verify_trace(path, inference_config_path=config.source_path)
                    )


class FreezeHardGateTests(unittest.TestCase):
    def test_failed_model_rows_cannot_be_frozen_as_passed(self):
        config = load_inference_config()
        rows = [
            {
                "provider": model.provider,
                "requested_model_id": model.model_id,
                "status": "blocked",
                "attempt_count": 1,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }
            for model in config.models
            if model.live_preflight_required
        ]
        report = {
            "contract_type": "stage3_live_preflight",
            "contract_version": "1.1.0",
            "status": "passed",
            "provider": "bailian",
            "providers": [{"name": "bailian", "endpoint_id": "bailian_000000000000"}],
            "inference_config_path": config.source_path.as_posix(),
            "inference_config_sha256": config.source_sha256,
            "counts": {
                "requested": len(rows),
                "passed": 0,
                "invalidated": 0,
                "blocked": len(rows),
            },
            "models": rows,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "forged-passed.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "status reconciliation"):
                freeze_preflight_evidence([path], root / "frozen", config=config)


class ClaimLabelSetTests(unittest.TestCase):
    def _case(self):
        return {
            "case_id": "case-claim-labels",
            "variant": {"family_id": "CLAIMS", "kind": "normal"},
            "quality": {"tier": "Gold"},
            "task": {
                "method_id": "lookup",
                "permissions": {"allowed_operations": ["read_snapshot"]},
                "expected_final_environment_state": {"state": "unchanged"},
            },
            "oracle": {
                "expected_status": "answer",
                "expected_value": {"last": "305.930", "currency": "USD"},
                "reason_codes": [],
            },
            "evidence_contract": {
                "material_record_ids": ["record-01"],
                "minimum_material_evidence_count": 1,
            },
            "applicable_critical_invariants": ["evidence_supports_material_claims"],
            "evidence_tier_requirement": True,
        }

    def _submission(self):
        return {
            "action": "answer",
            "value": {"last": "305.930", "currency": "USD"},
            "claims": {
                "last_price": "305.930",
                "quote_currency": "USD",
            },
            "reason_codes": [],
            "cited_record_ids": ["record-01"],
            "evidence_tier_labels": {
                "last_price": "research_direct_evidence",
                "quote_currency": "research_direct_evidence",
            },
            "method_id": "lookup",
            "observed_operations": ["read_snapshot"],
            "final_environment_state": {"state": "unchanged"},
        }

    def _grade(self, submission):
        case = self._case()
        return grader_v4.grade_run(
            case=case,
            oracle_result={"status": "answer", "value": case["oracle"]["expected_value"]},
            submission=submission,
            commitments=COMMITMENTS,
        )

    def test_label_keys_must_equal_enumerated_claim_keys(self):
        for labels in (
            {"unrelated_claim": "research_direct_evidence"},
            {"last_price": "research_direct_evidence"},
            {
                "last_price": "research_direct_evidence",
                "quote_currency": "research_direct_evidence",
                "extra": "illustrative_case",
            },
        ):
            with self.subTest(labels=labels):
                submission = self._submission()
                submission["evidence_tier_labels"] = labels
                row = self._grade(submission)
                self.assertFalse(row.evidence_tier_labels_valid)
                self.assertFalse(row.critical_success)

    def test_exact_claim_label_set_passes(self):
        row = self._grade(self._submission())
        self.assertTrue(row.evidence_tier_labels_valid)
        self.assertTrue(row.critical_success)


if __name__ == "__main__":
    unittest.main()
