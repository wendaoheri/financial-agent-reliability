"""复盘哈希口径工具(补差距项 L6:双哈希口径)。

冻结产物中存在两种 sha256 口径,复盘时必须区分,否则会把规范化哈希与
整文件哈希互相比较而误判 drift:

- **整文件 sha256**:对文件原始字节求 sha256(manifest 逐件钉住、
  harness config / plan core 文件钉住等);
- **规范化内容哈希(c14n)**:对 JSON 文档按 ``financial-agent-c14n-json-v1``
  语义(键排序、紧凑分隔符、保留非 ASCII)序列化后求 sha256
  (case/snapshot ``integrity.content_sha256``、grader ``commitments``、
  plan ``plan_sha256``、v3.8 起 bundle ``bundle_sha256`` 等)。

本模块复用冻结校验器中的实现,不引入新的哈希语义。
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from contracts.run_trace_validator_v3_8 import (  # noqa: F401  (re-export)
    content_sha256,
    file_sha256,
)
from contracts.validate_case_data import (  # noqa: F401  (re-export)
    content_sha256 as case_content_sha256,
)

__all__ = [
    "aggregate_sorted_pairs",
    "case_content_sha256",
    "content_sha256",
    "file_sha256",
]


def aggregate_sorted_pairs(artifacts: list[Mapping[str, Any]]) -> str:
    """旧式 bundle 聚合哈希:按 path 排序后逐条 ``path\\0sha256\\n`` 串联。

    与 ``contracts.run_trace_validator.build_bundle_sha256`` 及
    ``harness.bundle.ImmutableBundle._aggregate`` 的语义一致;
    v3.5 / frozen-smoke / frozen-preflight 等早期 bundle 使用本口径。
    """
    commitments = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(artifacts, key=lambda entry: str(entry["path"]))
    )
    return hashlib.sha256(commitments.encode("utf-8")).hexdigest()


def detect_bundle_aggregate(artifacts: list[Mapping[str, Any]], claimed: str) -> str | None:
    """判定 bundle manifest 使用的聚合口径(差距项 L6)。

    返回命中的口径名:``"content_sha256"``(v3.8 起)或
    ``"sorted_pair_aggregate"``(v3.5 / frozen-smoke / frozen-preflight 等
    早期 bundle);两者皆不命中返回 ``None``(按完整性存疑处理)。
    """
    if content_sha256(list(artifacts)) == claimed:
        return "content_sha256"
    if aggregate_sorted_pairs(list(artifacts)) == claimed:
        return "sorted_pair_aggregate"
    return None
