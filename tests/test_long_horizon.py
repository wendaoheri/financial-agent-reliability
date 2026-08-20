from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.adapters.core import AdapterResult, CandidateRequest
from financial_agent_reliability.long_horizon import (
    InjectedCrash,
    SoakHardStop,
    aggregate_soak,
    run_long_horizon,
)
from financial_agent_reliability.models import Candidate, load_tasks

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "dev" / "tasks.jsonl"


class FauxLongAdapter:
    name = "pi-agent-live"
    version = "faux"

    def __init__(
        self,
        *,
        fail_at: int | None = None,
        failure_code: str = "RATE_LIMITED",
        fallback_at: int | None = None,
        raise_at: int | None = None,
    ) -> None:
        self.calls = 0
        self.fail_at = fail_at
        self.failure_code = failure_code
        self.fallback_at = fallback_at
        self.raise_at = raise_at

    def execute(self, request: CandidateRequest, candidate: Candidate, tools):
        self.calls += 1
        if self.calls == self.raise_at:
            raise TimeoutError("faux interrupted stream")
        tools.invoke(request.tools[0])
        response_model = "fallback" if self.calls == self.fallback_at else candidate.model
        error = (
            {"code": self.failure_code, "message": "faux provider failure", "retryable": True}
            if self.calls == self.fail_at
            else None
        )
        return AdapterResult(
            output=None if error else {"status": "answer", "value": 35.0, "reason_codes": []},
            error=error,
            latency_ms=1,
            input_tokens=10,
            output_tokens=2,
            provider_identity={
                "requested_model": candidate.model,
                "response_model": response_model,
                "exact_match": response_model == candidate.model,
                "endpoint_id": "faux",
            },
            provider_observability={"generation_profile": {"effective_parameters": {}}},
            agent_events=(
                {"type": "message_end", "stop_reason": "toolUse"},
                {"type": "message_end", "stop_reason": "stop"},
            ),
        )


def _candidate() -> Candidate:
    return Candidate(
        id="fixture__pi-agent-0.73.1",
        model="fixture-model",
        agent="pi-agent-0.73.1",
        adapter="pi-agent-live",
        config={"max_provider_turns": 2},
        source_path=ROOT / "configs" / "pi-bailian-calibration-v3.json",
    )


def _task():
    return next(
        task
        for task in load_tasks(TASKS)
        if task["task_id"] == "portfolio-permission-boundary::analyze_weight"
    )


class LongHorizonTests(unittest.TestCase):
    def test_persisted_steps_keep_only_supplied_experiment_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            versions = {"config_sha256": "0" * 64}
            run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=root,
                experiment_id="coordinate-boundary",
                versions=versions,
                steps=1,
                adapter=FauxLongAdapter(),
            )
            step = (root / _candidate().id / "steps" / "step-0001.json").read_text(encoding="utf-8")
            self.assertEqual(json.loads(step)["versions"], versions)

    def test_fifty_steps_produce_one_hundred_turns_and_fifty_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FauxLongAdapter()
            summary = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=pathlib.Path(temporary),
                experiment_id="offline-soak",
                versions={"config_sha256": "a" * 64},
                steps=50,
                adapter=adapter,
            )
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["provider_turns"], 100)
            self.assertEqual(summary["tool_calls"], 50)
            self.assertEqual(adapter.calls, 50)
            trace = (
                (pathlib.Path(temporary) / _candidate().id / "steps.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.assertEqual(len(trace), 50)

    def test_resume_after_durable_crash_does_not_repeat_committed_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary)
            first = FauxLongAdapter()
            with self.assertRaises(InjectedCrash):
                run_long_horizon(
                    _task(),
                    _candidate(),
                    repository_root=ROOT,
                    output_directory=output,
                    experiment_id="resume-soak",
                    versions={"config_sha256": "b" * 64},
                    steps=50,
                    adapter=first,
                    crash_after_step=3,
                )
            second = FauxLongAdapter()
            summary = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=output,
                experiment_id="resume-soak",
                versions={"config_sha256": "b" * 64},
                steps=50,
                adapter=second,
            )
            self.assertEqual(summary["status"], "recovered")
            self.assertEqual(first.calls + second.calls, 50)
            self.assertEqual(len(summary["completed_step_ids"]), 50)

    def test_resume_rejects_version_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary)
            run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=output,
                experiment_id="drift",
                versions={"config_sha256": "c" * 64},
                steps=2,
                adapter=FauxLongAdapter(),
            )
            with self.assertRaisesRegex(SoakHardStop, "fingerprint drift"):
                run_long_horizon(
                    _task(),
                    _candidate(),
                    repository_root=ROOT,
                    output_directory=output,
                    experiment_id="drift",
                    versions={"config_sha256": "d" * 64},
                    steps=2,
                    adapter=FauxLongAdapter(),
                )

    def test_provider_failure_is_incomplete_and_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FauxLongAdapter(fail_at=4)
            summary = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=pathlib.Path(temporary),
                experiment_id="429",
                versions={"config_sha256": "e" * 64},
                steps=10,
                adapter=adapter,
            )
            report = aggregate_soak([summary])
            self.assertEqual(summary["status"], "incomplete")
            self.assertFalse(summary["eligible_for_completed_aggregation"])
            self.assertEqual(report["completed_aggregation"]["runs"], 0)
            resumed_adapter = FauxLongAdapter()
            repeated = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=pathlib.Path(temporary),
                experiment_id="429",
                versions={"config_sha256": "e" * 64},
                steps=10,
                adapter=resumed_adapter,
            )
            self.assertEqual(repeated["status"], "incomplete")
            self.assertEqual(resumed_adapter.calls, 0)

    def test_provider_fault_matrix_has_explicit_incomplete_terminal_state(self):
        for code in (
            "RATE_LIMITED",
            "PROVIDER_UNAVAILABLE",
            "TIMEOUT",
            "MALFORMED_STREAM",
            "DUPLICATE_CHUNK",
            "TOOL_ERROR",
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                summary = run_long_horizon(
                    _task(),
                    _candidate(),
                    repository_root=ROOT,
                    output_directory=pathlib.Path(temporary),
                    experiment_id=code.lower(),
                    versions={"config_sha256": "1" * 64},
                    steps=10,
                    adapter=FauxLongAdapter(fail_at=3, failure_code=code),
                )
                self.assertEqual(summary["status"], "incomplete")
                self.assertEqual(summary["terminal_error"]["code"], code)
                self.assertEqual(summary["completed_steps"], 3)

    def test_adapter_exception_is_sanitized_and_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FauxLongAdapter(raise_at=2)
            summary = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=pathlib.Path(temporary),
                experiment_id="exception",
                versions={"config_sha256": "2" * 64},
                steps=10,
                adapter=adapter,
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertEqual(summary["terminal_error"]["code"], "ADAPTER_EXCEPTION")
            self.assertEqual(summary["terminal_error"]["message"], "TimeoutError")
            self.assertEqual(adapter.calls, 2)

    def test_cancel_file_yields_cancelled_terminal_state_without_calling_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            cancel = root / "cancel"
            cancel.touch()
            adapter = FauxLongAdapter()
            summary = run_long_horizon(
                _task(),
                _candidate(),
                repository_root=ROOT,
                output_directory=root / "out",
                experiment_id="cancel",
                versions={"config_sha256": "3" * 64},
                steps=10,
                cancel_file=cancel,
                adapter=adapter,
            )
            self.assertEqual(summary["status"], "cancelled")
            self.assertFalse(summary["eligible_for_completed_aggregation"])
            self.assertEqual(adapter.calls, 0)

    def test_identity_drift_is_a_global_hard_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(SoakHardStop, "identity mismatch"):
                run_long_horizon(
                    _task(),
                    _candidate(),
                    repository_root=ROOT,
                    output_directory=pathlib.Path(temporary),
                    experiment_id="identity",
                    versions={"config_sha256": "f" * 64},
                    steps=10,
                    adapter=FauxLongAdapter(fallback_at=5),
                )


if __name__ == "__main__":
    unittest.main()
