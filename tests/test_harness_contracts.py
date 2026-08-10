import copy
import pathlib
import unittest

from contracts.run_trace_validator import (
    HarnessContractError,
    build_run_id,
    load_json,
    validate_harness_config,
    validate_model_manifest,
    validate_run_trace,
    verify_freeze,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures" / "harness"


def fixture(name):
    return load_json(FIXTURES / name)


class HarnessContractTests(unittest.TestCase):
    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(HarnessContractError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_frozen_harness_has_exact_dependency_prompt_tools_and_budget(self):
        result = validate_harness_config()
        self.assertEqual(result["pi_agent_core"], "0.73.1")
        self.assertEqual(result["candidate_models"], 3)
        self.assertEqual(result["tool_execution"], "sequential")

    def test_schemas_are_draft_2020_12_and_versioned(self):
        for name in ("model_manifest.schema.v1.json", "run_trace.schema.v1.json"):
            schema = load_json(CONTRACTS / name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith(name))

    def test_model_manifest_accepts_only_three_exact_bailian_ids(self):
        manifest = load_json(CONTRACTS / "model_manifest.frozen.v1.json")
        self.assertEqual(
            validate_model_manifest(manifest),
            ["deepseek-v4-pro", "glm-5.2", "qwen-3.8-max"],
        )
        aliased = copy.deepcopy(manifest)
        aliased["models"][0]["requested_model_id"] = "qwen3.8-max"
        self.assert_contract_error(
            lambda: validate_model_manifest(aliased),
            "candidate model ids must be exact",
        )

    def test_normal_trace_is_accepted(self):
        trace = fixture("run_trace.normal.json")
        self.assertEqual(validate_run_trace(trace)["status"], "succeeded")

    def test_identity_mismatch_fixture_is_invalidated_without_fallback(self):
        trace = fixture("run_trace.identity_mismatch.json")
        result = validate_run_trace(trace)
        self.assertEqual(result["status"], "invalidated")
        self.assertEqual(result["failure_type"], "identity_mismatch")
        self.assertFalse(trace["preflight"]["fallback_attempted"])

    def test_timeout_fixture_is_terminal_and_classified(self):
        trace = fixture("run_trace.timeout.json")
        result = validate_run_trace(trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], "timeout")

    def test_rate_limit_retry_fixture_records_bounded_retry(self):
        trace = fixture("run_trace.rate_limit_retry.json")
        result = validate_run_trace(trace)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["retries"], 1)
        self.assertEqual(trace["attempts"][0]["failure_type"], "rate_limited")

    def test_checkpoint_resume_fixture_preserves_idempotent_run_id(self):
        trace = fixture("run_trace.recovery.json")
        result = validate_run_trace(trace)
        expected = build_run_id(trace["run_identity"])
        self.assertEqual(trace["run_id"], expected)
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(trace["resume"]["resumed"])
        self.assertEqual(trace["resume"]["source_run_id"], trace["run_id"])

    def test_secret_leak_fixture_is_blocked(self):
        trace = fixture("run_trace.secret_leak.json")
        self.assert_contract_error(
            lambda: validate_run_trace(trace),
            "potential secret leakage",
        )

    def test_ignored_parameters_invalidate_preflight(self):
        trace = fixture("run_trace.normal.json")
        trace["preflight"]["parameters_honored"] = False
        trace["status"] = "succeeded"
        self.assert_contract_error(
            lambda: validate_run_trace(trace),
            "ignored parameters must invalidate the run",
        )

    def test_provider_fallback_cannot_be_reported_as_success(self):
        trace = fixture("run_trace.normal.json")
        trace["preflight"]["fallback_detected"] = True
        trace["preflight"]["identity_match"] = False
        self.assert_contract_error(
            lambda: validate_run_trace(trace),
            "fallback",
        )

    def test_real_trading_or_forbidden_config_access_is_rejected(self):
        trace = fixture("run_trace.normal.json")
        trace["environment"]["ledger_mode"] = "live"
        trace["environment"]["touched_paths"].append("~/.codex/config.toml")
        self.assert_contract_error(
            lambda: validate_run_trace(trace),
            "real trading is prohibited",
        )
        self.assert_contract_error(
            lambda: validate_run_trace(trace),
            "forbidden config path",
        )

    def test_contract_and_fixture_bundle_hashes_are_frozen(self):
        result = verify_freeze()
        self.assertGreaterEqual(result["files"], 13)
        self.assertRegex(result["contract_bundle_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
