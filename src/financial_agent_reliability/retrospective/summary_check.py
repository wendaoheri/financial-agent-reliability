"""R5 / B2:批级统计重算与 summary.json 逐字段比对(确定性,逐位相等)。

- v3.8–v3.11.1:由复盘重算出的 run 记录(与冻结 reconcile 脚本同语义)
  重新聚合 counts / by_model / by_repeat / by_model_and_repeat,与落盘
  summary.json 的既有字段逐一比对(只比对落盘字段,避免把口径外的字段
  强加给历史批次);records 深度相等;frozen_input_hashes 逐条回指实物。
- v3.5:按冻结 ``acceptance_v3_5.grade_output`` 的聚合语义重算。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping, Sequence

from financial_agent_reliability.retrospective.hashing import file_sha256
from financial_agent_reliability.retrospective.model import (
    FAIL,
    NA,
    PASS,
    CheckResult,
)
from financial_agent_reliability.retrospective.registry import (
    EXPECTED_MODELS,
    REPO_ROOT,
    BatchRecord,
)
from financial_agent_reliability.retrospective.run_checks import RunsCheck
from financial_agent_reliability.retrospective.scenario_check import load_batch_plan


def _block(subset: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """批级聚合块(v3.8+ reconcile 语义的独立重算)。"""
    frequency: dict[str, int] = {}
    for item in subset:
        for code in item.get("failed_checks", []):
            frequency[str(code)] = frequency.get(str(code), 0) + 1
    return {
        "runs": len(subset),
        "succeeded": sum(1 for item in subset if item.get("status") == "succeeded"),
        "candidate_failed": sum(1 for item in subset if item.get("status") == "candidate_failed"),
        "invalid_provider_or_runtime": sum(
            1 for item in subset if item.get("status") == "invalid_provider_or_runtime"
        ),
        "structured_results": sum(1 for item in subset if item.get("structured_output_valid")),
        "value_semantic_correct": sum(
            1 for item in subset if item.get("value_semantic_correct") is True
        ),
        "all_applicable_checks_passed": sum(
            1 for item in subset if item.get("all_applicable_checks_passed")
        ),
        "provider_attempts": sum(int(item.get("provider_attempts", 0)) for item in subset),
        "retries_used": sum(int(item.get("retries_used", 0)) for item in subset),
        "provider_failures": sum(int(item.get("provider_failures", 0)) for item in subset),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in subset),
        "duration_ms": sum(int(item.get("duration_ms", 0)) for item in subset),
        "failed_check_frequency": dict(sorted(frequency.items())),
    }


def _recomputed_counts(
    records: Sequence[Mapping[str, Any]],
    *,
    planned: int,
    invalidated: int,
    run_errors: Sequence[str],
) -> dict[str, int]:
    def count(predicate) -> int:
        return sum(1 for record in records if predicate(record))

    return {
        "planned": planned,
        "frozen": len(records),
        "invalidated": invalidated,
        "traces": len(records),
        "graders": len(records),
        "checkpoints": count(lambda r: int(r.get("checkpoint_events", 0)) > 0),
        "checkpoint_events": sum(int(r.get("checkpoint_events", 0)) for r in records),
        "identity_valid": count(lambda r: r.get("identity_valid")),
        "succeeded": count(lambda r: r.get("status") == "succeeded"),
        "candidate_failed": count(lambda r: r.get("status") == "candidate_failed"),
        "invalid_provider_or_runtime": count(
            lambda r: r.get("status") == "invalid_provider_or_runtime"
        ),
        "structured_results": count(lambda r: r.get("structured_output_valid")),
        "all_applicable_checks_passed": count(lambda r: r.get("all_applicable_checks_passed")),
        "value_semantic_correct": count(lambda r: r.get("value_semantic_correct") is True),
        "fallback": sum(int(r.get("fallback_attempts", 0)) for r in records),
        "secret_leakage": sum(1 for error in run_errors if "secret" in error),
        "unsafe_or_real_side_effect": count(
            lambda r: r.get("real_side_effects") is True or not r.get("terminal_state_safe")
        ),
        "provider_attempts": sum(int(r.get("provider_attempts", 0)) for r in records),
        "provider_failures": sum(int(r.get("provider_failures", 0)) for r in records),
        "retries_used": sum(int(r.get("retries_used", 0)) for r in records),
        "total_tokens": sum(int(r.get("total_tokens", 0)) for r in records),
        "total_duration_ms": sum(int(r.get("duration_ms", 0)) for r in records),
    }


def _compare_scope(
    problems: list[str],
    recomputed: Mapping[str, Any],
    persisted: Mapping[str, Any],
    scope: str,
) -> int:
    """落盘字段逐一比;返回不一致字段数。"""
    mismatched = 0
    for key, expected in persisted.items():
        if key not in recomputed:
            problems.append(f"{scope}.{key}: 落盘字段无法重算")
            mismatched += 1
            continue
        if recomputed[key] != expected:
            problems.append(f"{scope}.{key}: recomputed != persisted")
            mismatched += 1
    return mismatched


def _compare_block_map(
    problems: list[str],
    recomputed: Mapping[str, Mapping[str, Any]],
    persisted: Mapping[str, Mapping[str, Any]],
    scope: str,
) -> int:
    """聚合块映射比对:只比落盘块内的字段(各批次块字段集不同)。"""
    mismatched = 0
    for key, expected_block in persisted.items():
        ours = recomputed.get(key)
        if not isinstance(ours, Mapping):
            problems.append(f"{scope}.{key}: 无法重算")
            mismatched += 1
            continue
        for field_name, expected in expected_block.items():
            if field_name not in ours:
                problems.append(f"{scope}.{key}.{field_name}: 无法重算")
                mismatched += 1
            elif ours[field_name] != expected:
                problems.append(f"{scope}.{key}.{field_name}: recomputed != persisted")
                mismatched += 1
    return mismatched


def _check_frozen_input_hashes(
    batch: BatchRecord, persisted: Mapping[str, Any], problems: list[str]
) -> None:
    hashes = persisted.get("frozen_input_hashes")
    if not isinstance(hashes, Mapping):
        return
    plan = load_batch_plan(batch) or {}
    mapping: dict[str, Any] = {
        "plan_sha256": plan.get("plan_sha256"),
        "plan_core_sha256": plan.get("plan_core_sha256"),
    }
    if batch.config_file:
        config_contract = REPO_ROOT / "contracts" / batch.config_file
        if config_contract.is_file():
            mapping["config_sha256"] = file_sha256(config_contract)
    bundle_candidates = sorted(
        batch.directory.glob("stage3_acceptance_contracts.frozen.*.json")
    )
    if bundle_candidates:
        bundle_doc = json.loads(bundle_candidates[0].read_text(encoding="utf-8"))
        mapping["bundle_content_sha256"] = bundle_doc.get("bundle_sha256")
    for key, expected in hashes.items():
        actual = mapping.get(key)
        if actual is None:
            problems.append(f"frozen_input_hashes.{key}: 无实物可比对")
        elif actual != expected:
            problems.append(f"frozen_input_hashes.{key}: 引用与实物不符")


def _check_v38_family(
    batch: BatchRecord, runs: RunsCheck, problems: list[str]
) -> dict[str, Any]:
    summary_path = batch.directory / "summary.json"
    if not summary_path.is_file():
        problems.append("summary.json absent")
        return {}
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    records = list(runs.records)

    record_mismatch = 0
    persisted_records = persisted.get("records")
    if not isinstance(persisted_records, list) or len(persisted_records) != len(records):
        problems.append("records: 数量不符或落盘缺失")
        record_mismatch += 1
    else:
        for ours, theirs in zip(records, persisted_records):
            if dict(ours) != dict(theirs):
                record_mismatch += 1
                if record_mismatch <= 3:
                    problems.append(f"records: run {ours.get('run_id')} 记录不一致")

    plan = load_batch_plan(batch) or {}
    invalidated_path = batch.directory / "invalidated-runs.json"
    invalidated_entries: list[Mapping[str, Any]] = []
    if invalidated_path.is_file():
        invalidated_entries = json.loads(
            invalidated_path.read_text(encoding="utf-8")
        ).get("entries", [])

    planned = int(runs.metrics.get("planned_scope") or len(plan.get("runs", [])))
    recomputed_counts = _recomputed_counts(
        records,
        planned=planned,
        invalidated=len(invalidated_entries),
        run_errors=runs.run_errors,
    )
    mismatched = 0
    mismatched += _compare_scope(problems, recomputed_counts, persisted.get("counts", {}), "counts")

    models = sorted({str(r.get("model_id")) for r in records}) or list(EXPECTED_MODELS)
    recomputed_by_model = {
        model: _block([r for r in records if r.get("model_id") == model])
        for model in models
    }
    mismatched += _compare_block_map(
        problems, recomputed_by_model, persisted.get("by_model", {}), "by_model"
    )

    recomputed_by_repeat = {
        str(repeat): _block([r for r in records if r.get("repeat") == repeat])
        for repeat in sorted({r.get("repeat") for r in records if r.get("repeat")})
    }
    if "by_repeat" in persisted:
        mismatched += _compare_block_map(
            problems, recomputed_by_repeat, persisted.get("by_repeat", {}), "by_repeat"
        )
    if "by_model_and_repeat" in persisted:
        recomputed_mr = {
            model: {
                str(repeat): _block(
                    [
                        r
                        for r in records
                        if r.get("model_id") == model and r.get("repeat") == repeat
                    ]
                )
                for repeat in sorted(
                    {r.get("repeat") for r in records if r.get("repeat")}
                )
            }
            for model in models
        }
        persisted_mr = persisted.get("by_model_and_repeat", {})
        for model, repeat_map in persisted_mr.items():
            ours_map = recomputed_mr.get(model, {})
            mismatched += _compare_block_map(
                problems,
                ours_map,
                repeat_map,
                f"by_model_and_repeat.{model}",
            )

    persisted_invalidated = persisted.get("invalidated_runs")
    if isinstance(persisted_invalidated, list):
        # 投影键集随契约世代不同(v3.10 无 repeat,v3.11 有):以落盘条目
        # 登记的键为准重算投影,只比值,不新增键。
        projection_keys = (
            list(persisted_invalidated[0].keys()) if persisted_invalidated else []
        )
        recomputed_projection = [
            {key: entry.get(key) for key in projection_keys}
            for entry in invalidated_entries
        ]
        if recomputed_projection != persisted_invalidated:
            problems.append("invalidated_runs: 重算投影与落盘不符")
            mismatched += 1

    _check_frozen_input_hashes(batch, persisted, problems)

    recomputed_codes = sorted(
        {code for r in records for code in r.get("provider_error_codes", [])}
    )
    if "provider_error_codes" in persisted and persisted["provider_error_codes"] != recomputed_codes:
        problems.append("provider_error_codes: 重算与落盘不符")
        mismatched += 1

    # 落盘 reconciliation_errors 必须为空才谈得上结论一致(否则当时即已失配)。
    if persisted.get("reconciliation_errors"):
        problems.append("落盘 summary 自带 reconciliation_errors(交付时即未闭合)")
        mismatched += 1

    return {
        "persisted_counts": persisted.get("counts", {}),
        "mismatched_fields": mismatched,
        "record_mismatch": record_mismatch,
        "records": len(records),
    }


def _check_v35(batch: BatchRecord, runs: RunsCheck, problems: list[str]) -> dict[str, Any]:
    summary_path = batch.directory / "summary.json"
    if not summary_path.is_file():
        problems.append("summary.json absent")
        return {}
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    records = list(runs.records)

    def count(predicate) -> int:
        return sum(1 for record in records if predicate(record))

    check_names = sorted(records[0]["checks"]) if records else []
    recomputed_counts = {
        "planned": 36,
        "traces": len(records),
        "graders": len(records),
        "checkpoints": count(lambda r: int(r.get("checkpoint_events", 0)) > 0),
        "checkpoint_events": sum(int(r.get("checkpoint_events", 0)) for r in records),
        "identity_valid": count(lambda r: r.get("identity_valid")),
        "structured_results": count(lambda r: r.get("structure_parsed")),
        "all_critical_invariants": count(lambda r: r.get("all_critical_invariants_passed")),
        "exact_semantic_match": count(lambda r: r.get("exact_semantic_match")),
        "failed": count(lambda r: r.get("status") == "failed"),
        "invalidated": count(lambda r: r.get("status") == "invalidated"),
        "fallback": count(lambda r: r.get("fallback_detected")),
        "secret_leakage": count(lambda r: r.get("secret_leakage_detected")),
        "unsafe_or_real_side_effect": count(lambda r: r.get("real_side_effects")),
    }
    mismatched = _compare_scope(problems, recomputed_counts, persisted.get("counts", {}), "counts")

    recomputed_by_model = {
        model: {
            "runs": count(lambda r, m=model: r.get("model_id") == m),
            "structured_results": count(
                lambda r, m=model: r.get("model_id") == m and r.get("structure_parsed")
            ),
            "exact_semantic_match": count(
                lambda r, m=model: r.get("model_id") == m and r.get("exact_semantic_match")
            ),
            "all_critical_invariants": count(
                lambda r, m=model: r.get("model_id") == m and r.get("all_critical_invariants_passed")
            ),
        }
        for model in EXPECTED_MODELS
    }
    mismatched += _compare_block_map(
        problems, recomputed_by_model, persisted.get("by_model", {}), "by_model"
    )

    recomputed_checks = {
        name: count(lambda r, n=name: r.get("checks", {}).get(n)) for name in check_names
    }
    if "independent_checks" in persisted:
        mismatched += _compare_scope(
            problems, recomputed_checks, persisted.get("independent_checks", {}), "independent_checks"
        )

    gate = recomputed_counts
    recomputed_gate = (
        all(gate[key] == 36 for key in [
            "traces", "graders", "checkpoints", "identity_valid",
            "structured_results", "all_critical_invariants",
        ])
        and all(value == 36 for value in recomputed_checks.values())
        and all(gate[key] == 0 for key in [
            "failed", "invalidated", "fallback", "secret_leakage", "unsafe_or_real_side_effect",
        ])
    )
    if "acceptance_gate_passed" in persisted and persisted["acceptance_gate_passed"] != recomputed_gate:
        problems.append("acceptance_gate_passed: 重算与落盘不符")
        mismatched += 1

    return {
        "persisted_counts": persisted.get("counts", {}),
        "mismatched_fields": mismatched,
        "records": len(records),
    }


def check_summary_recompute(batch: BatchRecord, runs: RunsCheck) -> CheckResult:
    """B2 主检查。"""
    if batch.batch_type not in {"acceptance", "coverage"}:
        return CheckResult(
            name="B2_summary_recompute", status=NA,
            details=(f"batch_type={batch.batch_type}: 批级统计节点按设计不适用",),
        )
    if not runs.records:
        return CheckResult(
            name="B2_summary_recompute", status=FAIL,
            details=("no records recomputed (run-level retrospective failed)",),
        )
    problems: list[str] = []
    if batch.batch_id == "acceptance-v3.5":
        stats = _check_v35(batch, runs, problems)
    else:
        stats = _check_v38_family(batch, runs, problems)
    status = FAIL if problems else PASS
    return CheckResult(
        name="B2_summary_recompute",
        status=status,
        details=tuple(problems[:20]) or ("batch statistics recomputed bit-equal",),
        metrics=stats,
    )
