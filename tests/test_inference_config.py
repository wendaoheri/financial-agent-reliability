"""Tests for the provider/model-configurable inference layer (PER-323 Stage 2).

Covers the design-contract §7 offline test points: schema validation,
secret-scan gate false-positive avoidance (R1/R2), resolution order,
environment overrides, credential fail-fast, BENCH_BAILIAN_* compatibility,
endpoint_id reproducibility, and the structured CLI error path (Stage 1b F7).
All tests run without any real credential.
"""

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from financial_agent_reliability.harness import secret_scan
from financial_agent_reliability.inference_config import (
    DEFAULT_CONFIG_PATH,
    InferenceConfig,
    InferenceConfigError,
    endpoint_origin,
    load_inference_config,
    merged_parameters,
    resolve_provider_runtime,
)
from financial_agent_reliability.providers.bailian import (
    BailianAdapter,
    BailianConfigError,
    BailianSettings,
    build_all_adapters,
    expected_models,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _raw_default() -> dict:
    return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def _write_config(directory: pathlib.Path, payload: dict) -> pathlib.Path:
    path = directory / "inference.test.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class SchemaAndLoaderTests(unittest.TestCase):
    def test_default_config_loads_with_expected_shape(self):
        config = load_inference_config()
        self.assertEqual(config.schema_version, "1.0.0")
        provider = config.provider("bailian")
        self.assertEqual(provider.api, "openai_chat_completions_compatible")
        self.assertEqual(provider.credential_env, "BENCH_BAILIAN_API_KEY")
        self.assertEqual(
            provider.default_parameters,
            {"temperature": "0.000000", "top_p": "1.000000", "max_tokens": 4096, "stream": True},
        )
        self.assertEqual(
            tuple(model.model_id for model in config.models_for_provider("bailian")),
            ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro"),
        )
        for model in config.models:
            self.assertEqual(model.roles, ("candidate",))
            self.assertTrue(model.live_preflight_required)
            self.assertIn(model.model_id, model.allowed_response_model_ids)
        self.assertEqual(expected_models(), ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro"))

    def test_schema_rejects_each_invalid_shape(self):
        mutations = {
            "missing_required": lambda raw: raw.pop("models"),
            "bad_contract_type": lambda raw: raw.update({"contract_type": "other"}),
            "bad_schema_major": lambda raw: raw.update({"schema_version": "2.0.0"}),
            "bad_provider_name": lambda raw: raw["providers"][0].update({"name": "Bailian"}),
            "bad_api_enum": lambda raw: raw["providers"][0].update({"api": "anthropic_messages"}),
            "bad_base_url": lambda raw: raw["providers"][0].update({"base_url": "ftp://x"}),
            "bad_credential_env": lambda raw: raw["providers"][0].update({"credential_env": "lower_case"}),
            "duplicate_provider_name": lambda raw: raw["providers"].append(dict(raw["providers"][0])),
            "duplicate_model_id": lambda raw: raw["models"].append(dict(raw["models"][0])),
            "dangling_provider_ref": lambda raw: raw["models"][0].update({"provider": "moonshot"}),
            "bad_role_vocabulary": lambda raw: raw["models"][0].update({"roles": ["judge"]}),
            "allowed_ids_exclude_self": lambda raw: raw["models"][0].update(
                {"allowed_response_model_ids": ["glm-5.2"]}
            ),
            "parameter_key_outside_whitelist": lambda raw: raw["providers"][0].update(
                {"default_parameters": {"seed": 1}}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                raw = _raw_default()
                mutate(raw)
                with tempfile.TemporaryDirectory() as directory:
                    path = _write_config(pathlib.Path(directory), raw)
                    with self.assertRaises(InferenceConfigError):
                        load_inference_config(path, env={})

    def test_secret_scan_gate_rejects_secret_shaped_keys_and_values(self):
        with_secret_key = _raw_default()
        with_secret_key["providers"][0]["api_key"] = "placeholder"
        with_secret_value = _raw_default()
        with_secret_value["providers"][0]["description"] = (
            "example header Bearer abcdef1234567890"
        )
        with_secret_env_name = _raw_default()
        with_secret_env_name["providers"][0]["credential_env"] = "MY_BEARER_CREDENTIAL"
        for name, raw in {
            "key_name_R1": with_secret_key,
            "value_R2": with_secret_value,
            "credential_env_R2": with_secret_env_name,
        }.items():
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as directory:
                    path = _write_config(pathlib.Path(directory), raw)
                    with self.assertRaises(InferenceConfigError):
                        load_inference_config(path, env={})

    def test_resolution_order_explicit_path_beats_env_beats_default(self):
        marker = _raw_default()
        marker["providers"][0]["name"] = "explicitprov"
        for model in marker["models"]:
            model["provider"] = "explicitprov"
        env_marker = _raw_default()
        env_marker["providers"][0]["name"] = "envprov"
        for model in env_marker["models"]:
            model["provider"] = "envprov"
        with tempfile.TemporaryDirectory() as directory:
            explicit_path = _write_config(pathlib.Path(directory), marker)
            env_path = pathlib.Path(directory) / "env.json"
            env_path.write_text(json.dumps(env_marker), encoding="utf-8")
            explicit = load_inference_config(explicit_path, env={"FARELI_INFERENCE_CONFIG": str(env_path)})
            self.assertEqual(explicit.providers[0].name, "explicitprov")
            via_env = load_inference_config(env={"FARELI_INFERENCE_CONFIG": str(env_path)})
            self.assertEqual(via_env.providers[0].name, "envprov")
            default = load_inference_config(env={})
            self.assertEqual(default.providers[0].name, "bailian")


class RuntimeResolutionTests(unittest.TestCase):
    def test_credential_missing_fails_fast_before_any_request(self):
        config = load_inference_config()
        with self.assertRaisesRegex(InferenceConfigError, "BENCH_BAILIAN_API_KEY"):
            resolve_provider_runtime(config, "bailian", {})
        with self.assertRaisesRegex(BailianConfigError, "BENCH_BAILIAN_API_KEY"):
            BailianSettings.from_config(config, {})

    def test_base_url_env_override_wins_and_invalid_override_rejected(self):
        config = load_inference_config()
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret",
            "FARELI_BAILIAN_BASE_URL": "https://override.example/v1",
        }
        runtime = resolve_provider_runtime(config, "bailian", env)
        self.assertEqual(runtime.base_url, "https://override.example/v1")
        self.assertTrue(runtime.endpoint_id.startswith("bailian_"))
        self.assertNotIn("fixture-secret", repr(runtime))
        compat = resolve_provider_runtime(
            config, "bailian", {"BENCH_BAILIAN_API_KEY": "s", "BENCH_BAILIAN_BASE_URL": "https://compat.example/v1"}
        )
        self.assertEqual(compat.base_url, "https://compat.example/v1")
        with self.assertRaisesRegex(InferenceConfigError, "absolute HTTP"):
            resolve_provider_runtime(
                config, "bailian", {"BENCH_BAILIAN_API_KEY": "s", "FARELI_BAILIAN_BASE_URL": "not-a-url"}
            )

    def test_endpoint_id_is_bytewise_reproducible_for_one_origin(self):
        config = load_inference_config()
        env = {"BENCH_BAILIAN_API_KEY": "fixture-secret"}
        first = resolve_provider_runtime(config, "bailian", env)
        second = resolve_provider_runtime(config, "bailian", env)
        self.assertEqual(first.endpoint_id, second.endpoint_id)
        origin, origin_hash = endpoint_origin("https://example.invalid/compatible-mode/v1?x=1")
        self.assertEqual(origin, "https://example.invalid")
        self.assertNotIn("x=1", first.endpoint_id)
        self.assertEqual(len(origin_hash), 64)

    def test_legacy_model_ids_env_strict_consistency(self):
        config = load_inference_config()
        matching = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret",
            "BENCH_BAILIAN_MODEL_IDS": '["qwen3.8-max","glm-5.2","deepseek-v4-pro"]',
        }
        settings = BailianSettings.from_config(config, matching)
        self.assertEqual(settings.model_ids, ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro"))
        comma_form = dict(matching, BENCH_BAILIAN_MODEL_IDS="qwen3.8-max, glm-5.2, deepseek-v4-pro")
        self.assertEqual(
            BailianSettings.from_config(config, comma_form).model_ids, settings.model_ids
        )
        divergent = dict(matching, BENCH_BAILIAN_MODEL_IDS='["qwen3.8-max"]')
        with self.assertRaisesRegex(BailianConfigError, "exactly"):
            BailianSettings.from_config(config, divergent)
        typo = dict(matching, BENCH_BAILIAN_MODEL_IDS="qwen-3.8-max,glm-5.2,deepseek-v4-pro")
        with self.assertRaisesRegex(BailianConfigError, "exactly"):
            BailianSettings.from_config(config, typo)

    def test_from_env_compat_matches_from_config(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": '["qwen3.8-max","glm-5.2","deepseek-v4-pro"]',
        }
        compat = BailianSettings.from_env(env)
        direct = BailianSettings.from_config(load_inference_config(env=env), env)
        self.assertEqual(compat, direct)
        self.assertEqual(compat.endpoint_id, "bailian_" + compat.origin_sha256[:12])

    def test_parameter_overrides_take_precedence(self):
        raw = _raw_default()
        raw["models"][0]["parameter_overrides"] = {"max_tokens": 2048}
        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(pathlib.Path(directory), raw)
            config = load_inference_config(path, env={})
            model = config.models[0]
            parameters = merged_parameters(config, model)
            self.assertEqual(parameters["max_tokens"], 2048)
            self.assertEqual(parameters["temperature"], "0.000000")

    def test_build_all_adapters_and_request_are_config_driven(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
        }
        config = load_inference_config(env=env)
        settings = BailianSettings.from_config(config, env)
        adapters = build_all_adapters(settings, config=config)
        self.assertEqual(
            [adapter.model_id for adapter in adapters], list(settings.model_ids)
        )
        request = adapters[0].build_request(20260811)
        self.assertEqual(request["parameters"]["seed"], 20260811)
        self.assertEqual(
            set(request["parameters"]),
            {"temperature", "top_p", "max_tokens", "stream", "seed"},
        )
        self.assertEqual(
            request["messages"][1]["content"],
            "Call read_frozen_case with case_id PREFLIGHT.",
        )
        self.assertEqual(len(request["tools"]), 4)
        with self.assertRaises(BailianConfigError):
            BailianAdapter(settings, "qwen-3.8-max")


class SecretScanGateTests(unittest.TestCase):
    def test_scan_flags_secret_keys_and_text_verbatim_from_f8(self):
        payload = {
            "safe": "value",
            "api_key": "whatever",
            "nested": [{"authorization": "x"}, "token sk-abcdefgh12345"],
            "bearer": "Bearer abcdef12345678",
        }
        findings = secret_scan.scan_persisted_value_for_secrets(payload)
        self.assertIn("$.api_key", findings)
        self.assertIn("$.nested[0].authorization", findings)
        self.assertIn("$.nested[1]", findings)
        self.assertIn("$.bearer", findings)
        self.assertEqual(secret_scan.scan_persisted_value_for_secrets({"ok": "plain"}), [])

    def test_credential_env_name_rule(self):
        self.assertEqual(secret_scan.check_credential_env_name("BENCH_BAILIAN_API_KEY"), [])
        self.assertEqual(
            secret_scan.check_credential_env_name("MY_BEARER_CREDENTIAL"), ["$"]
        )
        # Rule R2 forbids the literal substrings bearer / sk- / akid
        # (case-insensitive), design contract §4.3.
        self.assertEqual(secret_scan.check_credential_env_name("PROVIDER_SK-ABCD"), ["$"])
        self.assertEqual(secret_scan.check_credential_env_name("AKIDLTAI_SECRET"), ["$"])

    def test_default_config_files_pass_the_gate(self):
        configs_directory = ROOT / "configs"
        for name in ("inference.json", "harness_contract.v1.json"):
            with self.subTest(file=name):
                self.assertEqual(
                    secret_scan.scan_persisted_file(configs_directory / name), []
                )


class CliPreflightErrorTests(unittest.TestCase):
    def test_preflight_without_credentials_exits_with_structured_error(self):
        from financial_agent_reliability.harness.cli import main

        buffer = io.StringIO()
        env = {"PATH": "/usr/bin"}
        with patch("financial_agent_reliability.harness.cli.os.environ", env):
            with redirect_stdout(buffer):
                exit_code = main(
                    ["preflight", "--output", "/tmp/should-not-be-written.json"]
                )
        self.assertEqual(exit_code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "config_error")
        self.assertIn("BENCH_BAILIAN_API_KEY", payload["error"])
        self.assertFalse(pathlib.Path("/tmp/should-not-be-written.json").exists())


if __name__ == "__main__":
    unittest.main()
