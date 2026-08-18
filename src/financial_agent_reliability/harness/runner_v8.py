"""Append-only v8 runner for externally anchored frozen-input traces."""

from __future__ import annotations

from typing import Any

from financial_agent_reliability.harness.runner_v7 import OfflineHarnessV7


class OfflineHarnessV8(OfflineHarnessV7):
    """Emit v8 traces without modifying the frozen v7 implementation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "trace_contract_version" in kwargs:
            raise TypeError("OfflineHarnessV8 fixes trace_contract_version to 8.0.0")
        super().__init__(*args, **kwargs)

    def run(self, *, frozen_input_path: str, **kwargs: Any) -> dict[str, Any]:
        trace = super().run(frozen_input_path=frozen_input_path, **kwargs)
        trace["contract_version"] = "8.0.0"
        return trace
