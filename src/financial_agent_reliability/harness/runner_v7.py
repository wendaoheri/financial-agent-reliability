"""Append-only v7 runner that records the exact frozen-input artifact path."""

from __future__ import annotations

from typing import Any

from financial_agent_reliability.harness.runner import OfflineHarness


class OfflineHarnessV7(OfflineHarness):
    """Emit v7 traces while preserving the frozen v6 runner implementation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "trace_contract_version" in kwargs:
            raise TypeError("OfflineHarnessV7 fixes trace_contract_version to 7.0.0")
        # The frozen runner only knows how to assemble the v6-shaped trace.  The
        # append-only adapter adds the v7 field after that deterministic build.
        super().__init__(*args, trace_contract_version="6.0.0", **kwargs)

    def run(self, *, frozen_input_path: str, **kwargs: Any) -> dict[str, Any]:
        trace = super().run(frozen_input_path=frozen_input_path, **kwargs)
        trace["contract_version"] = "7.0.0"
        trace["context"]["frozen_input_path"] = frozen_input_path
        return trace
