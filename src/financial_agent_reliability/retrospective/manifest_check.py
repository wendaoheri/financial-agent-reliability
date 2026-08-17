"""R1 / A1:证据 bundle manifest 完整性检查。

对 ``bundle.manifest.json`` 的 ``artifacts[]`` 逐文件重算 sha256 并与登记值
比对;目录内存在但未被 manifest 登记的文件一律视为污染(口径 3.2 R1);
``bundle_sha256`` 按两种历史聚合口径之一复核(差距项 L6)。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from financial_agent_reliability.retrospective.hashing import (
    detect_bundle_aggregate,
    file_sha256,
)
from financial_agent_reliability.retrospective.model import (
    FAIL,
    NA,
    PASS,
    CheckResult,
)

MANIFEST_NAME = "bundle.manifest.json"


def load_manifest(batch_dir: pathlib.Path) -> dict[str, Any] | None:
    manifest_path = batch_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def unregistered_files(batch_dir: pathlib.Path, manifest: dict[str, Any]) -> list[str]:
    """目录内存在但未被 manifest 登记的文件(复盘入口之外的污染面)。"""
    registered = {str(item["path"]) for item in manifest.get("artifacts", [])}
    extras: list[str] = []
    for path in sorted(batch_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(batch_dir).as_posix()
        if relative == MANIFEST_NAME:
            continue
        if relative not in registered:
            extras.append(relative)
    return extras


def check_bundle_manifest(batch_dir: pathlib.Path) -> CheckResult:
    """R1/A1 主检查。批次无 manifest 时按注册表语义返回 not_applicable。"""
    manifest = load_manifest(batch_dir)
    if manifest is None:
        return CheckResult(
            name="A1_manifest_integrity",
            status=NA,
            details=("bundle.manifest.json absent (protocol-gate/diagnostic batch)",),
        )

    artifacts = manifest.get("artifacts", [])
    missing: list[str] = []
    drifted: list[str] = []
    for item in artifacts:
        path = batch_dir / str(item["path"])
        if not path.is_file():
            missing.append(str(item["path"]))
            continue
        if file_sha256(path) != item.get("sha256"):
            drifted.append(str(item["path"]))

    extras = unregistered_files(batch_dir, manifest)

    aggregate_mode = None
    aggregate_ok: bool | None = None
    claimed_bundle_sha = manifest.get("bundle_sha256")
    if claimed_bundle_sha:
        aggregate_mode = detect_bundle_aggregate(list(artifacts), str(claimed_bundle_sha))
        aggregate_ok = aggregate_mode is not None

    problems = [f"missing artifact: {p}" for p in missing]
    problems += [f"hash drift: {p}" for p in drifted]
    problems += [f"unregistered file (pollution): {p}" for p in extras]
    if claimed_bundle_sha and not aggregate_ok:
        problems.append("bundle_sha256 matches neither registered aggregate convention")

    status = FAIL if problems else PASS
    return CheckResult(
        name="A1_manifest_integrity",
        status=status,
        details=tuple(problems[:20]) or ("all pinned artifacts verify",),
        metrics={
            "artifacts": len(artifacts),
            "missing": len(missing),
            "drifted": len(drifted),
            "unregistered": len(extras),
            "bundle_sha256_convention": aggregate_mode,
            "contract_type": manifest.get("contract_type"),
            "contract_version": manifest.get("contract_version"),
            "manifest_status": manifest.get("status"),
        },
    )
