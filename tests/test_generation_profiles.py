"""Offline contract tests for capability-aware generation profiles."""

from __future__ import annotations

import json
import pathlib
import unittest
from types import SimpleNamespace

from financial_agent_reliability.inference_config_v2 import load_inference_config_v2
from financial_agent_reliability.providers.bailian_http import _parse_sse
from financial_agent_reliability.providers.generation import (
    GenerationConfigError,
    resolve_generation,
)
from financial_agent_reliability.providers.protocols import (
    build_protocol_payload,
    normalize_stream_event,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
V2_CONFIG = ROOT / "examples" / "bench" / "bailian-token-plan-inference.v0.2.json"


def _provider(adapter: str, protocol: str, generation: dict | None = None):
    return SimpleNamespace(
        adapter=adapter,
        protocol=protocol,
        default_generation=generation or {},
    )


def _model(
    reasoning: str,
    controls: list[str],
    *,
    stream: str = "supported",
    generation: dict | None = None,
):
    return SimpleNamespace(
        capabilities={
            "stream": stream,
            "reasoning": reasoning,
            "reasoning_controls": controls,
            "reasoning_output": "hidden",
        },
        default_generation=generation or {},
    )


class GenerationProfileTests(unittest.TestCase):
    def test_v2_config_resolves_qwen_required_reasoning_and_stream(self):
        config = load_inference_config_v2(V2_CONFIG)
        self.assertEqual(config.schema_version, "2.0.0")
        provider = config.provider("bailian")
        model = config.models_for_provider("bailian")[0]
        resolved = resolve_generation(
            provider,
            model,
            profile=config.profile("benchmark_fast"),
            candidate={"seed": 7},
        )
        self.assertEqual(resolved.resolved["stream"], "on")
        self.assertEqual(resolved.resolved["reasoning"]["mode"], "on")
        self.assertEqual(resolved.effective_parameters["reasoning_effort"], "low")
        self.assertTrue(resolved.effective_parameters["stream"])
        self.assertEqual(resolved.sources["seed"], "candidate")
        self.assertNotIn("enable_thinking", resolved.effective_parameters)

    def test_required_and_unsupported_capabilities_fail_before_transport(self):
        provider = _provider("bailian", "openai_chat_completions")
        with self.assertRaisesRegex(GenerationConfigError, "requires"):
            resolve_generation(
                provider,
                _model("required", ["effort"]),
                candidate={"reasoning": {"mode": "off"}},
            )
        with self.assertRaisesRegex(GenerationConfigError, "unsupported"):
            resolve_generation(
                provider,
                _model("unsupported", []),
                candidate={"reasoning": {"mode": "on"}},
            )
        with self.assertRaisesRegex(GenerationConfigError, "stream=on"):
            resolve_generation(
                provider,
                _model("unsupported", [], stream="unsupported"),
                candidate={"stream": "on"},
            )

    def test_bailian_optional_reasoning_emits_explicit_enable_flag(self):
        resolved = resolve_generation(
            _provider("bailian", "openai_chat_completions"),
            _model("optional", ["enable_flag"]),
            candidate={"stream": "off", "reasoning": {"mode": "off"}},
        )
        self.assertFalse(resolved.effective_parameters["stream"])
        self.assertFalse(resolved.effective_parameters["enable_thinking"])

    def test_provider_specific_payload_mappings(self):
        anthropic = resolve_generation(
            _provider("anthropic", "anthropic_messages"),
            _model("optional", ["budget_tokens"]),
            candidate={
                "reasoning": {"mode": "on", "budget_tokens": 1000},
                "max_output_tokens": 500,
            },
        )
        self.assertEqual(
            anthropic.effective_parameters["thinking"],
            {"type": "enabled", "budget_tokens": 1000},
        )
        self.assertEqual(anthropic.effective_parameters["max_tokens"], 1500)

        gemini = resolve_generation(
            _provider("gemini", "gemini_generate_content"),
            _model("optional", ["budget_tokens"]),
            candidate={"reasoning": {"mode": "off"}},
        )
        self.assertEqual(
            gemini.effective_parameters["thinking_config"], {"thinking_budget": 0}
        )

        bigmodel = resolve_generation(
            _provider("bigmodel", "openai_chat_completions"),
            _model("optional", ["enable_flag"]),
            candidate={"reasoning": {"mode": "on"}},
        )
        self.assertEqual(bigmodel.effective_parameters["thinking"], {"type": "enabled"})

        openai = resolve_generation(
            _provider("openai", "openai_responses"),
            _model("optional", ["effort"]),
            candidate={"reasoning": {"mode": "on", "effort": "medium"}},
        )
        self.assertEqual(openai.effective_parameters["reasoning_effort"], "medium")

    def test_effort_and_budget_conflict_is_rejected(self):
        with self.assertRaisesRegex(GenerationConfigError, "mutually exclusive"):
            resolve_generation(
                _provider("bailian", "openai_chat_completions"),
                _model("required", ["effort", "budget_tokens"]),
                candidate={
                    "reasoning": {
                        "mode": "on",
                        "effort": "low",
                        "budget_tokens": 100,
                    }
                },
            )

    def test_protocol_codecs_keep_provider_wire_shapes_separate(self):
        messages = [
            {"role": "system", "content": "safe system"},
            {"role": "user", "content": "fixture"},
        ]
        anthropic = build_protocol_payload(
            "anthropic_messages",
            model="claude-fixture",
            messages=messages,
            parameters={
                "stream": True,
                "max_tokens": 1500,
                "thinking": {"type": "enabled", "budget_tokens": 1000},
            },
        )
        self.assertEqual(anthropic["system"], "safe system")
        self.assertEqual(anthropic["thinking"]["budget_tokens"], 1000)

        gemini = build_protocol_payload(
            "gemini_generate_content",
            model="gemini-fixture",
            messages=messages,
            parameters={
                "stream": True,
                "max_tokens": 512,
                "thinking_config": {"thinking_budget": 0},
            },
        )
        self.assertEqual(
            gemini["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0
        )
        self.assertEqual(gemini["contents"][0]["parts"][0]["text"], "fixture")

        anthropic_events = normalize_stream_event(
            "anthropic_messages",
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hidden"}},
        )
        gemini_events = normalize_stream_event(
            "gemini_generate_content",
            {"candidates": [{"content": {"parts": [{"thought": True, "text": "hidden"}, {"text": "answer"}]}}]},
        )
        self.assertEqual([event.kind for event in anthropic_events], ["reasoning_delta"])
        self.assertEqual(
            [event.kind for event in gemini_events],
            ["reasoning_delta", "content_delta"],
        )

    def test_sse_separates_reasoning_from_content_without_persisting_reasoning(self):
        chunks = [
            {
                "model": "fixture-model",
                "choices": [{"delta": {"reasoning_content": "private reasoning"}}],
            },
            {
                "model": "fixture-model",
                "choices": [{"delta": {"content": "final"}}],
            },
            {
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 5,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                }
            },
        ]
        raw = b"".join(
            f"data: {json.dumps(chunk)}\n\n".encode("utf-8") for chunk in chunks
        ) + b"data: [DONE]\n\n"
        parsed = _parse_sse(raw)
        self.assertEqual(parsed["output"], "final")
        self.assertEqual(parsed["reasoning_summary"]["characters"], 17)
        self.assertEqual(len(parsed["reasoning_summary"]["sha256"]), 64)
        self.assertNotIn("private reasoning", json.dumps(parsed))
        self.assertEqual(parsed["stream_metrics"]["mode"], "streaming")
        self.assertIsNotNone(parsed["stream_metrics"]["ttft_reasoning_ms"])
        self.assertIsNotNone(parsed["stream_metrics"]["ttft_content_ms"])


if __name__ == "__main__":
    unittest.main()
