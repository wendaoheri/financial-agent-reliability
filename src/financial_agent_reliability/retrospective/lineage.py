"""批次血缘索引(差距项 A1:可从现有产物推导)。

机器可读索引:batch → 契约 bundle(base_bundle/supersedes 链)→ plan →
preflight → bundle manifest。v3–v3.4 无 plan 的情况显式说明(契约包
``supersedes.plan`` 指向 stage3_smoke_plan.v2)。只读推导,不新增记录。
"""

from __future__ import annotations

import json
from typing import Any

from financial_agent_reliability.retrospective.hashing import file_sha256
from financial_agent_reliability.retrospective.registry import (
    BATCHES,
    REPO_ROOT,
    BatchRecord,
)


def _contract_bundle_lineage(batch: BatchRecord) -> dict[str, Any] | None:
    candidates = sorted(batch.directory.glob("stage3_acceptance_contracts.frozen.*.json"))
    if not candidates:
        return None
    bundle_path = candidates[0]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    entry: dict[str, Any] = {
        "path": bundle_path.relative_to(REPO_ROOT).as_posix(),
        "bundle_sha256": bundle.get("bundle_sha256"),
        "artifacts": len(bundle.get("artifacts", [])),
    }
    supersedes = bundle.get("supersedes")
    if isinstance(supersedes, dict):
        entry["supersedes"] = {
            key: supersedes.get(key) for key in ("path", "sha256", "v3_10_bundle_sha256")
            if supersedes.get(key) is not None
        }
    base = bundle.get("base_bundle")
    if isinstance(base, dict):
        entry["base_bundle"] = base
    preserved = bundle.get("preserved")
    if isinstance(preserved, dict):
        entry["preserved_bundle_sha256_keys"] = sorted(preserved.keys())
        entry["retroactive_regrading"] = preserved.get("retroactive_regrading")
    return entry


def batch_lineage(batch: BatchRecord) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "batch_id": batch.batch_id,
        "batch_type": batch.batch_type,
        "directory": batch.directory.relative_to(REPO_ROOT).as_posix(),
        "contract_version": batch.contract_version,
    }
    contract = _contract_bundle_lineage(batch)
    if contract:
        entry["contract_bundle"] = contract
    if batch.plan_file:
        plan_path = batch.directory / batch.plan_file
        if plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            entry["plan"] = {
                "path": plan_path.relative_to(REPO_ROOT).as_posix(),
                "plan_sha256": plan.get("plan_sha256"),
                "plan_core_sha256": plan.get("plan_core_sha256"),
                "tasks": len(plan.get("tasks", [])),
                "runs": len(plan.get("runs", [])),
            }
    else:
        entry["plan"] = {
            "path": None,
            "note": (
                "protocol-gate 批次无验收 plan;契约包 supersedes/base 链指向 "
                "stage3_smoke_plan.v2(见 Stage 1 差距报告 A1)"
            ),
        }
    manifest_path = batch.directory / "bundle.manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry["evidence_manifest"] = {
            "contract_type": manifest.get("contract_type"),
            "contract_version": manifest.get("contract_version"),
            "artifacts": len(manifest.get("artifacts", [])),
            "authorization_basis": manifest.get("authorization_basis"),
        }
    for name in ("preflight.json", "execution_decision.json"):
        path = batch.directory / name
        if path.is_file():
            entry[name] = {"sha256": file_sha256(path)}
    return entry


def build_lineage_index() -> dict[str, Any]:
    return {
        "contract_type": "stage3_batch_lineage_index",
        "index_version": "1.0.0",
        "derived_from": "read-only derivation over runs/ + evidence/ + contracts/",
        "batches": [batch_lineage(batch) for batch in BATCHES],
    }
