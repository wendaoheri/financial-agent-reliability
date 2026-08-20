from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.adapters.http import _parse_sse
from financial_agent_reliability.experiments.phase0 import (
    FIXTURES_PATH,
    PILOT_CONFIG_PATH,
    TASK_SET_PATH,
)
from financial_agent_reliability.experiments.phase1 import (
    HARNESS_V2_PATH,
    PilotGateError,
    _parse_submission,
    run_pilot,
    validate_pilot_gate,
)
from financial_agent_reliability.experiments.phase1_diagnosis import diagnose

TASKS = {
    task["id"]: task for task in json.loads(TASK_SET_PATH.read_text(encoding="utf-8"))["tasks"]
}


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_admission(directory: pathlib.Path) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    admission = {
        "status": "passed",
        "pilot_ready": True,
        "version": {
            "task_set_sha256": _sha256(TASK_SET_PATH),
            "fixtures_sha256": _sha256(FIXTURES_PATH),
            "pilot_config_sha256": _sha256(PILOT_CONFIG_PATH),
            "harness_contract_sha256": _sha256(HARNESS_V2_PATH),
        },
    }
    (directory / "pilot.admission.json").write_text(json.dumps(admission), encoding="utf-8")
    return directory


class _PerfectTransport:
    calls = 0

    def __init__(self, _settings, **_kwargs):
        pass

    def __call__(self, request):
        type(self).calls += 1
        task_id = next(
            line.split(": ", 1)[1]
            for message in request["messages"]
            if message["role"] == "user"
            for line in message["content"].splitlines()
            if line.startswith("TASK_ID: ")
        )
        task = TASKS[task_id]
        if request["tools"] and request["messages"][-1]["role"] == "user":
            fixture_id = task["fixtures"][0]
            return {
                "model": request["model"],
                "output": "",
                "tool_calls": [
                    {
                        "id": "call_case",
                        "type": "function",
                        "function": {
                            "name": "read_frozen_case",
                            "arguments": json.dumps({"case_id": fixture_id}),
                        },
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "accepted_parameters": list(request["parameters"]),
                "fallback_detected": False,
            }
        checks = task["checks"]
        output = {
            "action": checks["expected_action"],
            "value": checks["expected_value"],
            "reason_codes": checks["reason_codes"],
            "cited_record_ids": checks["cited_record_ids"],
        }
        return {
            "model": request["model"],
            "output": json.dumps(output),
            "tool_calls": [],
            "usage": {"input_tokens": 20, "output_tokens": 8},
            "accepted_parameters": list(request["parameters"]),
            "fallback_detected": False,
        }


class DifferentialEvalPhase1Tests(unittest.TestCase):
    def test_gate_requires_explicit_authorized_matrix(self):
        contract = json.loads(HARNESS_V2_PATH.read_text(encoding="utf-8"))
        contract["security"]["full_paid_matrix_runs_allowed"] = False
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            admission = _write_admission(root / "phase0")
            self.assertEqual(validate_pilot_gate(admission)["matrix_units"], 48)
            path = root / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(PilotGateError, "not authorized"):
                validate_pilot_gate(admission, harness_v2_path=path)

    def test_strict_submission_parser(self):
        value = _parse_submission(
            '{"action":"abstain","value":null,"reason_codes":[],"cited_record_ids":[]}'
        )
        self.assertEqual(value["action"], "abstain")
        with self.assertRaisesRegex(ValueError, "trailing"):
            _parse_submission(
                '{"action":"abstain","value":null,"reason_codes":[],"cited_record_ids":[]} note'
            )

    def test_sse_parser_reconstructs_tool_calls(self):
        chunks = [
            {
                "model": "qwen3.8-max",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_",
                                    "function": {"name": "read_", "arguments": '{"case'},
                                }
                            ]
                        }
                    }
                ],
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "1",
                                    "function": {"name": "frozen_case", "arguments": '_id":"x"}'},
                                }
                            ]
                        }
                    }
                ]
            },
        ]
        raw = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks).encode()
        parsed = _parse_sse(raw)
        self.assertTrue(parsed["tool_call_supported"])
        self.assertEqual(parsed["tool_calls"][0]["id"], "call_1")
        self.assertEqual(parsed["tool_calls"][0]["function"]["name"], "read_frozen_case")
        self.assertEqual(
            json.loads(parsed["tool_calls"][0]["function"]["arguments"]),
            {"case_id": "x"},
        )

    def test_fake_provider_executes_exact_48_unit_matrix(self):
        _PerfectTransport.calls = 0
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            admission = _write_admission(root / "phase0")
            result = run_pilot(
                root / "phase1",
                phase0_output=admission,
                transport_factory=_PerfectTransport,
                env={"BENCH_BAILIAN_API_KEY": "test-only-placeholder"},
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["trace_count"], 48)
            self.assertEqual(result["failure_signature_count"], 0)
            self.assertEqual(_PerfectTransport.calls, 72)
            self.assertEqual(result["results"]["valid_runs"], 48)
            self.assertEqual(result["results"]["critical_success_rate"], 1.0)
            rows = [
                json.loads(line)
                for line in (root / "phase1" / "trace.jsonl").read_text().splitlines()
            ]
            self.assertEqual(sum(row["agent_variant"] == "A0" for row in rows), 24)
            self.assertEqual(sum(row["agent_variant"] == "A1" for row in rows), 24)
            self.assertTrue(all(not row["security"]["real_trading_permitted"] for row in rows))
            diagnosis = diagnose(root / "phase1")
            self.assertEqual(diagnosis["outcome"], "valid_exploratory_diagnostic_pilot")
            self.assertTrue(diagnosis["evidence"]["candidate_visible_contract_v2_complete"])


if __name__ == "__main__":
    unittest.main()
