"""Runtime boundary tests for the configuration-driven harness (PER-323 Stage 2).

Migration from the baseline-v1 shape (cleanup list M1/M2): the manifest and
smoke-plan tests retired together with ``matrix.py``/``smoke.py`` and the
v3.x acceptance chain; the assertions below keep the live capabilities
(provider settings, identity preflight, HTTP payload normalization, bounded
retries, evidence freezing, bundle/checkpoint idempotence, offline dry-run,
redaction, ledger, grader) at undiminished strength. The run-trace is now
asserted structurally in place of the removed ``contracts`` validator —
the formal successor schema lands with baseline v2 (Stage 3, PER-328).
"""

import json
import hashlib
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from financial_agent_reliability.graders.pipeline import GraderInputError, GraderPipeline
from financial_agent_reliability.harness.bundle import ImmutableBundle
from financial_agent_reliability.harness.checkpoint import CheckpointStore, CheckpointError
from financial_agent_reliability.harness.redaction import redact
from financial_agent_reliability.harness.runner import OfflineHarness
from financial_agent_reliability.harness.stage3 import freeze_preflight_evidence, run_live_preflights
from financial_agent_reliability.inference_config import load_inference_config
from financial_agent_reliability.providers.bailian import BailianAdapter, BailianConfigError, BailianSettings
from financial_agent_reliability.providers.bailian_http import (
    BailianHTTPError,
    BailianHTTPTransport,
    build_chat_completions_payload,
)
from financial_agent_reliability.simulators.ledger import LedgerError, SimulatedLedger


ROOT = pathlib.Path(__file__).resolve().parents[2]


def _raw_inference_config():
    return json.loads((ROOT / "configs" / "inference.json").read_text(encoding="utf-8"))


def _write_inference_config(directory, raw, name="custom-inference.json"):
    path = pathlib.Path(directory) / name
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _successful_transport_factory(calls=None, response_aliases=None):
    calls = calls if calls is not None else []
    response_aliases = response_aliases or {}

    class FixtureTransport:
        def __init__(self, settings, *, timeout_seconds):
            self.settings = settings
            self.timeout_seconds = timeout_seconds

        def __call__(self, request, *, force_tool_call):
            calls.append((self.settings.provider_name, request["model"]))
            return {
                "model": response_aliases.get(request["model"], request["model"]),
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": force_tool_call,
                "fallback_detected": False,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

    return FixtureTransport


class ProviderAdapterTests(unittest.TestCase):
    def settings(self):
        return BailianSettings.from_env(
            {
                "BENCH_BAILIAN_API_KEY": "fixture-secret-never-log",
                "BENCH_BAILIAN_BASE_URL": "https://example.invalid/compatible-mode/v1?ignored=yes",
                "BENCH_BAILIAN_MODEL_IDS": json.dumps(
                    ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
                ),
            }
        )

    def test_settings_use_exact_models_and_non_sensitive_endpoint_id(self):
        settings = self.settings()
        self.assertEqual(settings.endpoint_id, "bailian_" + settings.origin_sha256[:12])
        self.assertNotIn("example.invalid", settings.endpoint_id)
        self.assertNotIn("fixture-secret", repr(settings))
        self.assertEqual(
            settings.model_ids,
            tuple(
                model.model_id
                for model in load_inference_config().models_for_provider("bailian")
            ),
        )

    def test_alias_or_missing_secret_is_rejected(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "secret",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": "qwen-3.8-max,glm-5.2,deepseek-v4-pro",
        }
        with self.assertRaisesRegex(BailianConfigError, "exactly"):
            BailianSettings.from_env(env)
        env["BENCH_BAILIAN_MODEL_IDS"] = '["qwen3.8-max","glm-5.2","deepseek-v4-pro"]'
        env.pop("BENCH_BAILIAN_API_KEY")
        with self.assertRaisesRegex(BailianConfigError, "BENCH_BAILIAN_API_KEY"):
            BailianSettings.from_env(env)

    def test_preflight_identity_mismatch_invalidates_without_fallback(self):
        adapter = BailianAdapter(self.settings(), "qwen3.8-max")
        result = adapter.preflight(
            lambda request: {
                "model": "provider-fallback-model",
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": True,
            }
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.failure_type, "identity_mismatch")
        self.assertFalse(result.retryable)
        self.assertFalse(result.fallback_attempted)

    def test_http_payload_preserves_frozen_parameters_and_forces_tool_in_preflight(self):
        adapter = BailianAdapter(self.settings(), "qwen3.8-max")
        request = adapter.build_request(20260811)
        payload = build_chat_completions_payload(request, force_tool_call=True)
        self.assertEqual(payload["model"], "qwen3.8-max")
        self.assertEqual(payload["seed"], 20260811)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["top_p"], 1.0)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(
            [item["function"]["name"] for item in payload["tools"]],
            [item["name"] for item in request["tools"]],
        )
        self.assertNotIn("parameters", payload)

    def test_http_transport_normalizes_identity_usage_and_tool_capability(self):
        settings = self.settings()
        adapter = BailianAdapter(settings, "qwen3.8-max")
        body = {
            "model": "qwen3.8-max",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_fixture",
                                "type": "function",
                                "function": {
                                    "name": "read_frozen_case",
                                    "arguments": '{"case_id":"PREFLIGHT"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(body).encode("utf-8")

        transport = BailianHTTPTransport(settings, timeout_seconds=5)
        with patch("financial_agent_reliability.providers.bailian_http.urlopen", return_value=Response()) as opened:
            normalized = transport(adapter.build_request(20260811), force_tool_call=True)
        sent = opened.call_args.args[0]
        self.assertNotIn(settings.api_key, repr(normalized))
        self.assertEqual(normalized["model"], "qwen3.8-max")
        self.assertTrue(normalized["tool_call_supported"])
        self.assertEqual(normalized["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(
            set(normalized["accepted_parameters"]),
            set(adapter.build_request(20260811)["parameters"]),
        )
        self.assertEqual(sent.full_url, "https://example.invalid/compatible-mode/v1/chat/completions")

    def test_http_transport_classifies_errors_without_response_body(self):
        settings = self.settings()
        adapter = BailianAdapter(settings, "qwen3.8-max")
        transport = BailianHTTPTransport(settings, timeout_seconds=5)
        from urllib.error import HTTPError

        error = HTTPError(
            settings.base_url,
            429,
            "rate limited secret-shaped body",
            hdrs=None,
            fp=None,
        )
        with patch("financial_agent_reliability.providers.bailian_http.urlopen", side_effect=error):
            with self.assertRaises(BailianHTTPError) as caught:
                transport(adapter.build_request(20260811), force_tool_call=True)
        self.assertEqual(caught.exception.failure_type, "rate_limited")
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret-shaped", str(caught.exception))

    def test_tool_capability_failure_is_not_mislabeled_as_parameter_failure(self):
        adapter = BailianAdapter(self.settings(), "glm-5.2")
        result = adapter.preflight(
            lambda request: {
                "model": request["model"],
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": False,
            }
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.failure_type, "tool_capability_unverified")

    def test_live_preflight_retries_transient_failure_and_reconciles_models(self):
        settings = self.settings()
        calls: dict[str, int] = {}

        class FixtureTransport:
            def __init__(self, _settings, *, timeout_seconds):
                self.timeout_seconds = timeout_seconds

            def __call__(self, request, *, force_tool_call):
                model_id = request["model"]
                calls[model_id] = calls.get(model_id, 0) + 1
                if model_id == "glm-5.2" and calls[model_id] == 1:
                    raise BailianHTTPError("rate_limited", True, 429)
                return {
                    "model": model_id,
                    "accepted_parameters": list(request["parameters"]),
                    "tool_call_supported": force_tool_call,
                    "fallback_detected": False,
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                }

        result = run_live_preflights(
            settings,
            transport_factory=FixtureTransport,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["counts"], {"requested": 3, "passed": 3, "invalidated": 0, "blocked": 0})
        self.assertEqual([row["requested_model_id"] for row in result["models"]], list(settings.model_ids))
        glm = next(row for row in result["models"] if row["requested_model_id"] == "glm-5.2")
        self.assertEqual(glm["attempt_count"], 2)
        self.assertEqual(glm["usage"], {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6})
        # PER-323 lineage: the two contract hashes replace the retired
        # harness-config/model-manifest pins.
        self.assertEqual(len(result["inference_config_sha256"]), 64)
        self.assertEqual(len(result["harness_contract_sha256"]), 64)
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(settings.api_key, rendered)
        self.assertNotIn(settings.base_url, rendered)

    def test_live_preflight_groups_and_runs_a_second_provider(self):
        raw = _raw_inference_config()
        raw["providers"].append(
            {
                "name": "second",
                "api": "openai_chat_completions_compatible",
                "base_url": "https://second.example.invalid/v1",
                "credential_env": "SECOND_PROVIDER_ACCESS",
            }
        )
        raw["models"].append(
            {"model_id": "second-model", "provider": "second", "roles": ["candidate"]}
        )
        with tempfile.TemporaryDirectory() as directory:
            config = load_inference_config(_write_inference_config(directory, raw), env={})
            env = {
                "BENCH_BAILIAN_API_KEY": "fixture-bailian",
                "SECOND_PROVIDER_ACCESS": "fixture-second",
            }
            settings = tuple(
                BailianSettings.from_config(config, env, provider.name)
                for provider in config.providers
            )
            calls = []
            result = run_live_preflights(
                settings,
                config=config,
                transport_factory=_successful_transport_factory(calls),
            )
        self.assertEqual(result["counts"]["requested"], 4)
        self.assertEqual({row["provider"] for row in result["models"]}, {"bailian", "second"})
        self.assertIn(("second", "second-model"), calls)

    def test_live_preflight_skips_false_flag_without_resolving_unused_provider(self):
        raw = _raw_inference_config()
        raw["models"][0]["live_preflight_required"] = False
        raw["providers"].append(
            {
                "name": "unused",
                "api": "openai_chat_completions_compatible",
                "base_url": "https://unused.example.invalid/v1",
                "credential_env": "UNUSED_PROVIDER_ACCESS",
            }
        )
        raw["models"].append(
            {
                "model_id": "unused-model",
                "provider": "unused",
                "roles": ["candidate"],
                "live_preflight_required": False,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            config = load_inference_config(_write_inference_config(directory, raw), env={})
            env = {"BENCH_BAILIAN_API_KEY": "fixture-bailian"}
            settings = BailianSettings.from_config(config, env, "bailian")
            calls = []
            result = run_live_preflights(
                settings,
                config=config,
                transport_factory=_successful_transport_factory(calls),
            )
        self.assertEqual(result["counts"]["requested"], 2)
        self.assertNotIn("qwen3.8-max", {model for _provider, model in calls})
        self.assertNotIn("unused-model", {model for _provider, model in calls})

    def test_allowed_response_alias_uses_injected_model_config(self):
        raw = _raw_inference_config()
        raw["models"][0]["allowed_response_model_ids"] = ["qwen3.8-max", "qwen-alias"]
        with tempfile.TemporaryDirectory() as directory:
            config = load_inference_config(_write_inference_config(directory, raw), env={})
            settings = BailianSettings.from_config(
                config, {"BENCH_BAILIAN_API_KEY": "fixture"}
            )
            result = run_live_preflights(
                settings,
                config=config,
                transport_factory=_successful_transport_factory(
                    response_aliases={"qwen3.8-max": "qwen-alias"}
                ),
            )
        alias_row = next(
            row for row in result["models"] if row["requested_model_id"] == "qwen3.8-max"
        )
        self.assertEqual(alias_row["status"], "passed")
        self.assertTrue(alias_row["identity_match"])
        self.assertEqual(alias_row["response_model_id"], "qwen-alias")

    def test_custom_config_path_and_hash_flow_into_report_and_frozen_bundle(self):
        raw = _raw_inference_config()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config_path = _write_inference_config(root, raw, "inference.custom.json")
            config = load_inference_config(config_path, env={})
            settings = BailianSettings.from_config(
                config, {"BENCH_BAILIAN_API_KEY": "fixture"}
            )
            result = run_live_preflights(
                settings,
                config=config,
                transport_factory=_successful_transport_factory(),
            )
            expected_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
            self.assertEqual(result["inference_config_path"], config_path.resolve().as_posix())
            self.assertEqual(result["inference_config_sha256"], expected_sha)
            report = root / "preflight.json"
            report.write_text(json.dumps(result), encoding="utf-8")
            bundle = freeze_preflight_evidence(
                [report], root / "frozen", config=config
            )
            decision = json.loads(
                (bundle.root / "execution_decision.json").read_text(encoding="utf-8")
            )
            self.assertEqual(decision["inference_config_path"], config_path.resolve().as_posix())
            self.assertEqual(decision["inference_config_sha256"], expected_sha)
            self.assertEqual(
                (bundle.root / "contracts" / "inference.json").read_bytes(),
                config_path.read_bytes(),
            )

    def test_blocked_preflights_freeze_reconciled_evidence_bundle(self):
        fixture = {
            "contract_type": "stage3_live_preflight",
            "contract_version": "1.1.0",
            "status": "blocked",
            "endpoint_id": "bailian_fixture",
            "inference_config_path": load_inference_config().source_path.as_posix(),
            "inference_config_sha256": load_inference_config().source_sha256,
            "counts": {"requested": 3, "passed": 0, "invalidated": 1, "blocked": 2},
            "models": [
                {
                    "requested_model_id": model,
                    "status": "invalidated" if model == "glm-5.2" else "blocked",
                    "attempt_count": 1,
                    "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                }
                for model in ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro")
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            report = root / "preflight.json"
            report.write_text(json.dumps(fixture), encoding="utf-8")
            bundle = freeze_preflight_evidence([report], root / "frozen")
            self.assertEqual(bundle.verify(), bundle.bundle_sha256)
            decision = json.loads(
                (bundle.root / "execution_decision.json").read_text(encoding="utf-8")
            )
            self.assertEqual(decision["provider_requests"], 3)
            self.assertEqual(decision["usage"]["total_tokens"], 9)
            self.assertFalse(decision["smoke_started"])
            self.assertFalse(decision["full_matrix_started"])
            self.assertEqual(decision["planned_matrix_runs"], 0)
            self.assertEqual(len(decision["inference_config_sha256"]), 64)
            self.assertEqual(len(decision["harness_contract_sha256"]), 64)
            # The frozen bundle carries the two live contracts as lineage.
            artifact_paths = {path for path, _sha in bundle.artifacts}
            self.assertIn("contracts/inference.json", artifact_paths)
            self.assertIn("contracts/harness_contract.v1.json", artifact_paths)


class ManifestAndRecoveryTests(unittest.TestCase):
    def test_pi_agent_core_is_exactly_locked_with_frozen_integrity(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        harness_contract = json.loads(
            (ROOT / "configs" / "harness_contract.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            package["dependencies"]["@mariozechner/pi-agent-core"], "0.73.1"
        )
        locked = lock["packages"]["node_modules/@mariozechner/pi-agent-core"]
        self.assertEqual(locked["version"], "0.73.1")
        self.assertEqual(
            locked["integrity"],
            harness_contract["runtime"]["registry_integrity"],
        )
        self.assertEqual(
            locked["integrity"],
            "sha512-Y/KVOhuKSgRQgYBlwmRtO2gPkUcoavOSqGF9bpQIINvNZvc19k6Z1H3bFDTce3Vp5ApMmTsfLH3+tNvOg75fAQ==",
        )

    def test_immutable_bundle_hash_and_checkpoint_resume_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "case.json").write_text('{"case":"FTW-04"}\n', encoding="utf-8")
            bundle = ImmutableBundle.create(source, root / "bundle")
            self.assertEqual(bundle.verify(), bundle.bundle_sha256)
            with self.assertRaises(PermissionError):
                bundle.write_text("new.json", "forbidden")

            store = CheckpointStore(root / "checkpoints", "run_" + "a" * 32)
            first = store.append("started", {"step": 1})
            resumed = CheckpointStore.resume(root / "checkpoints", store.run_id)
            second = resumed.append("completed", {"step": 2})
            self.assertEqual(second.offset, first.offset + 1)
            self.assertEqual(resumed.run_id, store.run_id)
            checkpoint_path = root / "checkpoints" / f"{store.run_id}.jsonl"
            checkpoint_path.write_text(
                checkpoint_path.read_text(encoding="utf-8") + '{"tampered":true}\n',
                encoding="utf-8",
            )
            with self.assertRaises(CheckpointError):
                CheckpointStore.resume(root / "checkpoints", store.run_id)

    def test_offline_dry_run_emits_valid_trace_and_resumes_same_run_id(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret-never-persist",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": json.dumps(
                ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
            ),
        }
        settings = BailianSettings.from_env(env)
        adapter = BailianAdapter(settings, "qwen3.8-max")

        def preflight(request):
            return {
                "model": request["model"],
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": True,
            }

        inference_calls = 0

        def inference(request):
            nonlocal inference_calls
            inference_calls += 1
            if inference_calls == 1:
                raise TimeoutError("synthetic timeout")
            return {
                "model": request["model"],
                "output": "Synthetic fixture answer; no external action.",
                "action": "answer",
                "usage": {"input_tokens": 20, "output_tokens": 8},
                "cost": {"input_usd": "0.000000", "output_usd": "0.000000"},
            }

        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            source = temp / "source"
            source.mkdir()
            (source / "case.json").write_text(
                json.dumps({"case_id": "FTW-01", "prompt": "Use synthetic data."}),
                encoding="utf-8",
            )
            bundle = ImmutableBundle.create(source, temp / "bundle")
            harness = OfflineHarness(adapter, bundle, temp / "checkpoints")
            first = harness.run(
                case_id="FTW-01",
                variant_id="baseline",
                repeat=1,
                seed=20260811,
                frozen_input_path="case.json",
                preflight_transport=preflight,
                inference_transport=inference,
            )
            # Structural run-trace assertions in place of the removed
            # contracts.run_trace_validator_v2 (successor schema: Stage 3).
            self.assertEqual(first["contract_type"], "run_trace")
            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(first["retry"]["retries_used"], 1)
            self.assertTrue(first["preflight"]["valid"])
            self.assertEqual(
                first["provider"]["response_model_id"], "qwen3.8-max"
            )
            self.assertEqual(
                set(first["request"]["parameters"]),
                {"temperature", "top_p", "max_tokens", "stream"},
            )
            self.assertEqual(first["request"]["seed"], 20260811)
            identity = first["run_identity"]
            self.assertEqual(len(identity["inference_config_sha256"]), 64)
            self.assertEqual(len(identity["harness_contract_sha256"]), 64)
            self.assertEqual(
                identity["immutable_bundle_sha256"], bundle.bundle_sha256
            )
            self.assertNotIn("fixture-secret-never-persist", json.dumps(first))
            second = harness.run(
                case_id="FTW-01",
                variant_id="baseline",
                repeat=1,
                seed=20260811,
                frozen_input_path="case.json",
                preflight_transport=preflight,
                inference_transport=inference,
            )
            self.assertEqual(second["run_id"], first["run_id"])
            self.assertTrue(second["resume"]["resumed"])
            self.assertEqual(second["status"], "succeeded")


class SafetyAndGraderTests(unittest.TestCase):
    def test_redaction_removes_headers_secret_fields_and_bearer_values(self):
        cleaned = redact(
            {
                "Authorization": "Bearer abcdefghijklmnop",
                "api_key": "sk-should-not-survive",
                "nested": ["BENCH_BAILIAN_API_KEY=plain-secret", "safe"],
            }
        )
        rendered = json.dumps(cleaned, sort_keys=True)
        self.assertNotIn("abcdefghijklmnop", rendered)
        self.assertNotIn("plain-secret", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_redaction_covers_generic_provider_env_assignments(self):
        cleaned = redact(
            {"log": "export FARELI_MOONSHOT_API_KEY=top-secret-value-123 done"}
        )
        rendered = json.dumps(cleaned, sort_keys=True)
        self.assertNotIn("top-secret-value-123", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_simulated_ledger_handles_timeout_duplicate_permission_and_idempotency(self):
        ledger = SimulatedLedger("ledger-1", allowed_instruments={"AAPL.US"})
        preview = ledger.apply("preview", "AAPL.US", "2", "key-preview")
        self.assertEqual(preview.state, "previewed")
        pending = ledger.apply("buy", "AAPL.US", "2", "key-buy", timeout=True)
        self.assertEqual(pending.state, "unknown")
        confirmed = ledger.confirm("key-buy", "committed")
        duplicate = ledger.confirm("key-buy", "committed")
        self.assertEqual(confirmed.event_id, duplicate.event_id)
        self.assertEqual(ledger.positions["AAPL.US"], "2")
        with self.assertRaisesRegex(LedgerError, "idempotency"):
            ledger.apply("buy", "AAPL.US", "3", "key-buy")
        with self.assertRaisesRegex(LedgerError, "permission"):
            ledger.apply("buy", "MSFT.US", "1", "key-other")

    def test_grader_priority_gold_silver_and_blind_judge_isolation(self):
        pipeline = GraderPipeline()
        rows = [
            {
                "run_id": "run-gold",
                "family_id": "FTW-01",
                "tier": "Gold",
                "model_id": "qwen3.8-max",
                "environment_state_oracle": {"critical_success": False},
                "executable_oracle": {"critical_success": True},
            },
            {
                "run_id": "run-silver",
                "family_id": "FTW-14",
                "tier": "Silver",
                "model_id": "glm-5.2",
                "structured_evidence_oracle": {"critical_success": True},
            },
        ]
        result = pipeline.prepare(rows, blind_salt="fixture-salt")
        self.assertEqual(len(result.ranking_rows), 1)
        self.assertFalse(result.ranking_rows[0]["critical_success"])
        self.assertEqual(len(result.diagnostic_rows), 1)
        judge_payload = result.judge_payloads[0]
        self.assertNotIn("model_id", judge_payload)
        self.assertNotIn("qwen", json.dumps(judge_payload))
        self.assertIn("blind_model_id", judge_payload)

        invalid = [dict(rows[0], blind_independent_expert={"critical_success": True})]
        with self.assertRaisesRegex(GraderInputError, "expert isolation"):
            pipeline.prepare(invalid, blind_salt="fixture-salt")


if __name__ == "__main__":
    unittest.main()
