"""Focused tests for the only live provider in the MVP."""

from __future__ import annotations

import json
import pathlib
import unittest
from types import SimpleNamespace

from financial_agent_reliability.adapters.generation import (
    GenerationConfigError,
    resolve_generation,
)
from financial_agent_reliability.adapters.http import _parse_sse
from financial_agent_reliability.config import load_run_config

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE_CONFIG = ROOT / "configs" / "plain-bailian-live.json"


def _provider(generation: dict | None = None):
    return SimpleNamespace(
        adapter="bailian",
        protocol="openai_chat_completions",
        default_generation=generation or {},
    )


def _model(reasoning: str, controls: list[str], *, stream: str = "supported"):
    return SimpleNamespace(
        capabilities={
            "stream": stream,
            "reasoning": reasoning,
            "reasoning_controls": controls,
        },
        default_generation={},
    )


class GenerationProfileTests(unittest.TestCase):
    def test_config_resolves_required_reasoning_and_stream(self):
        config = load_run_config(LIVE_CONFIG)
        self.assertEqual(config.schema_version, "1.0.0")
        resolved = resolve_generation(
            config.provider("bailian"),
            config.models_for_provider("bailian")[0],
            profile=config.profile("benchmark_fast"),
            candidate={"seed": 7},
        )
        self.assertEqual(resolved.resolved["stream"], "on")
        self.assertEqual(resolved.resolved["reasoning"]["mode"], "on")
        self.assertEqual(resolved.effective_parameters["reasoning_effort"], "low")
        self.assertTrue(resolved.effective_parameters["stream"])

    def test_invalid_capability_combinations_fail_before_transport(self):
        with self.assertRaisesRegex(GenerationConfigError, "requires"):
            resolve_generation(
                _provider(),
                _model("required", ["effort"]),
                candidate={"reasoning": {"mode": "off"}},
            )
        with self.assertRaisesRegex(GenerationConfigError, "unsupported"):
            resolve_generation(
                _provider(),
                _model("unsupported", []),
                candidate={"reasoning": {"mode": "on"}},
            )

    def test_optional_reasoning_emits_enable_flag(self):
        resolved = resolve_generation(
            _provider(),
            _model("optional", ["enable_flag"]),
            candidate={"stream": "off", "reasoning": {"mode": "off"}},
        )
        self.assertFalse(resolved.effective_parameters["stream"])
        self.assertFalse(resolved.effective_parameters["enable_thinking"])

    def test_sse_separates_reasoning_from_content(self):
        chunks = [
            {
                "model": "fixture-model",
                "choices": [{"delta": {"reasoning_content": "private reasoning"}}],
            },
            {
                "model": "fixture-model",
                "choices": [{"delta": {"content": "final"}}],
            },
            {"usage": {"prompt_tokens": 3, "completion_tokens": 5}},
        ]
        raw = (
            b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
            + b"data: [DONE]\n\n"
        )
        result = _parse_sse(raw)
        self.assertEqual(result["output"], "final")
        self.assertEqual(result["model"], "fixture-model")
        self.assertNotIn("private reasoning", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
