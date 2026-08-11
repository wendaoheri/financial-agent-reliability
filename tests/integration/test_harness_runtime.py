import json
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from graders.pipeline import GraderInputError, GraderPipeline
from harness.bundle import ImmutableBundle
from harness.checkpoint import CheckpointStore, CheckpointError
from harness.matrix import build_run_manifest
from harness.redaction import redact
from harness.runner import OfflineHarness
from harness.stage3 import freeze_preflight_evidence, run_live_preflights
from harness.smoke import (
    build_smoke_plan,
    correct_pi_identity_semantics,
    validate_smoke_plan,
)
from providers.bailian import BailianAdapter, BailianConfigError, BailianSettings
from providers.bailian_http import (
    BailianHTTPError,
    BailianHTTPTransport,
    build_chat_completions_payload,
)
from simulators.ledger import LedgerError, SimulatedLedger
from contracts.run_trace_validator import file_sha256
from contracts.run_trace_validator_v2 import validate_run_trace_v2 as validate_run_trace


ROOT = pathlib.Path(__file__).resolve().parents[2]


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
            ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro"),
        )

    def test_alias_or_missing_secret_is_rejected(self):
        env = {
            "BENCH_BAILIAN_API_KEY": "secret",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": "qwen-3.8-max,glm-5.2,deepseek-v4-pro",
        }
        with self.assertRaisesRegex(BailianConfigError, "exactly"):
            BailianSettings.from_env(env)
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
        with patch("providers.bailian_http.urlopen", return_value=Response()) as opened:
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
        with patch("providers.bailian_http.urlopen", side_effect=error):
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
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(settings.api_key, rendered)
        self.assertNotIn(settings.base_url, rendered)

    def test_blocked_preflights_freeze_reconciled_evidence_bundle(self):
        fixture = {
            "contract_type": "stage3_live_preflight",
            "contract_version": "1.0.0",
            "status": "blocked",
            "endpoint_id": "bailian_fixture",
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
            self.assertEqual(decision["planned_matrix_runs"], 810)


class ManifestAndRecoveryTests(unittest.TestCase):
    def _copy_matrix_inputs(self, destination: pathlib.Path) -> pathlib.Path:
        for relative in (
            "contracts",
            "preregistration",
            "catalog/public",
            "catalog/longbridge",
            "cases/public",
            "cases/longbridge",
            "snapshots/public",
            "snapshots/longbridge",
            "pipelines/longbridge",
            "oracles/longbridge",
        ):
            source = ROOT / relative
            target = destination / relative
            shutil.copytree(source, target)
        for relative in (
            "tests/test_public_cases_v2.py",
            "tests/test_longbridge_synthetic_v2.py",
        ):
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return destination

    def test_pi_agent_core_is_exactly_locked_with_frozen_integrity(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(
            package["dependencies"]["@mariozechner/pi-agent-core"], "0.73.1"
        )
        locked = lock["packages"]["node_modules/@mariozechner/pi-agent-core"]
        self.assertEqual(locked["version"], "0.73.1")
        self.assertEqual(
            locked["integrity"],
            "sha512-Y/KVOhuKSgRQgYBlwmRtO2gPkUcoavOSqGF9bpQIINvNZvc19k6Z1H3bFDTce3Vp5ApMmTsfLH3+tNvOg75fAQ==",
        )

    def test_manifest_has_810_unique_deterministically_randomized_rows(self):
        first = build_run_manifest(ROOT)
        second = build_run_manifest(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            json.loads((ROOT / "harness/run_manifest.v4.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(first["contract_version"], "4.0.0")
        self.assertEqual(len(first["runs"]), 810)
        self.assertEqual(len({row["run_id"] for row in first["runs"]}), 810)
        self.assertEqual(
            {
                variant: sum(row["variant_id"] == variant for row in first["runs"])
                for variant in {
                    "baseline",
                    "single_factor_stress",
                    "missing_or_anomalous_diagnostic",
                }
            },
            {
                "baseline": 270,
                "single_factor_stress": 270,
                "missing_or_anomalous_diagnostic": 270,
            },
        )
        self.assertNotIn("single_factor_control", {row["variant_id"] for row in first["runs"]})
        protocol_path = ROOT / "catalog/public/preregistration_variant_protocol.v2.json"
        self.assertEqual(first["variant_protocol"]["version"], "2.0.0")
        self.assertEqual(first["variant_protocol"]["sha256"], file_sha256(protocol_path))
        selected = first["selected_input_bundles"]
        self.assertEqual(
            selected["public_v2"]["contract_bundle_sha256"],
            "e3067d7a7cdb66694052e1a959a80120f7ccfbfa43b0525192b40acee942d62c",
        )
        self.assertEqual(
            selected["synthetic_workflow_v2"]["stage3_input_bundle_sha256"],
            "62511d582702c8019201c16f18e22a36bb0b8632d8c2ac39b3c9b8a8e49118e8",
        )
        self.assertEqual(
            selected["frozen_allocation"],
            {
                "families": 30,
                "cases": 90,
                "gold": 46,
                "silver": 44,
                "track_weights": {
                    "financial_knowledge_work": "50_percent",
                    "financial_tool_workflow": "50_percent",
                },
            },
        )
        previous = json.loads(
            (ROOT / "harness/run_manifest.v3.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            {row["run_id"] for row in first["runs"]}.isdisjoint(
                row["run_id"] for row in previous["runs"]
            )
        )
        self.assertEqual(first["config_sha256"], second["config_sha256"])
        self.assertNotEqual(
            [row["model_id"] for row in first["runs"][:3]],
            ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"],
        )

    def test_smoke_plan_is_frozen_balanced_and_bounded_to_36_runs(self):
        plan = build_smoke_plan(ROOT)
        self.assertEqual(plan, build_smoke_plan(ROOT))
        self.assertEqual(plan["contract_type"], "stage3_sequential_necessity_smoke_plan")
        self.assertEqual(plan["contract_version"], "1.1.0")
        self.assertEqual(plan["run_cap"], 36)
        self.assertFalse(plan["full_matrix_authorized"])
        self.assertEqual(len(plan["tasks"]), 12)
        self.assertEqual(len(plan["runs"]), 36)
        self.assertEqual(
            plan["allocation"],
            {
                "tracks": {"financial_knowledge_work": 6, "financial_tool_workflow": 6},
                "tiers": {"Gold": 6, "Silver": 6},
                "variants": {
                    "baseline": 3,
                    "single_factor_stress": 3,
                    "missing_or_anomalous_diagnostic": 6,
                },
                "models_per_task": 3,
            },
        )
        self.assertEqual(
            {row["model_id"] for row in plan["runs"]},
            {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"},
        )
        full = json.loads((ROOT / "harness/run_manifest.v4.json").read_text(encoding="utf-8"))
        full_rows = {row["run_id"]: row for row in full["runs"]}
        self.assertTrue(all(row == full_rows[row["run_id"]] for row in plan["runs"]))
        validate_smoke_plan(plan, ROOT)

    def test_smoke_plan_tampering_is_rejected(self):
        plan = build_smoke_plan(ROOT)
        plan["runs"][0]["seed"] += 1
        with self.assertRaisesRegex(ValueError, "frozen v4 run"):
            validate_smoke_plan(plan, ROOT)

    def test_pi_absent_response_model_correction_preserves_candidate_output(self):
        trace = {
            "status": "invalidated",
            "provider": {"requested_model_id": "qwen3.8-max", "response_model_id": "unavailable"},
            "attempts": [{"http_status": 200}],
            "preflight": {},
            "failure": {"type": "identity_mismatch"},
        }
        grader = {
            "status": "invalidated",
            "model_id": "qwen3.8-max",
            "identity_valid": False,
            "end_to_end_complete": False,
            "max_loss_level": "L4",
            "candidate_output_sha256": "a" * 64,
        }
        corrected_trace, corrected_grader = correct_pi_identity_semantics(trace, grader)
        self.assertEqual(corrected_trace["provider"]["response_model_id"], "qwen3.8-max")
        self.assertEqual(corrected_trace["status"], "succeeded")
        self.assertTrue(corrected_grader["identity_valid"])
        self.assertEqual(corrected_grader["candidate_output_sha256"], "a" * 64)

    def test_manifest_rejects_missing_variant_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            (root / "catalog/public/preregistration_variant_protocol.v2.json").unlink()
            with self.assertRaisesRegex(ValueError, "variant protocol v2 is required"):
                build_run_manifest(root)

    def test_manifest_rejects_old_variant_protocol_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            protocol_path = root / "catalog/public/preregistration_variant_protocol.v2.json"
            protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
            protocol["version"] = "1.0.0"
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required variant protocol version 2.0.0"):
                build_run_manifest(root)

    def test_manifest_rejects_legacy_control_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            protocol_path = root / "catalog/public/preregistration_variant_protocol.v2.json"
            protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
            protocol["canonical_execution_variants"][2]["execution_id"] = "single_factor_control"
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy variant id single_factor_control"):
                build_run_manifest(root)

    def test_manifest_rejects_revoked_public_v1_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            manifest_path = root / "catalog/public/v2/frozen_manifest.v2.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["contract_bundle_sha256"] = (
                "7a05f78739f6751778cac31cde031bf56721fa7429a68ce8aa6b1ff576de87a7"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "revoked public v1"):
                build_run_manifest(root)

    def test_manifest_rejects_isolated_longbridge_v1_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            policy_path = root / "catalog/longbridge/synthetic_v2/stage3_input_policy.v2.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["stage3_input_bundle_sha256"] = (
                "d862b41b9e03a8e6d478e3515c1ce5c8613994527bd6bdd577082222dcc37c77"
            )
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "isolated Longbridge v1"):
                build_run_manifest(root)

    def test_manifest_rejects_selected_input_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy_matrix_inputs(pathlib.Path(directory))
            case_path = root / "cases/public/v2/case_card.FKW-01.normal.json"
            case_path.write_text(
                case_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "input hash drift"):
                build_run_manifest(root)

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
            validated = validate_run_trace(first)
            self.assertEqual(validated["status"], "succeeded")
            self.assertEqual(validated["retries"], 1)
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
            self.assertEqual(validate_run_trace(second)["status"], "succeeded")


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
