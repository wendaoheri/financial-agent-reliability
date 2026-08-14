"""Read-only counterexample battery for the Stage 3 v3.8 independent gate audit (PER-47).

Every mutation below MUST be rejected by the v3.8 validator or fail the v3.8 grader.
If any assertion fails, the corresponding PER-44 second-round gate (B2/B3/B5/B6) is NOT closed.
This script performs no network calls, reads no credentials, and never mutates frozen files.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from contracts.run_trace_validator_v3_8 import HarnessContractV38Error, content_sha256, validate_run_trace_v38
from harness.acceptance_v3_8 import grade_candidate_v38

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/acceptance_v3_8/grader.baseline.json"


def _rejected(mutate, *, companions=None, label="", base=None) -> str:
    trace = copy.deepcopy(base if base is not None else BASE["trace"])
    mutate(trace)
    try:
        validate_run_trace_v38(trace, scan_companions=companions)
    except HarnessContractV38Error as exc:
        return str(exc)[:160]
    raise AssertionError(f"MUTATION ACCEPTED (gate leak): {label}")


def _grade(candidate, trace) -> dict:
    return grade_candidate_v38(candidate, PROJECTION, SNAPSHOT, trace)


def main() -> None:
    out: dict[str, object] = {}

    # --- sanity: frozen baseline must pass both gates -------------------------
    assert validate_run_trace_v38(BASE["trace"], scan_companions=[BASE["candidate"]])
    base_grade = _grade(BASE["candidate"], BASE["trace"])
    assert base_grade["all_applicable_checks_passed"] is True
    out["baseline"] = {"validator": "accepted", "grader_all_passed": True}

    # ================= B2: attempt identity / HTTP / phase semantics =========
    b2: dict[str, str] = {}
    b2["attempt_response_model_mismatch_200"] = _rejected(
        lambda t: t["logical_requests"][0]["attempts"][0].__setitem__("response_model_id", "deepseek-v4-pro"),
        label="B2 response identity",
    )
    b2["http_429_kept_success"] = _rejected(
        lambda t: t["logical_requests"][0]["attempts"][0].__setitem__("http_status", 429),
        label="B2 429 as success",
    )
    b2["http_500_kept_success"] = _rejected(
        lambda t: t["logical_requests"][0]["attempts"][0].__setitem__("http_status", 500),
        label="B2 500 as success",
    )

    def _reclassify_429(t):
        attempt = t["logical_requests"][0]["attempts"][0]
        attempt["http_status"] = 429
        attempt["classification"] = "provider_or_runtime_failure"
        attempt["response_model_id"] = None
        request = t["logical_requests"][0]
        request["classification"] = "provider_or_runtime_failure"
        request["retries_used"] = 0
        t["status"] = "invalid_provider_or_runtime"
        t["failure"] = {"class": "provider_or_runtime_failure", "code": None}
        t["result"]["candidate_scored"] = False

    # consistent 429 failure is legitimately accepted as provider failure — scoring gate only
    t429 = copy.deepcopy(BASE["trace"]); _reclassify_429(t429)
    validate_run_trace_v38(t429, scan_companions=[])
    g429 = _grade(None, t429)
    b2["consistent_429_not_scored"] = str({"candidate_scored": t429["result"]["candidate_scored"], "provider_runtime_valid": g429["checks"]["provider_runtime_valid"]})
    assert t429["result"]["candidate_scored"] is False and g429["checks"]["provider_runtime_valid"] is False

    def _fail_attempt_other_response_model(t):
        attempt = t["logical_requests"][0]["attempts"][0]
        attempt["http_status"] = None
        attempt["classification"] = "provider_or_runtime_failure"
        attempt["response_model_id"] = "glm-5.2"  # fabricated response model on a no-response failure
        request = t["logical_requests"][0]
        request["classification"] = "provider_or_runtime_failure"
        t["status"] = "invalid_provider_or_runtime"
        t["failure"] = {"class": "provider_or_runtime_failure", "code": None}
        t["result"]["candidate_scored"] = False

    b2["no_response_failure_fabricated_response_model"] = _rejected(_fail_attempt_other_response_model, label="B2 fabricated response model")

    b2["first_request_relabelled_repair"] = _rejected(
        lambda t: t["logical_requests"][0].__setitem__("phase", "repair"),
        label="B2 phase initial prefix",
    )
    out["B2_trace_mutations_rejected"] = b2

    # ================= B2/B5 multi-request fixture (positive + negatives) =====
    multi = json.loads((ROOT / "tests/fixtures/acceptance_v3_8/trace.multi_request_retry.json").read_text(encoding="utf-8"))
    multi_trace = multi["trace"] if isinstance(multi, dict) and "trace" in multi else multi
    assert validate_run_trace_v38(multi_trace, scan_companions=[])
    phases = [r["phase"] for r in multi_trace["logical_requests"]]
    n_attempts = [len(r["attempts"]) for r in multi_trace["logical_requests"]]
    out["multi_request_fixture"] = {"phases": phases, "attempts_per_request": n_attempts, "validator": "accepted"}

    b2m: dict[str, str] = {}
    b2m["interleaved_initial_after_repair"] = _rejected(
        lambda t: t["logical_requests"][-1].__setitem__("phase", "initial"),
        label="B2 interleaved phases", base=multi_trace,
    )

    def _semantic_retry(t):
        retried = next(r for r in t["logical_requests"] if len(r["attempts"]) == 2)
        retried["attempts"][0]["classification"] = "success"

    b2m["semantic_retry_after_success"] = _rejected(_semantic_retry, label="B2 semantic retry", base=multi_trace)

    def _payload_divergent_retry(t):
        retried = next(r for r in t["logical_requests"] if len(r["attempts"]) == 2)
        retried["attempts"][1]["payload_sha256"] = "b" * 64

    b2m["retry_payload_not_identical"] = _rejected(_payload_divergent_retry, label="B2 retry payload binding", base=multi_trace)

    def _repair_attempt_success_classified(t):
        retried = next(r for r in t["logical_requests"] if len(r["attempts"]) == 2)
        retried["attempts"][0]["http_status"] = 200
        # classification stays provider_or_runtime_failure -> derived mismatch must reject

    b2m["repair_attempt_http_misclassified"] = _rejected(_repair_attempt_success_classified, label="B2 derived classification", base=multi_trace)
    out["B2_multi_request_mutations_rejected"] = b2m

    # ================= B3: ledger replay + calculation execution ==============
    ledger_fx = json.loads((ROOT / "tests/fixtures/acceptance_v3_8/trace.ledger_restored.json").read_text(encoding="utf-8"))
    ledger_trace = ledger_fx["trace"] if isinstance(ledger_fx, dict) and "trace" in ledger_fx else ledger_fx
    assert validate_run_trace_v38(ledger_trace, scan_companions=[])
    ledger_events = [e for e in ledger_trace["tool_events"] if e["tool_name"] == "simulated_ledger"]
    out["ledger_fixture"] = {
        "validator": "accepted",
        "ledger_events": len(ledger_events),
        "initial_root": ledger_trace["environment"]["initial_ledger_sha256"],
        "final_root": ledger_trace["environment"]["final_ledger_sha256"],
        "final_matches_initial": ledger_trace["environment"]["final_state_matches_initial"],
    }
    assert ledger_trace["environment"]["final_state_matches_initial"] is True, "ledger fixture must restore initial state"

    b3: dict[str, str] = {}

    def _wrong_resulting_quantity(t):
        event = next(e for e in t["tool_events"] if e["tool_name"] == "simulated_ledger" and e["operation"] in {"buy", "sell"})
        event["ledger_transition"]["resulting_quantity"] = "999999"

    b3["ledger_wrong_resulting_quantity"] = _rejected(_wrong_resulting_quantity, label="B3 ledger arithmetic", base=ledger_trace)

    def _broken_state_chain(t):
        events = [e for e in t["tool_events"] if e["tool_name"] == "simulated_ledger"]
        events[1]["state_before_sha256"] = "c" * 64

    b3["ledger_broken_state_chain"] = _rejected(_broken_state_chain, label="B3 ledger state chain", base=ledger_trace)

    def _dropped_restoring_event(t):
        events = [e for e in t["tool_events"] if e["tool_name"] == "simulated_ledger"]
        assert len(events) >= 2, "ledger fixture needs >=2 ledger events for drop test"
        t["tool_events"].remove(events[-1])  # drop the restoring sell -> terminal root cannot match
        t["usage"]["tool_calls"] = len(t["tool_events"])

    b3["ledger_dropped_restoring_event"] = _rejected(_dropped_restoring_event, label="B3 dropped ledger event", base=ledger_trace)

    def _partial_sell_not_restored(t):
        events = [e for e in t["tool_events"] if e["tool_name"] == "simulated_ledger"]
        sell = events[-1]
        sell["ledger_transition"]["quantity"] = "1.5"
        sell["ledger_transition"]["resulting_quantity"] = "1"  # arithmetic-consistent but terminal != initial

    b3["ledger_partial_sell_terminal_mismatch"] = _rejected(_partial_sell_not_restored, label="B3 terminal state recomputed", base=ledger_trace)

    def _hardcoded_safe_terminal(t):
        t["environment"]["final_state_matches_initial"] = True
        t["environment"]["final_ledger_sha256"] = "d" * 64

    b3["ledger_hardcoded_terminal_safety"] = _rejected(_hardcoded_safe_terminal, label="B3 hardcoded terminal state", base=ledger_trace)
    out["B3_ledger_mutations_rejected"] = b3

    # grader side: calculation check needs a REAL matching calculate event
    no_calc_trace = copy.deepcopy(BASE["trace"])
    no_calc_trace["tool_events"] = [e for e in no_calc_trace["tool_events"] if e["tool_name"] != "calculate"]
    no_calc_trace["usage"]["tool_calls"] = len(no_calc_trace["tool_events"])
    no_calc_trace["permission"]["observed_operations"] = [op for op in no_calc_trace["permission"]["observed_operations"] if op != "calculate"]
    no_calc_grade = _grade(BASE["candidate"], no_calc_trace)
    out["B3_calculation_without_event"] = {
        "calculation_correct": no_calc_grade["checks"]["calculation_correct"],
        "method_correct": no_calc_grade["checks"]["method_correct"],
        "all_passed": no_calc_grade["all_applicable_checks_passed"],
    }
    assert no_calc_grade["checks"]["calculation_correct"] is False
    assert no_calc_grade["checks"]["method_correct"] is False
    assert no_calc_grade["all_applicable_checks_passed"] is False

    forged_calc = copy.deepcopy(BASE["trace"])
    forged_calc["tool_events"] = [dict(e) for e in forged_calc["tool_events"]]
    for event in forged_calc["tool_events"]:
        if event["tool_name"] == "calculate":
            event["output_sha256"] = "e" * 64  # claim a different calculation result
    forged_grade = _grade(BASE["candidate"], forged_calc)
    out["B3_calculation_forged_output_hash"] = {
        "calculation_correct": forged_grade["checks"]["calculation_correct"],
        "all_passed": forged_grade["all_applicable_checks_passed"],
    }
    assert forged_grade["checks"]["calculation_correct"] is False
    assert forged_grade["all_applicable_checks_passed"] is False

    forged_unit = copy.deepcopy(BASE["trace"])
    for event in forged_unit["tool_events"]:
        if event["tool_name"] == "read_frozen_evidence":
            event["unit_basis_sha256"] = "f" * 64  # unit commitment not recomputable
    unit_grade = _grade(BASE["candidate"], forged_unit)
    out["B3_unit_commitment_forged"] = {
        "unit_correct": unit_grade["checks"]["unit_correct"],
        "all_passed": unit_grade["all_applicable_checks_passed"],
    }
    assert unit_grade["checks"]["unit_correct"] is False
    assert unit_grade["all_applicable_checks_passed"] is False

    # ================= B5: candidate/trace/grader hash binding ================
    empty_cite = copy.deepcopy(BASE["candidate"])
    empty_cite["evidence_record_ids"] = []
    empty_grade = _grade(empty_cite, BASE["trace"])
    out["B5_empty_evidence_record_ids"] = {
        "evidence_provenance_valid": empty_grade["checks"]["evidence_provenance_valid"],
        "evidence_sufficient": empty_grade["checks"]["evidence_sufficient"],
        "unit_correct": empty_grade["checks"]["unit_correct"],
        "all_passed": empty_grade["all_applicable_checks_passed"],
    }
    assert empty_grade["checks"]["evidence_provenance_valid"] is False
    assert empty_grade["checks"]["evidence_sufficient"] is False
    assert empty_grade["all_applicable_checks_passed"] is False

    changed_candidate = copy.deepcopy(BASE["candidate"])
    changed_candidate["uncertainty"] = "high"
    changed_grade = _grade(changed_candidate, BASE["trace"])
    out["B5_candidate_hash_mismatch"] = {
        "candidate_trace_bound": changed_grade["checks"]["candidate_trace_bound"],
        "candidate_sha256": content_sha256(changed_candidate),
        "trace_commitment": BASE["trace"]["result"]["candidate_output_sha256"],
        "all_passed": changed_grade["all_applicable_checks_passed"],
    }
    assert changed_grade["checks"]["candidate_trace_bound"] is False
    assert changed_grade["all_applicable_checks_passed"] is False

    commitments = base_grade["commitments"]
    rehashed = content_sha256({k: v for k, v in base_grade.items() if k != "grader_sha256"})
    out["B5_grader_commitments"] = {
        "candidate_sha256_matches_trace": commitments["candidate_sha256"] == BASE["trace"]["result"]["candidate_output_sha256"],
        "trace_sha256_recomputed": commitments["trace_sha256"] == content_sha256(BASE["trace"]),
        "projection_sha256_recomputed": commitments["projection_sha256"] == content_sha256(PROJECTION),
        "snapshot_sha256_recomputed": commitments["snapshot_sha256"] == content_sha256(SNAPSHOT),
        "grader_self_hash_recomputed": rehashed == base_grade["grader_sha256"],
    }
    assert commitments["candidate_sha256"] == BASE["trace"]["result"]["candidate_output_sha256"]
    assert commitments["trace_sha256"] == content_sha256(BASE["trace"])
    assert commitments["projection_sha256"] == content_sha256(PROJECTION)
    assert commitments["snapshot_sha256"] == content_sha256(SNAPSHOT)
    assert rehashed == base_grade["grader_sha256"]

    # ================= B6: cited ∩ observed ∩ material, PIT, secrets ==========
    b6: dict[str, object] = {}

    cited_not_observed = copy.deepcopy(BASE["candidate"])
    cited_not_observed["evidence_record_ids"] = ["FKW-12-MEX-2021"]  # registered, non-material, never read
    not_observed_grade = _grade(cited_not_observed, BASE["trace"])
    b6["cited_non_material_non_observed"] = {
        "evidence_provenance_valid": not_observed_grade["checks"]["evidence_provenance_valid"],
        "evidence_sufficient": not_observed_grade["checks"]["evidence_sufficient"],
        "all_passed": not_observed_grade["all_applicable_checks_passed"],
    }
    assert not_observed_grade["checks"]["evidence_provenance_valid"] is False
    assert not_observed_grade["checks"]["evidence_sufficient"] is False
    assert not_observed_grade["all_applicable_checks_passed"] is False

    forged_evidence_hash = copy.deepcopy(BASE["trace"])
    for event in forged_evidence_hash["tool_events"]:
        if event["tool_name"] == "read_frozen_evidence":
            event["output_sha256"] = "a1" * 32  # output not matching frozen snapshot record
    forged_ev_grade = _grade(BASE["candidate"], forged_evidence_hash)
    b6["observed_requires_real_evidence_event"] = {
        "evidence_sufficient": forged_ev_grade["checks"]["evidence_sufficient"],
        "evidence_provenance_valid": forged_ev_grade["checks"]["evidence_provenance_valid"],
        "all_passed": forged_ev_grade["all_applicable_checks_passed"],
    }
    assert forged_ev_grade["checks"]["evidence_sufficient"] is False
    assert forged_ev_grade["all_applicable_checks_passed"] is False

    bad_provenance = copy.deepcopy(BASE["trace"])
    bad_provenance["evidence_observations"][0]["source_locator"] = "snapshots/public/v2/raw/OTHER.json#/x"
    prov_grade = _grade(BASE["candidate"], bad_provenance)
    b6["provenance_source_locator_mismatch"] = {
        "evidence_provenance_valid": prov_grade["checks"]["evidence_provenance_valid"],
        "all_passed": prov_grade["all_applicable_checks_passed"],
    }
    assert prov_grade["checks"]["evidence_provenance_valid"] is False

    pit_violation = copy.deepcopy(BASE["trace"])
    pit_violation["evidence_observations"][0]["available_at"] = "2026-08-12T00:00:00Z"  # after cutoff
    pit_grade = _grade(BASE["candidate"], pit_violation)
    b6["pit_available_at_after_cutoff"] = {
        "pit_valid": pit_grade["checks"]["pit_valid"],
        "all_passed": pit_grade["all_applicable_checks_passed"],
    }
    assert pit_grade["checks"]["pit_valid"] is False
    assert pit_grade["all_applicable_checks_passed"] is False

    def _secret_in_trace(t):
        t["reason_facts"] = {"note": "Bearer abcdef1234567890 leaked"}

    b6["secret_in_trace_rejected"] = _rejected(_secret_in_trace, label="B6 secret trace gate")
    leaked_candidate = copy.deepcopy(BASE["candidate"])
    leaked_candidate["uncertainty"] = "low"
    try:
        validate_run_trace_v38(BASE["trace"], scan_companions=[{**leaked_candidate, "permission_boundary_claimed": True, "sk_like": "sk-abcdef1234567890"}])
        raise AssertionError("MUTATION ACCEPTED (gate leak): B6 secret companion gate")
    except HarnessContractV38Error as exc:
        b6["secret_in_companion_candidate_rejected"] = str(exc)[:160]
    out["B6_evidence_and_secret_gates"] = b6

    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    print("ALL_COUNTEREXAMPLES_REJECTED_AS_REQUIRED")


BASE = json.loads(FIXTURE.read_text(encoding="utf-8"))
PROJECTION = json.loads((ROOT / BASE["projection_path"]).read_text(encoding="utf-8"))
SNAPSHOT = json.loads((ROOT / BASE["snapshot_path"]).read_text(encoding="utf-8"))

if __name__ == "__main__":
    main()
