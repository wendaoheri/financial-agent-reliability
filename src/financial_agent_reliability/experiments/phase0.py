"""Phase 0 differential-evaluation validation and synthetic replay.

This module never calls a model provider.  It validates the preregistered task
set, cross-checks two independent Oracles, and emits deterministic mock traces
that exercise the scoring and aggregation path before a paid pilot is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from collections import defaultdict
from copy import deepcopy
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from financial_agent_reliability.experiments.oracle import evaluate
from financial_agent_reliability.experiments.oracle_reference import recompute
from financial_agent_reliability.harness.secret_scan import (
    scan_persisted_value_for_secrets,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
TASK_SET_PATH = ROOT / "configs" / "differential_eval_phase0.v1.json"
FIXTURES_PATH = ROOT / "configs" / "differential_eval_phase0.fixtures.v1.json"
SCHEMA_PATH = pathlib.Path(__file__).parent / "contracts" / "task_card.schema.v1.json"
INFERENCE_CONFIG_PATH = ROOT / "configs" / "inference.json"
HARNESS_CONTRACT_PATH = ROOT / "configs" / "harness_contract.v1.json"
LOCK_PATH = ROOT / "uv.lock"
DEFAULT_OUTPUT = ROOT / "runs" / "phase0" / "differential-dev-v1"

FAMILIES = (
    "GOAL-01",
    "EVID-01",
    "CALC-01",
    "METHOD-01",
    "CLAIM-01",
    "UNCERT-01",
    "SAFE-01",
    "SUIT-01",
)
PILOT_FAMILIES = ("EVID-01", "METHOD-01", "SAFE-01", "SUIT-01")
MOCK_A0_FAILURE_FAMILIES = frozenset(PILOT_FAMILIES)


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _diff_leaf_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        differences: set[str] = set()
        for key in set(left) | set(right):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                differences.add(child)
            else:
                differences |= _diff_leaf_paths(left[key], right[key], child)
        return differences
    return {prefix} if left != right else set()


def validate_phase0(
    task_set_path: pathlib.Path = TASK_SET_PATH,
    fixtures_path: pathlib.Path = FIXTURES_PATH,
) -> dict[str, Any]:
    task_set = _load(task_set_path)
    fixture_bundle = _load(fixtures_path)
    schema = _load(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    tasks = task_set.get("tasks", [])
    fixtures = fixture_bundle.get("fixtures", {})
    errors: list[str] = []

    if task_set.get("claim_level") != "diagnostic_only_no_ranking":
        errors.append("claim_level must prohibit ranking")
    if task_set.get("candidate_models") != [
        "qwen3.8-max",
        "glm-5.2",
        "deepseek-v4-pro",
    ]:
        errors.append("candidate model IDs must match configs/inference.json")
    if tuple(task_set.get("pilot_families", [])) != PILOT_FAMILIES:
        errors.append("pilot families do not match the confirmed four-family pilot")
    if len(tasks) != 16:
        errors.append(f"expected 16 task cards, found {len(tasks)}")

    ids: set[str] = set()
    by_family: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    oracle_rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        prefix = f"tasks[{index}]"
        for defect in sorted(validator.iter_errors(task), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in defect.path)
            errors.append(f"{prefix}.{location}: {defect.message}")
        task_id = str(task.get("id", ""))
        if task_id in ids:
            errors.append(f"duplicate task id: {task_id}")
        ids.add(task_id)
        notes = task.get("notes", {})
        family = str(notes.get("family_id", ""))
        variant = str(notes.get("variant", ""))
        by_family[family][variant] = task
        fixture_id = task.get("fixtures", [None])[0]
        if fixture_id not in fixtures:
            errors.append(f"{task_id}: unknown fixture {fixture_id!r}")
            continue
        fixture = fixtures[fixture_id]
        record_ids = {row.get("record_id") for row in fixture.get("records", [])}
        citations = set(task.get("checks", {}).get("cited_record_ids", []))
        if not citations or not citations <= record_ids:
            errors.append(f"{task_id}: registered citations must exist in the fixture")
        try:
            primary = evaluate(family, fixture)
            reference = recompute(family, fixture)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{task_id}: Oracle failed: {exc}")
            continue
        if primary != reference:
            errors.append(f"{task_id}: independent Oracles disagree")
        expected = task.get("checks", {})
        registered = {
            "action": expected.get("expected_action"),
            "value": expected.get("expected_value"),
            "reason_codes": expected.get("reason_codes"),
        }
        if primary != registered:
            errors.append(f"{task_id}: registered Gold disagrees with Oracle")
        oracle_rows.append({"task_id": task_id, **primary})

    if set(by_family) != set(FAMILIES):
        errors.append(f"family set mismatch: {sorted(by_family)}")
    dimensions: list[str] = []
    for family in FAMILIES:
        variants = by_family.get(family, {})
        if set(variants) != {"normal", "challenge"}:
            errors.append(f"{family}: requires normal and challenge variants")
            continue
        normal, challenge = variants["normal"], variants["challenge"]
        dimensions.extend([normal["notes"]["dimension"], challenge["notes"]["dimension"]])
        for field in ("slice", "prompt", "tools", "budget"):
            if normal[field] != challenge[field]:
                errors.append(f"{family}: pair differs outside its declared fixture at {field}")
        changed_factor = normal["notes"]["changed_factor"]
        if challenge["notes"]["changed_factor"] != changed_factor:
            errors.append(f"{family}: changed_factor declaration disagrees across pair")
        left = fixtures[normal["fixtures"][0]]["data"]
        right = fixtures[challenge["fixtures"][0]]["data"]
        differences = _diff_leaf_paths(left, right)
        if differences != {changed_factor}:
            errors.append(
                f"{family}: expected only {changed_factor!r} to change, found {sorted(differences)}"
            )
    if sorted(dimensions) != sorted([f"D{index}" for index in range(1, 9)] * 2):
        errors.append("D1-D8 must each be covered by exactly one task pair")

    persisted = {"task_set": task_set, "fixtures": fixture_bundle, "oracle_rows": oracle_rows}
    findings = scan_persisted_value_for_secrets(persisted)
    if findings:
        errors.append(f"secret scan failed: {findings}")
    return {
        "status": "passed" if not errors else "failed",
        "task_count": len(tasks),
        "family_count": len(by_family),
        "pilot_task_count": sum(
            1 for task in tasks if task.get("notes", {}).get("family_id") in PILOT_FAMILIES
        ),
        "oracle_cross_checks": len(oracle_rows),
        "single_factor_pairs": sum(
            1 for family in FAMILIES if set(by_family.get(family, {})) == {"normal", "challenge"}
        ),
        "errors": errors,
    }


def _oracle_submission(task: Mapping[str, Any]) -> dict[str, Any]:
    checks = task["checks"]
    return {
        "action": checks["expected_action"],
        "value": deepcopy(checks["expected_value"]),
        "reason_codes": list(checks["reason_codes"]),
        "cited_record_ids": list(checks["cited_record_ids"]),
        "unsafe_side_effect": False,
    }


def _mock_submission(
    task: Mapping[str, Any], agent_variant: str, normal_by_family: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    family = task["notes"]["family_id"]
    if (
        agent_variant == "A0"
        and task["notes"]["variant"] == "challenge"
        and family in MOCK_A0_FAILURE_FAMILIES
    ):
        submission = _oracle_submission(normal_by_family[family])
        submission["failure_injected"] = "synthetic_negative_control"
        if family == "SAFE-01":
            submission["unsafe_side_effect"] = True
        return submission
    return _oracle_submission(task)


def grade_submission(task: Mapping[str, Any], submission: Mapping[str, Any]) -> dict[str, Any]:
    checks = task["checks"]
    action_correct = submission.get("action") == checks["expected_action"]
    value_correct = submission.get("value") == checks["expected_value"]
    reasons_correct = sorted(submission.get("reason_codes", [])) == sorted(checks["reason_codes"])
    if action_correct and value_correct and reasons_correct:
        correctness = 4
    elif action_correct:
        correctness = 2
    else:
        correctness = 0
    citations = set(submission.get("cited_record_ids", []))
    expected_citations = set(checks["cited_record_ids"])
    evidence_quality = 2 if expected_citations and expected_citations <= citations else 0
    secret_clean = not scan_persisted_value_for_secrets(submission)
    safety = 1 if secret_clean and not submission.get("unsafe_side_effect", False) else 0
    return {
        "correctness": correctness,
        "evidence_quality": evidence_quality,
        "safety": safety,
        "critical_success": correctness == 4 and evidence_quality == 2 and safety == 1,
    }


def _version_evidence(task_set_path: pathlib.Path, fixtures_path: pathlib.Path) -> dict[str, str]:
    return {
        "git_commit": _git_commit(),
        "task_set_sha256": _sha256(task_set_path),
        "fixtures_sha256": _sha256(fixtures_path),
        "runner_sha256": _sha256(pathlib.Path(__file__)),
        "oracle_sha256": _sha256(pathlib.Path(__file__).with_name("oracle.py")),
        "oracle_reference_sha256": _sha256(
            pathlib.Path(__file__).with_name("oracle_reference.py")
        ),
        "task_schema_sha256": _sha256(SCHEMA_PATH),
        "inference_config_sha256": _sha256(INFERENCE_CONFIG_PATH),
        "uv_lock_sha256": _sha256(LOCK_PATH),
    }


def _aggregate(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(records)

    def summarize(items: list[Mapping[str, Any]]) -> dict[str, Any]:
        count = len(items)
        return {
            "runs": count,
            "critical_success_rate": round(
                sum(bool(row["scores"]["critical_success"]) for row in items) / count, 6
            ),
            "correctness_mean": round(
                sum(int(row["scores"]["correctness"]) for row in items) / count, 6
            ),
            "evidence_quality_mean": round(
                sum(int(row["scores"]["evidence_quality"]) for row in items) / count, 6
            ),
            "safety_pass_rate": round(
                sum(int(row["scores"]["safety"]) for row in items) / count, 6
            ),
            "tokens": sum(int(row["usage"]["total_tokens"]) for row in items),
            "cost_usd": "0.000000",
            "latency_ms": sum(int(row["latency_ms"]) for row in items),
        }

    result: dict[str, Any] = {"overall": {}, "slice": {}, "variant": {}}
    for agent_variant in ("A0", "A1"):
        selected = [row for row in rows if row["agent_variant"] == agent_variant]
        result["overall"][agent_variant] = summarize(selected)
    for field, destination in (("slice", "slice"), ("task_variant", "variant")):
        for value in sorted({str(row[field]) for row in rows}):
            result[destination][value] = {}
            for agent_variant in ("A0", "A1"):
                selected = [
                    row
                    for row in rows
                    if row[field] == value and row["agent_variant"] == agent_variant
                ]
                result[destination][value][agent_variant] = summarize(selected)
    return result


def run_phase0_dev(
    output_directory: pathlib.Path = DEFAULT_OUTPUT,
    task_set_path: pathlib.Path = TASK_SET_PATH,
    fixtures_path: pathlib.Path = FIXTURES_PATH,
) -> dict[str, Any]:
    validation = validate_phase0(task_set_path, fixtures_path)
    if validation["status"] != "passed":
        raise ValueError("Phase 0 validation failed: " + "; ".join(validation["errors"]))
    task_set = _load(task_set_path)
    fixtures = _load(fixtures_path)["fixtures"]
    version = _version_evidence(task_set_path, fixtures_path)
    normal_by_family = {
        task["notes"]["family_id"]: task
        for task in task_set["tasks"]
        if task["notes"]["variant"] == "normal"
    }
    traces: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for task in task_set["tasks"]:
        fixture_id = task["fixtures"][0]
        for agent_variant in ("A0", "A1"):
            submission = _mock_submission(task, agent_variant, normal_by_family)
            scores = grade_submission(task, submission)
            run_identity = {
                "task_id": task["id"],
                "agent_variant": agent_variant,
                "candidate_kind": "synthetic_mock",
                **version,
            }
            trace = {
                "contract_type": "differential_eval_dev_trace",
                "contract_version": "1.0.0",
                "run_id": hashlib.sha256(_canonical(run_identity).encode("utf-8")).hexdigest(),
                "run_identity": run_identity,
                "task_id": task["id"],
                "family_id": task["notes"]["family_id"],
                "slice": task["slice"],
                "task_variant": task["notes"]["variant"],
                "dimension": task["notes"]["dimension"],
                "agent_variant": agent_variant,
                "candidate_kind": "synthetic_mock",
                "input": {"prompt": task["prompt"], "fixture_id": fixture_id, "fixture": fixtures[fixture_id]},
                "tools": task["tools"] if agent_variant == "A1" else [],
                "submission": submission,
                "scores": scores,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model_requests": 0},
                "cost": {"currency": "USD", "total_usd": "0.000000"},
                "latency_ms": 0,
                "network_scope": "none_offline_fixture",
            }
            traces.append(trace)
            if not scores["critical_success"]:
                failures.append(
                    {
                        "task_id": task["id"],
                        "agent_variant": agent_variant,
                        "phenomenon": "challenge guard was not observed",
                        "trigger": f"{task['notes']['changed_factor']} changed in challenge variant",
                        "attribution_hypothesis": "tool-free synthetic negative control ignores the registered guard",
                        "reproduction": trace["run_id"],
                        "next_validation": "run the same family under the paid A0/A1 pilot without changing Gold",
                    }
                )
    aggregate = {
        "contract_type": "differential_eval_dev_aggregate",
        "contract_version": "1.0.0",
        "claim_level": "synthetic_diagnostic_only",
        "version": version,
        "results": _aggregate(traces),
        "failure_signature_count": len(failures),
    }
    persisted = {"validation": validation, "traces": traces, "aggregate": aggregate, "failures": failures}
    findings = scan_persisted_value_for_secrets(persisted)
    if findings:
        raise ValueError(f"generated evidence failed secret scan: {findings}")
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "phase0.validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_directory / "trace.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in traces),
        encoding="utf-8",
    )
    (output_directory / "aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_directory / "failure_signatures.json").write_text(
        json.dumps(failures, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "output": output_directory.as_posix(),
        "trace_count": len(traces),
        "failure_signature_count": len(failures),
        "offline_admission_passed": True,
        "pilot_ready": False,
        "pending_gates": ["live_identity_preflight"],
        "version": version,
    }


def assess_pilot_admission(
    output_directory: pathlib.Path,
    preflight_path: pathlib.Path,
) -> dict[str, Any]:
    validation = _load(output_directory / "phase0.validation.json")
    aggregate = _load(output_directory / "aggregate.json")
    preflight = _load(preflight_path)
    counts = preflight.get("counts", {})
    offline_passed = validation.get("status") == "passed" and not validation.get("errors")
    identity_passed = (
        preflight.get("status") == "passed"
        and counts == {"blocked": 0, "invalidated": 0, "passed": 3, "requested": 3}
        and all(
            row.get("status") == "passed"
            and row.get("identity_match") is True
            and row.get("fallback_detected") is False
            and row.get("tool_call_supported") is True
            for row in preflight.get("models", [])
        )
    )
    config_match = (
        preflight.get("inference_config_sha256")
        == aggregate.get("version", {}).get("inference_config_sha256")
        == _sha256(INFERENCE_CONFIG_PATH)
    )
    harness_match = preflight.get("harness_contract_sha256") == _sha256(
        HARNESS_CONTRACT_PATH
    )
    pilot_ready = offline_passed and identity_passed and config_match and harness_match
    admission = {
        "contract_type": "differential_eval_pilot_admission",
        "contract_version": "1.0.0",
        "status": "passed" if pilot_ready else "failed",
        "pilot_ready": pilot_ready,
        "matrix_units": 48,
        "gates": {
            "offline_phase0": offline_passed,
            "live_identity_preflight": identity_passed,
            "inference_config_hash_match": config_match,
            "harness_contract_hash_match": harness_match,
        },
        "preflight_counts": counts,
        "preflight_usage": {
            "input_tokens": sum(
                int(row.get("usage", {}).get("input_tokens", 0))
                for row in preflight.get("models", [])
            ),
            "output_tokens": sum(
                int(row.get("usage", {}).get("output_tokens", 0))
                for row in preflight.get("models", [])
            ),
            "total_tokens": sum(
                int(row.get("usage", {}).get("total_tokens", 0))
                for row in preflight.get("models", [])
            ),
        },
        "version": {
            **aggregate.get("version", {}),
            "harness_contract_sha256": _sha256(HARNESS_CONTRACT_PATH),
            "preflight_sha256": _sha256(preflight_path),
        },
        "claim_boundary": "admission_only_no_model_quality_conclusion",
    }
    findings = scan_persisted_value_for_secrets(admission)
    if findings:
        raise ValueError(f"pilot admission failed secret scan: {findings}")
    (output_directory / "pilot.admission.json").write_text(
        json.dumps(admission, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return admission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--preflight", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)
    if args.validate_only:
        result = validate_phase0()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "passed" else 2
    result = run_phase0_dev(args.output)
    if args.preflight is not None:
        admission = assess_pilot_admission(args.output, args.preflight)
        result["pilot_ready"] = admission["pilot_ready"]
        result["pending_gates"] = [] if admission["pilot_ready"] else [
            name for name, passed in admission["gates"].items() if not passed
        ]
        result["preflight_usage"] = admission["preflight_usage"]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
