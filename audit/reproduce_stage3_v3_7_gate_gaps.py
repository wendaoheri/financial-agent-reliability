"""Read-only counterexamples for the Stage 3 v3.7 independent gate audit."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from contracts.run_trace_validator_v3_7 import validate_run_trace_v37
from harness.acceptance_v3_7 import content_sha256, grade_candidate_v37


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/acceptance_v3_7/grader.baseline.json"


def main() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projection = json.loads((ROOT / fixture["projection_path"]).read_text(encoding="utf-8"))
    snapshot = json.loads((ROOT / fixture["snapshot_path"]).read_text(encoding="utf-8"))
    accepted_trace_mutations: list[str] = []

    mutations = {
        "attempt_response_model_mismatch": lambda trace: trace["logical_requests"][0]["attempts"][0].__setitem__(
            "response_model_id", "deepseek-v4-pro"
        ),
        "http_429_classified_success": lambda trace: trace["logical_requests"][0]["attempts"][0].__setitem__(
            "http_status", 429
        ),
        "initial_request_relabelled_repair": lambda trace: trace["logical_requests"][0].__setitem__(
            "phase", "repair"
        ),
    }
    for name, mutate in mutations.items():
        trace = copy.deepcopy(fixture["trace"])
        mutate(trace)
        validate_run_trace_v37(trace)
        accepted_trace_mutations.append(name)

    candidate_without_citations = copy.deepcopy(fixture["candidate"])
    candidate_without_citations["evidence_record_ids"] = []
    empty_citation_grade = grade_candidate_v37(
        candidate_without_citations, projection, snapshot, fixture["trace"]
    )

    changed_candidate = copy.deepcopy(fixture["candidate"])
    changed_candidate["uncertainty"] = "high"
    changed_candidate_grade = grade_candidate_v37(changed_candidate, projection, snapshot, fixture["trace"])
    changed_candidate_sha256 = content_sha256(changed_candidate)
    trace_candidate_sha256 = fixture["trace"]["result"]["candidate_output_sha256"]

    result = {
        "accepted_trace_mutations": accepted_trace_mutations,
        "empty_evidence_record_ids": {
            "all_applicable_checks_passed": empty_citation_grade["all_applicable_checks_passed"],
            "evidence_provenance_valid": empty_citation_grade["checks"]["evidence_provenance_valid"],
            "evidence_sufficient": empty_citation_grade["checks"]["evidence_sufficient"],
        },
        "candidate_hash_not_bound": {
            "all_applicable_checks_passed": changed_candidate_grade["all_applicable_checks_passed"],
            "candidate_sha256": changed_candidate_sha256,
            "trace_candidate_output_sha256": trace_candidate_sha256,
            "hashes_differ": changed_candidate_sha256 != trace_candidate_sha256,
        },
        "calculation_not_observed": {
            "observed_operations": fixture["trace"]["permission"]["observed_operations"],
            "calculation_check_passed": changed_candidate_grade["checks"]["calculation_correct"],
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    assert accepted_trace_mutations == list(mutations)
    assert all(empty_citation_grade["checks"][key] is True for key in ("evidence_provenance_valid", "evidence_sufficient"))
    assert empty_citation_grade["all_applicable_checks_passed"] is True
    assert changed_candidate_sha256 != trace_candidate_sha256
    assert changed_candidate_grade["all_applicable_checks_passed"] is True
    assert "calculate" not in fixture["trace"]["permission"]["observed_operations"]
    assert changed_candidate_grade["checks"]["calculation_correct"] is True


if __name__ == "__main__":
    main()
