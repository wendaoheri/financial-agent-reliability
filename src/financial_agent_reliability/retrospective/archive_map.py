"""archive ↔ evidence 映射(差距项 A4/M2:可从现有产物推导)。

``runs/frozen-runtime-archive/`` 下的副本不自证(缺 manifest/plan/contracts),
但可由 ``evidence/stage3`` 正本推导:逐文件整 sha256 比对,并回指正本
bundle manifest 中的登记条目。本工具生成该映射索引并复核一致性(只读)。
"""

from __future__ import annotations

import json
from typing import Any

from financial_agent_reliability.retrospective.hashing import file_sha256
from financial_agent_reliability.retrospective.registry import (
    ARCHIVE_COPIES,
    REPO_ROOT,
)


def map_archive_pair(archive_rel: str, canonical_rel: str) -> dict[str, Any]:
    archive_dir = REPO_ROOT / archive_rel
    canonical_dir = REPO_ROOT / canonical_rel
    entry: dict[str, Any] = {
        "archive": archive_rel,
        "canonical": canonical_rel,
    }
    if not archive_dir.is_dir():
        entry["problems"] = [f"archive directory missing: {archive_rel}"]
        entry["ok"] = False
        return entry

    manifest: dict[str, str] = {}
    manifest_path = canonical_dir / "bundle.manifest.json"
    if manifest_path.is_file():
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = {str(item["path"]): str(item["sha256"]) for item in manifest_doc.get("artifacts", [])}

    files = 0
    mismatched: list[str] = []
    missing_canonical: list[str] = []
    not_in_manifest: list[str] = []
    for path in sorted(archive_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(archive_dir).as_posix()
        files += 1
        canonical_path = canonical_dir / relative
        if not canonical_path.is_file():
            missing_canonical.append(relative)
            continue
        archive_sha = file_sha256(path)
        if archive_sha != file_sha256(canonical_path):
            mismatched.append(relative)
        if manifest and relative in manifest and manifest[relative] != archive_sha:
            not_in_manifest.append(relative)
        elif manifest and relative not in manifest and relative != "bundle.manifest.json":
            not_in_manifest.append(relative)

    problems = []
    if mismatched:
        problems.append(f"{len(mismatched)} 文件与正本字节不一致")
    if missing_canonical:
        problems.append(f"{len(missing_canonical)} 文件在正本中缺失")
    if not_in_manifest and manifest:
        problems.append(f"{len(not_in_manifest)} 文件未在正本 manifest 登记或哈希不符")
    entry.update({
        "files": files,
        "byte_equal_with_canonical": files - len(mismatched) - len(missing_canonical),
        "problems": problems,
        "ok": not problems,
    })
    return entry


def build_archive_map() -> dict[str, Any]:
    pairs = [map_archive_pair(archive, canonical) for archive, canonical in ARCHIVE_COPIES]
    return {
        "contract_type": "archive_evidence_mapping_index",
        "index_version": "1.0.0",
        "pairs": pairs,
        "all_ok": all(pair.get("ok") for pair in pairs),
    }
