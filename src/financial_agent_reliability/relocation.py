"""PER-86 relocation map for the src-layout refactor (PER-85-D6 baseline).

背景:PER-85 用户裁决要求重跑全部实验、当前任务以重构代码为主;PER-85-D6
将旧 v3.x 冻结血緣降级为历史基线——内容保留、不改不删,但其路径/哈希钉住
不再构成重构与验收的阻塞。

PER-86 重构把代码包(graders、harness、oracles、pipelines、providers、
simulators、reporting)从仓库根移入 ``src/financial_agent_reliability/``。
旧冻结产物(契约 bundle、目录 manifest、报告契约)中按根相对路径钉住的
代码文件因此需要一张显式的迁移映射表,本模块是唯一事实来源:

- :func:`relocate` 把旧根相对路径映射到新位置(不在迁移范围内的返回 ``None``);
- :data:`CONTENT_CHANGED_BY_REFACTOR` 逐条列出因重构而合法变更内容的文件
  (导入路径、ROOT 深度、路径常量与 mjs 相对 URL 的机械改写),供漂移校验
  显式放行,而不是静默跳过;
- :func:`verify_frozen_pin` / :func:`verify_frozen_manifest` 供各校验点复用,
  保证"放行"始终是被点名、可审计的。

冻结产物本身一律不改:本模块只改变"如何解析其中记录的路径",不改变任何
冻结文件的内容。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable

__all__ = [
    "REFACTOR_TARGET",
    "RELOCATED_PREFIXES",
    "CONTENT_CHANGED_BY_REFACTOR",
    "TESTS_CHANGED_BY_REFACTOR",
    "relocate",
    "verify_frozen_pin",
    "verify_frozen_manifest",
]

#: 新布局下代码包的根相对位置。
REFACTOR_TARGET = "src/financial_agent_reliability"

#: 被 PER-86 迁移的旧顶层代码目录(根相对前缀)。
RELOCATED_PREFIXES: tuple[str, ...] = (
    "graders/",
    "harness/",
    "oracles/",
    "pipelines/",
    "providers/",
    "reporting/",
    "simulators/",
)

#: 因 PER-86 重构而内容发生合法变更的旧根相对路径。
#:
#: 变更全部是机械性的:包导入改写到 financial_agent_reliability.* 命名空间、
#: ``parents[1]``/``parents[2]`` 改为 ``parents[3]``/``parents[4]``、ROOT 相对
#: 路径常量与 mjs 相对 URL 跟随目录深度调整。行为由 261 个测试背书。
CONTENT_CHANGED_BY_REFACTOR: frozenset[str] = frozenset(
    {
        "harness/acceptance_v3.py",
        "harness/acceptance_v3_1.py",
        "harness/acceptance_v3_10.py",
        "harness/acceptance_v3_11.py",
        "harness/acceptance_v3_11_1.py",
        "harness/acceptance_v3_2.py",
        "harness/acceptance_v3_3.py",
        "harness/acceptance_v3_4.py",
        "harness/acceptance_v3_5.py",
        "harness/acceptance_v3_6.py",
        "harness/acceptance_v3_7.py",
        "harness/acceptance_v3_8.py",
        "harness/acceptance_v3_9.py",
        "harness/cli.py",
        "harness/diagnose_preflight_v3.mjs",
        "harness/live_acceptance_v3.mjs",
        "harness/live_acceptance_v3_1.mjs",
        "harness/live_acceptance_v3_10.mjs",
        "harness/live_acceptance_v3_11.mjs",
        "harness/live_acceptance_v3_2.mjs",
        "harness/live_acceptance_v3_3.mjs",
        "harness/live_acceptance_v3_4.mjs",
        "harness/live_acceptance_v3_5.mjs",
        "harness/live_acceptance_v3_6.mjs",
        "harness/live_acceptance_v3_7.mjs",
        "harness/live_acceptance_v3_8.mjs",
        "harness/live_acceptance_v3_9.mjs",
        "harness/live_smoke.mjs",
        "harness/matrix.py",
        "harness/pi_runtime.mjs",
        "harness/pi_runtime_v3.mjs",
        "harness/pi_runtime_v3_3.mjs",
        "harness/pi_runtime_v3_4.mjs",
        "harness/pi_runtime_v3_5.mjs",
        "harness/runner.py",
        "harness/smoke.py",
        "harness/stage3.py",
        "pipelines/longbridge/build_synthetic_v2.py",
        "pipelines/longbridge/freeze.py",
        "providers/bailian.py",
        "providers/bailian_http.py",
        "reporting/report.py",
    }
)


#: 被旧冻结 bundle 钉住、且因 PER-86 导入改写而合法变更内容的测试文件
#: (测试不随代码包迁移,保持在仓库根 tests/ 下)。
TESTS_CHANGED_BY_REFACTOR: frozenset[str] = frozenset(
    {
        "tests/integration/acceptance_v3.test.mjs",
        "tests/integration/acceptance_v3_1.test.mjs",
        "tests/integration/acceptance_v3_2.test.mjs",
        "tests/integration/acceptance_v3_3.test.mjs",
        "tests/integration/acceptance_v3_4.test.mjs",
        "tests/integration/financial_acceptance_v3_10.test.mjs",
        "tests/integration/financial_acceptance_v3_11.test.mjs",
        "tests/integration/financial_acceptance_v3_5.test.mjs",
        "tests/integration/financial_acceptance_v3_6.test.mjs",
        "tests/integration/financial_acceptance_v3_7.test.mjs",
        "tests/integration/financial_acceptance_v3_8.test.mjs",
        "tests/integration/financial_acceptance_v3_9.test.mjs",
        "tests/test_acceptance_v3.py",
        "tests/test_acceptance_v3_3.py",
        "tests/test_acceptance_v3_4.py",
        "tests/test_financial_acceptance_v3_10.py",
        "tests/test_financial_acceptance_v3_11.py",
        "tests/test_financial_acceptance_v3_5.py",
        "tests/test_financial_acceptance_v3_6.py",
        "tests/test_financial_acceptance_v3_7.py",
        "tests/test_financial_acceptance_v3_8.py",
        "tests/test_financial_acceptance_v3_9.py",
        "tests/test_reporting_contracts.py",
        "tests/test_longbridge_cases.py",
        "tests/test_longbridge_synthetic_v2.py",
    }
)


#: PER-86 任务书明确允许修改的根级工程配置文件(旧 v3.7 bundle 钉住了它们)。
ROOT_CONFIG_CHANGED_BY_REFACTOR: frozenset[str] = frozenset(
    {"pyproject.toml", "uv.lock"}
)


def relocate(path: str) -> str | None:
    """把迁移前的根相对路径映射到新位置;不属于迁移范围返回 ``None``。"""
    normalized = path.replace("\\", "/").lstrip("./")
    for prefix in RELOCATED_PREFIXES:
        if normalized.startswith(prefix):
            return f"{REFACTOR_TARGET}/{normalized}"
    return None


def _file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_pin(root: pathlib.Path, pin_path: str, expected_sha: str) -> tuple[bool, str]:
    """解析单个冻结路径钉住,返回 ``(是否通过, 分类)``。

    ``pin_path`` 必须是仓库根相对路径;``root`` 是仓库根。分类取值:
    - ``"ok"``: 文件在原位且哈希一致(未迁移产物);
    - ``"relocated"``: 文件已迁移到新位置且内容逐字节一致;
    - ``"refactor-change"``: 文件已迁移且属于 PER-86 机械改写清单(D6 放行);
    - ``"missing"`` / ``"drift"``: 解析失败或出现非放行漂移。
    """
    original = root / pin_path
    if original.is_file():
        actual = _file_sha256(original)
        if actual == expected_sha:
            return (True, "ok")
        if pin_path in TESTS_CHANGED_BY_REFACTOR or pin_path in ROOT_CONFIG_CHANGED_BY_REFACTOR:
            return (True, "refactor-change")
        return (False, "drift")
    new_relative = relocate(pin_path)
    if new_relative is None:
        return (False, "missing")
    relocated_file = root / new_relative
    if not relocated_file.is_file():
        return (False, "missing")
    if _file_sha256(relocated_file) == expected_sha:
        return (True, "relocated")
    if pin_path in CONTENT_CHANGED_BY_REFACTOR:
        return (True, "refactor-change")
    return (False, "drift")


def verify_frozen_manifest(
    manifest_path: pathlib.Path,
    *,
    project_root: pathlib.Path,
    extra_allow_changed: Iterable[str] = (),
) -> dict[str, Any]:
    """按 D6 语义校验冻结 manifest,返回分类结果而不是直接抛错。

    - manifest 自身的 ``contract_bundle_sha256`` 承诺必须仍然成立(证明
      manifest 文档未被改动);
    - 条目路径按 manifest 所在目录解析(与冻结时一致),再换算为仓库根相对
      路径交给 :func:`verify_frozen_pin`;
    - ``extra_allow_changed`` 用于放行 manifest 钉住的、因本次重构合法变更
      的测试文件(测试不属于代码包,不在统一迁移清单内)。

    任何 ``missing`` / ``drift`` 都会体现在返回的 ``errors`` 中。
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    allow_changed = set(extra_allow_changed)
    root_resolved = project_root.resolve()
    lines: list[str] = []
    results: list[dict[str, str]] = []
    errors: list[str] = []
    for index, entry in enumerate(entries):
        pin_path = entry.get("path", "")
        expected_sha = entry.get("sha256", "")
        lines.append(f"{expected_sha}  {pin_path}\n")
        resolved = (manifest_path.parent / pin_path).resolve()
        try:
            root_relative = resolved.relative_to(root_resolved).as_posix()
        except ValueError:
            errors.append(f"$/files/{index}: pin escapes project root: {pin_path}")
            results.append({"path": pin_path, "classification": "missing"})
            continue
        ok, classification = verify_frozen_pin(project_root, root_relative, expected_sha)
        if not ok and pin_path in allow_changed and classification in {"missing", "drift"}:
            # 钉住文件本身因重构移动且内容合法变更(例如被 manifest 引用的测试)。
            ok, classification = True, "refactor-change"
        if not ok:
            errors.append(f"$/files/{index}: {classification} for {pin_path}")
        results.append({"path": pin_path, "classification": classification})
    expected_bundle = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    if manifest.get("contract_bundle_sha256") != expected_bundle:
        errors.append("$/contract_bundle_sha256: manifest commitment mismatch")
    return {
        "manifest": str(manifest_path),
        "bundle_commitment_valid": manifest.get("contract_bundle_sha256") == expected_bundle,
        "entries": results,
        "errors": errors,
        "historical_baseline_pins": [
            item["path"] for item in results if item["classification"] in {"relocated", "refactor-change"}
        ],
    }
