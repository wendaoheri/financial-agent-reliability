"""Financial Agent Reliability benchmark harness.

研究配套代码包:评测 harness、评分器、数据管线、provider 适配、
模拟账本、oracle 与报告渲染。冻结评测产物(契约、快照、证据、审计)
保留在仓库根的旧血缘目录中,见 README.md 与 AGENTS.md。
"""

from __future__ import annotations

import importlib
import pathlib
import sys

# 冻结契约包 contracts/ 属于旧血缘历史基线,原地保留、不打包;代码包通过
# 仓库根解析它,因此把仓库根加回 sys.path(等价于旧布局下从仓库根运行)。
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

    旧冻结脚本(audit/、cases/ 下的构建器等)按 ``sys.path.insert(0, ROOT)``
    之后 ``from harness.x import y`` 的方式导入。先导入本包,旧包名即可在
    ``sys.modules`` 中命中,冻结脚本内容无需任何改动即可继续被导入执行。
    注意:这只是导入兼容;旧脚本内部按重构前路径做的哈希/路径校验仍属于
    历史基线(PER-85-D6),其验证结论按历史记录对待。
    """
    for name in _LEGACY_ALIASES:
        full_name = f"{__name__}.{name}"
        module = importlib.import_module(full_name)
        sys.modules.setdefault(name, module)


_register_legacy_aliases()
