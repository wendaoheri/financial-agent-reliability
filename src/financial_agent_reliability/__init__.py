"""Financial Agent Reliability benchmark harness.

研究配套代码包:评测 harness、评分器、数据管线、provider 适配、
模拟账本、oracle 与报告渲染。推理 provider/模型由 ``configs/inference.json``
配置,运行时契约见 ``configs/harness_contract.v1.json``(PER-323)。
基线 v1 的旧血缘目录已按 PER-323 冻结清理清单删除,基线 v2 由
Stage 3(PER-328)重建;删除留痕与回滚索引见
``docs/per323-stage2-deletion-record.md``。
"""

from __future__ import annotations

import importlib
import pathlib
import sys

# 历史布局兼容:把仓库根加回 sys.path。基线 v1 时代用于从仓库根导入
# contracts/ 等旧血缘包;这些目录已随 PER-323 清理删除,此段保留以维持
# 既有导入行为不变。
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#: PER-86 重构前的顶层包名 → 新包内子包。
_LEGACY_ALIASES: tuple[str, ...] = (
    "graders",
    "harness",
    "oracles",
    "pipelines",
    "providers",
    "reporting",
    "simulators",
)


def _register_legacy_aliases() -> None:
    """PER-85-D6 兼容层:把旧顶层包名注册为新子包的别名。

    历史上旧冻结脚本按 ``sys.path.insert(0, ROOT)`` 之后
    ``from harness.x import y`` 的方式导入;先导入本包,旧包名即可在
    ``sys.modules`` 中命中。引用这些别名的冻结脚本已随基线 v1 删除
    (PER-323),别名层本身保留以维持导入兼容行为不变。
    """
    for name in _LEGACY_ALIASES:
        full_name = f"{__name__}.{name}"
        module = importlib.import_module(full_name)
        sys.modules.setdefault(name, module)


_register_legacy_aliases()
