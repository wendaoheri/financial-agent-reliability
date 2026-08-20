"""Diagnose a completed Phase 1 pilot without changing its frozen Gold."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from financial_agent_reliability.experiments.phase0 import PILOT_FAMILIES, TASK_SET_PATH
from financial_agent_reliability.experiments.phase1 import DEFAULT_OUTPUT
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets


def diagnose(
    output_directory: pathlib.Path = DEFAULT_OUTPUT,
    task_set_path: pathlib.Path = TASK_SET_PATH,
) -> dict[str, Any]:
    tasks = {
        task["id"]: task
        for task in json.loads(task_set_path.read_text(encoding="utf-8"))["tasks"]
        if task["notes"]["family_id"] in PILOT_FAMILIES
    }
    rows = [
        json.loads(line)
        for line in (output_directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(rows) != 48:
        raise ValueError(f"expected 48 completed traces, found {len(rows)}")
    components = {
        "action_exact": sum(
            row["submission"]["action"] == tasks[row["task_id"]]["checks"]["expected_action"]
            for row in rows
        ),
        "value_exact": sum(
            row["submission"]["value"] == tasks[row["task_id"]]["checks"]["expected_value"]
            for row in rows
        ),
        "reason_codes_exact": sum(
            sorted(row["submission"]["reason_codes"])
            == sorted(tasks[row["task_id"]]["checks"]["reason_codes"])
            for row in rows
        ),
        "citations_cover_gold": sum(
            set(tasks[row["task_id"]]["checks"]["cited_record_ids"])
            <= set(row["submission"]["cited_record_ids"])
            for row in rows
        ),
        "strict_parse_pass": sum(row["failure_type"] != "output_contract_violation" for row in rows),
        "safety_pass": sum(row["scores"]["safety"] == 1 for row in rows),
    }
    missing_interface = {
        task_id: ["allowed_actions", "allowed_reason_codes", "value_schema"]
        for task_id, task in tasks.items()
        if "output_contract" not in task
    }
    diagnosis = {
        "contract_type": "differential_eval_pilot_diagnosis",
        "contract_version": "1.0.0",
        "outcome": "invalid_for_model_quality_conclusion",
        "primary_failure_signature": "GRADER_OUTPUT_CONTRACT_UNDERSPECIFIED",
        "evidence": {
            "completed_runs": len(rows),
            "valid_infrastructure_runs": sum(row["status"] == "passed" for row in rows),
            "component_exact_matches": components,
            "pilot_tasks_missing_explicit_output_contract": missing_interface,
        },
        "reasoning": (
            "The grader requires exact action, value, and reason-code equality, but the task "
            "interface exposes only JSON field types; it does not expose controlled vocabularies "
            "or a value schema. High citation and safety pass rates alongside a correctness floor "
            "therefore cannot support a model or A0/A1 quality conclusion."
        ),
        "disposition": {
            "current_trace": "retain_as_failed_pilot_evidence",
            "gold": "unchanged_no_post_hoc_regrading",
            "ranking": "prohibited",
            "repeat_validation": "not_admitted",
            "lifecycle": "return_to_dev_with_new_task_contract_version",
        },
        "next_version_requirements": [
            "declare candidate-visible allowed action vocabulary",
            "declare candidate-visible allowed reason-code vocabulary without revealing the answer",
            "declare family-specific value JSON schema",
            "re-run leak, single-factor, dual-Oracle, and synthetic negative-control gates",
            "run a new pilot version; never overwrite or regrade this trace",
        ],
        "claim_boundary": "evaluation-interface diagnosis only; no model ranking or stability claim",
    }
    findings = scan_persisted_value_for_secrets(diagnosis)
    if findings:
        raise ValueError(f"diagnosis failed secret scan: {findings}")
    (output_directory / "diagnosis.json").write_text(
        json.dumps(diagnosis, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return diagnosis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = diagnose(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
