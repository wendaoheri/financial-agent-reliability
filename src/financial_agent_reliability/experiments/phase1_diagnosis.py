"""Diagnose a completed Phase 1 pilot without changing its frozen Gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

from financial_agent_reliability.experiments.phase0 import PILOT_FAMILIES, TASK_SET_PATH
from financial_agent_reliability.experiments.phase1 import DEFAULT_OUTPUT
from financial_agent_reliability.security import scan_persisted_value_for_secrets


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
        "strict_parse_pass": sum(
            row["failure_type"] != "output_contract_violation" for row in rows
        ),
        "safety_pass": sum((row.get("scores") or {}).get("safety") == 1 for row in rows),
    }
    aggregate = json.loads((output_directory / "aggregate.json").read_text(encoding="utf-8"))
    contracts = [row.get("input", {}).get("candidate_output_contract", {}) for row in rows]
    complete_contracts = all(
        contract.get("version") == "2.0.0"
        and contract.get("allowed_actions")
        and contract.get("allowed_reason_codes")
        and contract.get("answer_value_schema")
        for contract in contracts
    )
    infrastructure_valid = all(row["status"] == "passed" for row in rows)
    format_dominant = bool(aggregate["separation"]["format_check_dominant"])
    pilot_valid = complete_contracts and infrastructure_valid and not format_dominant
    repeat_admitted = bool(aggregate["separation"]["repeat_validation_admission"])
    diagnosis = {
        "contract_type": "differential_eval_pilot_diagnosis",
        "contract_version": "2.0.0",
        "outcome": "valid_exploratory_diagnostic_pilot" if pilot_valid else "invalid_pilot",
        "primary_failure_signature": None
        if pilot_valid
        else ("INFRASTRUCTURE_INVALID" if not infrastructure_valid else "FORMAT_CHECK_DOMINANT"),
        "evidence": {
            "completed_runs": len(rows),
            "valid_infrastructure_runs": sum(row["status"] == "passed" for row in rows),
            "component_exact_matches": components,
            "candidate_visible_contract_v2_complete": complete_contracts,
            "format_check_dominant": format_dominant,
            "separation": aggregate["separation"],
        },
        "reasoning": (
            "Contract v2 exposes the controlled action and reason-code vocabularies plus each "
            "family's value schema without exposing per-case Gold. Validity requires all 48 "
            "infrastructure cells and rejects a run still dominated by format failures."
        ),
        "disposition": {
            "current_trace": "retain_as_valid_v2_pilot_evidence"
            if pilot_valid
            else "retain_as_failed_v2_pilot_evidence",
            "gold": "unchanged_no_post_hoc_regrading",
            "ranking": "prohibited",
            "repeat_validation": "admitted_for_qualifying_families"
            if repeat_admitted
            else "not_admitted",
            "lifecycle": "preregister_repeat_validation"
            if repeat_admitted
            else "return_low_information_families_to_dev",
        },
        "next_action": (
            "pre-register repeated validation only for qualifying families"
            if repeat_admitted
            else "keep eval closed; revise or retire low-information families in dev"
        ),
        "claim_boundary": (
            "exploratory diagnostic only; no ranking, significance, or stability claim"
        ),
    }
    findings = scan_persisted_value_for_secrets(diagnosis)
    if findings:
        raise ValueError(f"diagnosis failed secret scan: {findings}")
    (output_directory / "diagnosis.json").write_text(
        json.dumps(diagnosis, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    artifact_names = (
        "trace.jsonl",
        "aggregate.json",
        "failure_signatures.json",
        "manifest.json",
        "diagnosis.json",
    )
    bundle_manifest = {
        "contract_type": "differential_eval_evidence_bundle_manifest",
        "contract_version": "2.0.0",
        "pilot_outcome": diagnosis["outcome"],
        "artifacts": [
            {
                "path": name,
                "sha256": hashlib.sha256((output_directory / name).read_bytes()).hexdigest(),
                "size_bytes": (output_directory / name).stat().st_size,
            }
            for name in artifact_names
        ],
        "security": {
            "secret_scan_passed": True,
            "synthetic_read_only": True,
            "credentials_persisted": False,
        },
    }
    bundle_findings = scan_persisted_value_for_secrets(bundle_manifest)
    if bundle_findings:
        raise ValueError(f"bundle manifest failed secret scan: {bundle_findings}")
    (output_directory / "bundle.manifest.json").write_text(
        json.dumps(bundle_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
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
