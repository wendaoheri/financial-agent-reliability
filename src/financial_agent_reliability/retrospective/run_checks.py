"""R3/R4/B1:逐运行轨迹校验、链锚回验与 grader 确定性重算。

- v3.8–v3.11.1 验收批次:**复用配套版本的冻结 reconcile 脚本**
  (``audit/reconcile_stage3_v3_X_execution.py``)的 ``reconcile_run`` /
  ``verify_frozen_inputs`` / ``verify_preflight`` / ``verify_authorization``。
  这些脚本是交付时的确定性对账实现,复盘复用它们保证记录语义与交付时
  完全一致;本工具只读调用,不写任何文件。
- v3.5 验收批次无 reconcile 脚本,按冻结的 ``acceptance_v3_5.grade_output``
  语义在本模块内重放(候选答案内嵌于 trace.result.structured_output)。
- 链锚回验(R4/A4)独立复核:run_identity 哈希 ↔ 批内 config/plan、
  ``result.candidate_output_sha256`` ↔ 候选文档、grader commitments 四哈希
  ↔ 落盘文档(均为 c14n 口径)。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import types
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from financial_agent_reliability.retrospective.hashing import (
    content_sha256,
    file_sha256,
)
from financial_agent_reliability.retrospective.registry import (
    REPO_ROOT,
    BatchRecord,
)
from financial_agent_reliability.retrospective.scenario_check import load_batch_plan

ZERO_SHA = "0" * 64


@dataclass(frozen=True)
class RunsCheck:
    """逐运行复盘的聚合输入(供 summary 重算与判定使用)。"""

    records: tuple[Mapping[str, Any], ...]
    run_errors: tuple[str, ...]
    frozen_input_errors: tuple[str, ...]
    preflight_errors: tuple[str, ...]
    authorization_errors: tuple[str, ...]
    invalidation_notes: tuple[str, ...]
    anchor_problems: tuple[str, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    frozen_input_resolved: tuple[str, ...] = ()  # PER-85-D6 relocation 放行留痕
    anchors_na: bool = False  # F4: 该契约世代无 commitments/链锚字段,链锚回验 N/A(非空转通过)


def _reclassify_frozen_input_errors(
    batch: BatchRecord, errors: Sequence[str]
) -> tuple[list[str], list[str]]:
    """把旧路径钉住 drift 按 relocation 放行清单解析(PER-85-D6)。

    冻结 reconcile 脚本按重构前路径校验工件;源码迁移后这些钉住由
    ``relocation.verify_frozen_pin`` 解析(内容逐字节一致 = relocated;
    机械改写放行 = refactor-change)。解析成功的条目降级为留痕,其余保留。
    """
    from financial_agent_reliability.relocation import verify_frozen_pin

    pins: dict[str, str] = {}
    bundle_paths = sorted(batch.directory.glob("stage3_acceptance_contracts.frozen.*.json"))
    canonical = REPO_ROOT / "contracts"
    for bundle_path in bundle_paths + sorted(
        canonical.glob("stage3_acceptance_contracts.frozen.*.json")
    ):
        try:
            bundle = _read_json(bundle_path)
        except (OSError, ValueError):
            continue
        for item in bundle.get("artifacts", []):
            pins.setdefault(str(item["path"]), str(item["sha256"]))

    kept: list[str] = []
    resolved: list[str] = []
    marker = "artifact drift:"
    for error in errors:
        # 兼容两种冻结脚本错误前缀:"artifact drift:<path>" 与
        # "v3.11 artifact drift:<path>"(coverage reconcile 的写法)。
        index = error.find(marker)
        if index != -1:
            pin_path = error[index + len(marker):]
            expected = pins.get(pin_path)
            if expected:
                ok, classification = verify_frozen_pin(REPO_ROOT, pin_path, expected)
                if ok:
                    resolved.append(f"{pin_path}:relocation={classification}")
                    continue
        kept.append(error)
    return kept, resolved


def load_reconcile_module(batch: BatchRecord) -> types.ModuleType | None:
    """按注册表加载冻结 reconcile 脚本(只读复用,不修改)。"""
    if not batch.reconcile_script:
        return None
    path = REPO_ROOT / batch.reconcile_script
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        f"retrospective_frozen_reconcile_{batch.batch_id.replace('-', '_').replace('.', '_')}",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _anchor_checks(
    batch_dir: pathlib.Path,
    row: Mapping[str, Any],
    task: Mapping[str, Any],
    plan: Mapping[str, Any],
    config_path: pathlib.Path | None,
) -> list[str]:
    """R4/A4:单运行链锚回验(全部为只读哈希比对)。"""
    problems: list[str] = []
    run_id = str(row["run_id"])
    trace_path = batch_dir / "traces" / f"{run_id}.json"
    if not trace_path.is_file():
        return [f"{run_id}: trace missing"]
    trace = _read_json(trace_path)

    identity = trace.get("run_identity", {})
    if config_path is not None and config_path.is_file():
        if identity.get("harness_config_sha256") != file_sha256(config_path):
            problems.append(f"{run_id}: run_identity.harness_config_sha256 anchor broken")
    plan_core = plan.get("plan_core_sha256")
    if isinstance(plan_core, str) and identity.get("plan_core_sha256") != plan_core:
        problems.append(f"{run_id}: run_identity.plan_core_sha256 anchor broken")
    if identity.get("seed") != row.get("seed"):
        problems.append(f"{run_id}: seed disagrees with plan row")

    grader_path = batch_dir / "graders" / f"{run_id}.json"
    grader = _read_json(grader_path) if grader_path.is_file() else None
    commitments = grader.get("commitments") if isinstance(grader, Mapping) else None

    candidate_path = batch_dir / "candidates" / f"{run_id}.json"
    if candidate_path.is_file():
        candidate = _read_json(candidate_path)
        result_sha = trace.get("result", {}).get("candidate_output_sha256")
        if candidate is None:
            # 失败候选约定:候选文件为 null,trace/grader 锚点同为 null。
            if result_sha is not None:
                problems.append(f"{run_id}: null candidate but trace anchor non-null")
            if isinstance(commitments, Mapping) and commitments.get("candidate_sha256") is not None:
                problems.append(f"{run_id}: null candidate but grader anchor non-null")
        else:
            candidate_hash = content_sha256(candidate)
            if result_sha != candidate_hash:
                problems.append(f"{run_id}: result.candidate_output_sha256 anchor broken")
            if isinstance(commitments, Mapping) and commitments.get("candidate_sha256") != candidate_hash:
                problems.append(f"{run_id}: grader commitment candidate_sha256 broken")
    if isinstance(commitments, Mapping):
        if commitments.get("trace_sha256") != content_sha256(trace):
            problems.append(f"{run_id}: grader commitment trace_sha256 broken")
        projection = _read_json(REPO_ROOT / str(task["projection_path"]))
        snapshot = _read_json(REPO_ROOT / str(task["snapshot_path"]))
        if commitments.get("projection_sha256") != content_sha256(projection):
            problems.append(f"{run_id}: grader commitment projection_sha256 broken")
        if commitments.get("snapshot_sha256") != content_sha256(snapshot):
            problems.append(f"{run_id}: grader commitment snapshot_sha256 broken")
    return problems


def _checkpoint_chain_events(path: pathlib.Path, run_id: str) -> tuple[int, list[str]]:
    """checkpoint 哈希链重放(v3.5 语义;高阶批次由 reconcile_run 承担)。"""
    errors: list[str] = []
    previous = ZERO_SHA
    count = 0
    if not path.is_file():
        return 0, [f"{run_id}: checkpoint missing"]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        stored = event.pop("event_sha256", None)
        if (
            event.get("run_id") != run_id
            or event.get("offset") != count
            or event.get("previous_event_sha256") != previous
            or content_sha256(event) != stored
        ):
            errors.append(f"{run_id}: checkpoint chain broken at offset {count}")
        previous = stored
        count += 1
    return count, errors


def _verify_v35_bundle_pins(batch: BatchRecord) -> tuple[str, ...]:
    """F2:v3.5 契约 bundle 钉住校验(此前无 reconcile 脚本,该校验空转)。

    v3.5 没有配套冻结 reconcile 脚本,``frozen_input_errors`` 曾恒为空元组。
    此处直接按 PER-85-D6 语义(``relocation.verify_frozen_pin``:原位一致 /
    迁移逐字节一致 / 机械改写放行清单均算通过)逐件校验批内冻结 bundle
    ``artifacts[]`` 的路径钉住;未通过者按 ``artifact drift:<path>`` 记录。
    """
    from financial_agent_reliability.relocation import verify_frozen_pin

    pins: dict[str, str] = {}
    bundle_paths = sorted(
        batch.directory.glob("stage3_acceptance_contracts.frozen.*.json")
    )
    for bundle_path in bundle_paths:
        try:
            bundle = _read_json(bundle_path)
        except (OSError, ValueError):
            continue
        for item in bundle.get("artifacts", []):
            pins.setdefault(str(item["path"]), str(item["sha256"]))
    return tuple(
        f"artifact drift:{pin_path}"
        for pin_path, expected in sorted(pins.items())
        if not verify_frozen_pin(REPO_ROOT, pin_path, expected)[0]
    )


def _retrospect_v35(batch: BatchRecord, plan: Mapping[str, Any]) -> RunsCheck:
    """v3.5 批次:按冻结 grade_output 语义重放(无 reconcile 脚本)。"""
    from contracts.run_trace_validator_v3 import validate_grader_v3
    from contracts.run_trace_validator_v3_5 import validate_run_trace_v35
    from financial_agent_reliability.harness.acceptance_v3 import (
        canonical,
        grade_candidate,
    )

    batch_dir = batch.directory
    task_by_run = {run_id: task for task in plan["tasks"] for run_id in task["run_ids"]}
    records: list[dict[str, Any]] = []
    run_errors: list[str] = []
    anchor_problems: list[str] = []
    checkpoint_events_total = 0

    for row in plan["runs"]:
        run_id = str(row["run_id"])
        errors: list[str] = []
        trace = _read_json(batch_dir / "traces" / f"{run_id}.json")
        try:
            validate_run_trace_v35(trace)
        except Exception as exc:  # noqa: BLE001 - 收集全部拒绝原因
            errors.append(f"validator rejected trace: {exc}")
        task = task_by_run[run_id]
        projection = _read_json(REPO_ROOT / task["projection_path"])
        card = _read_json(REPO_ROOT / task["source_case_path"])
        expected = {
            "status": card["oracle"]["expected_status"],
            "value": card["oracle"]["expected_value"],
            "reason_codes": card["oracle"]["reason_codes"],
        }
        candidate = trace["result"]["structured_output"]
        grader = grade_candidate(
            candidate, projection, expected, trace,
            parse_error=trace["result"]["parse_error"],
        )
        grader.update({
            "run_id": run_id,
            "model_id": row["model_id"],
            "case_id": task["case_id"],
            "identity_valid": (
                trace["provider"]["response_model_id"] == row["model_id"]
                and trace["preflight"]["identity_match"]
            ),
            "provider_status": trace["status"],
            "exact_semantic_match": (
                candidate is not None
                and candidate["status"] == expected["status"]
                and canonical(candidate["value"]) == canonical(expected["value"])
                and sorted(candidate["reason_codes"]) == sorted(expected["reason_codes"])
            ),
            "cost_usd": None,
            "cost_status": "provider_response_does_not_supply_cost",
        })
        try:
            validate_grader_v3(grader)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"grader schema invalid: {exc}")
        persisted = _read_json(batch_dir / "graders" / f"{run_id}.json")
        if grader != persisted:
            errors.append("grader not deterministically reproducible")
        events, chain_errors = _checkpoint_chain_events(
            batch_dir / "checkpoints" / f"{run_id}.jsonl", run_id
        )
        errors.extend(chain_errors)
        checkpoint_events_total += events

        checks = grader.get("checks", {})
        records.append({
            "run_id": run_id,
            "model_id": row["model_id"],
            "case_id": task["case_id"],
            "status": trace["status"],
            "identity_valid": grader["identity_valid"],
            "structure_parsed": bool(checks.get("structure_parsed")),
            "all_critical_invariants_passed": grader["all_critical_invariants_passed"],
            "exact_semantic_match": grader["exact_semantic_match"],
            "checks": {name: bool(value) for name, value in checks.items()},
            "fallback_detected": bool(trace["preflight"]["fallback_detected"]),
            "secret_leakage_detected": bool(trace["redaction"]["secret_leakage_detected"]),
            "real_side_effects": bool(trace["environment"]["real_side_effects"]),
            "checkpoint_events": events,
            "errors": errors,
        })
        run_errors.extend(f"{run_id}:{item}" for item in errors)

    return RunsCheck(
        records=tuple(records),
        run_errors=tuple(run_errors),
        frozen_input_errors=_verify_v35_bundle_pins(batch),
        preflight_errors=(),
        authorization_errors=(),
        invalidation_notes=(),
        anchor_problems=tuple(anchor_problems),
        metrics={
            "runs": len(records),
            "checkpoint_events": checkpoint_events_total,
            "regrade_engine": "acceptance_v3.grade_candidate(v3.5 semantics)",
        },
        # F4:v3.5 世代无 commitments/链锚字段,anchor_problems=() 是 N/A 而非通过。
        anchors_na=True,
    )


def _retrospect_with_reconcile(
    batch: BatchRecord,
    plan: Mapping[str, Any],
    module: types.ModuleType,
) -> RunsCheck:
    """v3.8–v3.11.1:复用冻结 reconcile 脚本的逐运行对账。"""
    batch_dir = batch.directory
    raw_frozen_errors = list(module.verify_frozen_inputs())
    kept_frozen, resolved_frozen = _reclassify_frozen_input_errors(batch, raw_frozen_errors)
    frozen_input_errors = tuple(kept_frozen)

    preflight_errors: list[str] = []
    preflight_path = batch_dir / "preflight.json"
    if preflight_path.is_file():
        preflight_errors = list(module.verify_preflight(plan, _read_json(preflight_path)))
    else:
        preflight_errors = ["preflight.json absent (M1: v3.5 类治理缺口或 carry-over)"]

    authorization_errors: list[str] = []
    authorization_path = batch_dir / "authorization.run.json"
    verify_authorization = getattr(module, "verify_authorization", None)
    if verify_authorization is not None and authorization_path.is_file():
        authorization = _read_json(authorization_path)
        preflight_doc = _read_json(preflight_path)
        if batch.batch_id == "acceptance-v3.10":
            first_repeat = plan["replication_design"]["first_round_repeats"][0]
            scope = [row for row in plan["runs"] if row["repeat"] == first_repeat]
            authorization_errors = list(
                verify_authorization(plan, preflight_doc, authorization, scope)
            )
        elif batch.batch_id == "coverage-v3.11.1":
            authorization_errors = list(verify_authorization(plan, preflight_doc, authorization))
        else:
            authorization_errors = list(
                verify_authorization(plan, preflight_doc, authorization, list(plan["runs"]))
            )
    elif verify_authorization is not None:
        authorization_errors = ["authorization.run.json absent"]
    elif authorization_path.is_file():
        # 冻结 reconcile 未配套授权校验(v3.8):做结构绑定复核兜底。
        authorization = _read_json(authorization_path)
        if authorization.get("plan_sha256") != plan.get("plan_sha256"):
            authorization_errors = ["authorization not plan-bound (structural check)"]
        if preflight_path.is_file() and authorization.get("preflight_sha256") != _read_json(
            preflight_path
        ).get("preflight_sha256"):
            authorization_errors.append("authorization not preflight-bound (structural check)")

    # 作废 run 清单(v3.10/v3.11):report-only,不入 records。
    invalidated_ids: set[str] = set()
    invalidation_notes: list[str] = []
    invalidation_path = batch_dir / "invalidated-runs.json"
    if invalidation_path.is_file():
        report = _read_json(invalidation_path)
        entries = report.get("entries", [])
        claimed = report.get("report_sha256")
        stripped = {k: v for k, v in report.items() if k != "report_sha256"}
        if claimed != content_sha256(stripped):
            invalidation_notes.append("invalidation report hash mismatch")
        for entry in entries:
            run_id = str(entry.get("run_id"))
            invalidated_ids.add(run_id)
            if entry.get("replaced_or_reexecuted") is not False:
                invalidation_notes.append(f"{run_id}: must stay report-only")
            for sub in ("traces", "graders", "candidates"):
                if (batch_dir / sub / f"{run_id}.json").exists():
                    invalidation_notes.append(f"{run_id}: frozen {sub} artifact must not exist")
            chain_only = getattr(module, "verify_chain_only", None)
            checkpoint_path = batch_dir / "checkpoints" / f"{run_id}.jsonl"
            if chain_only is not None and checkpoint_path.is_file():
                _events, chain_errors = chain_only(checkpoint_path, run_id, plan["plan_sha256"])
                if chain_errors:
                    invalidation_notes.append(f"{run_id}: forensics chain no longer verifies")

    task_by_run = {run_id: task for task in plan["tasks"] for run_id in task["run_ids"]}
    config_path = batch_dir / batch.config_file if batch.config_file else None
    records: list[Mapping[str, Any]] = []
    run_errors: list[str] = []
    anchor_problems: list[str] = []
    checkpoint_events_total = 0

    # 执行范围:v3.10 计划含 810 全矩阵但只授权首轮 repeat(270);其余批次
    # 的 plan.runs 即执行范围(与各自冻结 reconcile 脚本的 scope 一致)。
    if batch.batch_id == "acceptance-v3.10":
        first_repeat = plan["replication_design"]["first_round_repeats"][0]
        scope = [row for row in plan["runs"] if row["repeat"] == first_repeat]
    else:
        scope = list(plan["runs"])

    for row in scope:
        run_id = str(row["run_id"])
        if run_id in invalidated_ids:
            continue
        task = task_by_run[run_id]
        record = module.reconcile_run(batch_dir, row, task, plan)
        records.append(record)
        run_errors.extend(f"{run_id}:{item}" for item in record.get("errors", []))
        checkpoint_events_total += int(record.get("checkpoint_events", 0))
        anchor_problems.extend(_anchor_checks(batch_dir, row, task, plan, config_path))

    return RunsCheck(
        records=tuple(records),
        run_errors=tuple(run_errors),
        frozen_input_errors=frozen_input_errors,
        preflight_errors=tuple(preflight_errors),
        authorization_errors=tuple(authorization_errors),
        invalidation_notes=tuple(invalidation_notes),
        anchor_problems=tuple(anchor_problems),
        metrics={
            "runs": len(records),
            "planned_scope": len(scope),
            "invalidated": len(invalidated_ids),
            "checkpoint_events": checkpoint_events_total,
            "regrade_engine": f"frozen reconcile: {batch.reconcile_script}",
            "frozen_pins_relocated": len(resolved_frozen),
        },
        frozen_input_resolved=tuple(resolved_frozen),
    )


def retrospect_runs(batch: BatchRecord) -> RunsCheck:
    """逐运行复盘入口(验收/覆盖批次)。"""
    plan = load_batch_plan(batch)
    if plan is None:
        return RunsCheck(
            records=(), run_errors=(f"plan missing: {batch.plan_file}",),
            frozen_input_errors=(), preflight_errors=(),
            authorization_errors=(), invalidation_notes=(), anchor_problems=(),
        )
    if batch.batch_id == "acceptance-v3.5":
        return _retrospect_v35(batch, plan)
    module = load_reconcile_module(batch)
    if module is None:
        return RunsCheck(
            records=(), run_errors=(f"reconcile script missing: {batch.reconcile_script}",),
            frozen_input_errors=(), preflight_errors=(),
            authorization_errors=(), invalidation_notes=(), anchor_problems=(),
        )
    return _retrospect_with_reconcile(batch, plan, module)
