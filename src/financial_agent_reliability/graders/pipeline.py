"""Oracle precedence, Gold/Silver separation, and blind expert payloads."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Iterable


ORACLE_PRIORITY = (
    "environment_state_oracle",
    "executable_oracle",
    "structured_evidence_oracle",
    "blind_independent_expert",
)


class GraderInputError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedGraderInput:
    ranking_rows: tuple[dict[str, Any], ...]
    diagnostic_rows: tuple[dict[str, Any], ...]
    judge_payloads: tuple[dict[str, Any], ...]
    cluster_unit: str = "case_family"


class GraderPipeline:
    @staticmethod
    def _blind_id(model_id: str, salt: str) -> str:
        digest = hashlib.sha256(f"{salt}:{model_id}".encode()).hexdigest()[:12]
        return f"candidate_{digest}"

    def prepare(
        self, rows: Iterable[dict[str, Any]], *, blind_salt: str
    ) -> PreparedGraderInput:
        if not blind_salt:
            raise GraderInputError("blind salt is required")
        ranking: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        judge_payloads: list[dict[str, Any]] = []
        for index, source in enumerate(rows):
            row = dict(source)
            tier = row.get("tier")
            if tier not in {"Gold", "Silver"}:
                raise GraderInputError(f"rows/{index}: tier must be Gold or Silver")
            present = [name for name in ORACLE_PRIORITY if name in row]
            if not present:
                raise GraderInputError(f"rows/{index}: no registered oracle result")
            if "blind_independent_expert" in present and present[0] != "blind_independent_expert":
                raise GraderInputError(
                    f"rows/{index}: expert isolation forbids expert output beside a higher-priority oracle"
                )
            selected_name = present[0]
            selected = row[selected_name]
            if not isinstance(selected, dict) or type(selected.get("critical_success")) is not bool:
                raise GraderInputError(f"rows/{index}: oracle requires boolean critical_success")
            normalized = {
                "run_id": row.get("run_id"),
                "family_id": row.get("family_id"),
                "tier": tier,
                "model_id": row.get("model_id"),
                "oracle_type": selected_name,
                "critical_success": selected["critical_success"],
            }
            (ranking if tier == "Gold" else diagnostics).append(normalized)
            blind_id = self._blind_id(str(row.get("model_id")), blind_salt)
            judge_payloads.append(
                {
                    "run_id": row.get("run_id"),
                    "family_id": row.get("family_id"),
                    "tier": tier,
                    "blind_model_id": blind_id,
                    "candidate_output": row.get("candidate_output"),
                    "oracle_type": selected_name,
                }
            )
        random.Random(int(hashlib.sha256(blind_salt.encode()).hexdigest()[:8], 16)).shuffle(
            judge_payloads
        )
        return PreparedGraderInput(
            tuple(ranking), tuple(diagnostics), tuple(judge_payloads)
        )
