"""PER-58 independent audit — Part 3: visibility gate over all 90 tasks,
8 negative scenarios, hidden-label leakage scan, reason vocabulary 18->21,
23-operation coverage, three-model symmetry and v3.9 zero-drift, and the
byte-identical expectation check for the 9 unchanged previously-covered cases.

Runs the frozen harness gate implementations (the audited subject) and
cross-checks their outputs against independently gathered baselines.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness import acceptance_v3_10 as v310  # noqa: E402
from harness import acceptance_v3_7 as v37  # noqa: E402

FAILURES: list[str] = []
DEC_RE = __import__("re").compile(r"^-?\d+(?:\.\d+)?$")


def check(condition: bool, label: str) -> None:
    tag = "OK  " if condition else "FAIL"
    if not condition:
        FAILURES.append(label)
    print(f"[{tag}] {label}")


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def main() -> None:
    plan = load(ROOT / "contracts/stage3_acceptance_plan.v3.10.json")
    tasks = plan["tasks"]
    check(len(tasks) == 90, "plan carries 90 tasks")

    # --- 1. visibility gate over all 90 tasks (with input sha binding) ---
    violations_all = []
    reports = {}
    for task in tasks:
        proj_path, snap_path = ROOT / task["projection_path"], ROOT / task["snapshot_path"]
        if v310.file_sha256(proj_path) != task["projection_sha256"] or v310.file_sha256(snap_path) != task["snapshot_sha256"]:
            violations_all.append(f"{task['case_id']}:input_drift")
            continue
        projection, snapshot = load(proj_path), load(snap_path)
        report = v310.oracle_visibility_report_v310(projection, snapshot)
        reports[task["case_id"]] = report
        violations_all.extend(f"{task['case_id']}:{v}" for v in report["violations"])
    visible_count = sum(1 for r in reports.values() if r["visible"])
    check(visible_count == 90, f"oracle-expectations-subset-of-visible-contract gate: 90/90 visible (visible={visible_count})")
    check(not violations_all, f"no visibility violations across the full matrix (violations={violations_all[:5]})")

    # persisted fixture agreement
    persisted = load(ROOT / "tests/fixtures/acceptance_v3_10/oracle_visibility.report.json")
    check(persisted.get("all_visible") is True and len(persisted.get("cases", [])) == 90, "persisted visibility report fixture: all_visible, 90 cases")
    fixture_case_ids = {c["case_id"] for c in persisted.get("cases", [])}
    check(fixture_case_ids == set(reports), "persisted visibility report covers exactly the 90 in-plan case ids")
    mismatched_report = [c["case_id"] for c in persisted.get("cases", [])
                         if reports.get(c["case_id"], {}).get("violations") != c.get("violations")
                         or reports.get(c["case_id"], {}).get("conventions") != c.get("conventions")]
    check(not mismatched_report, f"re-run visibility reports byte-agree with persisted fixture (mismatched={mismatched_report[:5]})")

    # --- 2. negative scenarios: all 8 caught ---
    results = v310.run_gate_negative_scenarios_v310()
    required_ids = {
        "v3.6-fkw-03-undisclosed-six-decimal-convention",
        "v3.6-fkw-07-undisclosed-six-decimal-convention",
        "v3.10-fkw-02-average-undisclosed-six-decimal-convention",
        "v3.10-fkw-05-growth-undisclosed-six-decimal-convention",
        "contract-decimal-places-mismatch",
        "contract-rounding-mode-mismatch",
        "lexical-schema-waived",
        "contract-threshold-comparison-basis-mismatch",
    }
    found_ids = {s["id"] for s in results}
    check(found_ids == required_ids, f"exactly the 8 registered negative scenarios present (found {len(found_ids)})")
    check(all(s["caught"] for s in results), "8/8 negative scenarios caught by the gate")
    for s in results:
        ok = all(any(code in v for v in s["observed_violations"]) for code in s["expected_codes"])
        if not ok:
            check(False, f"scenario {s['id']} expected codes not observed")
    neg_persisted = load(ROOT / "tests/fixtures/acceptance_v3_10/oracle_visibility.negative.json")
    check(neg_persisted.get("all_caught") is True and len(neg_persisted.get("scenarios", [])) == 8, "persisted negative fixture: all_caught, 8 scenarios")
    persisted_by_id = {s["id"]: s for s in neg_persisted.get("scenarios", [])}
    check(all(persisted_by_id.get(s["id"], {}).get("projection_sha256") == s["projection_sha256"] for s in results),
          "re-run negative scenario projection hashes match persisted fixture (deterministic reproduction)")

    # --- 3. clean-room expectations vs registered Gold (my own comparison) ---
    mismatches = []
    ops_seen = set()
    for entry in v310.case_card_index():
        card = entry["card"]
        case_id = v310.projection_case_id(card)
        ops_seen.add(card["task"]["inputs"]["operation"])
        task = next(t for t in tasks if t["case_id"] == case_id)
        projection = load(ROOT / task["projection_path"])
        snapshot = load(ROOT / task["snapshot_path"])
        expected = v310.independent_expected_v310(projection, snapshot)
        oracle = card["oracle"]
        if expected["status"] != oracle["expected_status"]:
            mismatches.append(f"{case_id}:status")
        if sorted(expected["reason_codes"]) != sorted(oracle.get("reason_codes", [])):
            mismatches.append(f"{case_id}:reasons")
        ev, rv = expected.get("value"), oracle.get("expected_value")
        if (ev is None) != (rv is None):
            mismatches.append(f"{case_id}:value-shape")
        elif isinstance(ev, dict):
            for key in set(ev) | set(rv):
                a, b = ev.get(key), rv.get(key)
                if isinstance(a, str) and isinstance(b, str) and DEC_RE.fullmatch(a) and DEC_RE.fullmatch(b):
                    if Decimal(a) != Decimal(b):
                        mismatches.append(f"{case_id}:{key}")
                elif a != b:
                    mismatches.append(f"{case_id}:{key}")
    check(not mismatches, f"clean-room v3.10 expectations agree with Stage-2 registered Gold on 90/90 (bad={mismatches[:5]})")
    check(len(ops_seen) == 23, f"23 distinct registered operations exercised across the 90 tasks (found {len(ops_seen)})")

    # --- 4. quant disclosure scheme A ---
    quant_tasks = []
    for task in tasks:
        projection = load(ROOT / task["projection_path"])
        contract = projection.get("decimal_output_contract")
        expected = reports[task["case_id"]]
        quantized_fields = [f for f, c in expected["conventions"].items() if str(c).startswith("quantize_6")]
        if quantized_fields:
            quant_tasks.append((task["case_id"], contract, quantized_fields))
    check(len(quant_tasks) == 20, f"20 answer-status tasks carry quantized answer fields (10 quant families x 2 answering variants) (found {len(quant_tasks)})")
    disclosed = []
    for task in tasks:
        projection = load(ROOT / task["projection_path"])
        if projection.get("decimal_output_contract"):
            disclosed.append((task["case_id"], projection["decimal_output_contract"]))
    check(len(disclosed) == 30, f"30 tasks (10 FKW quant families x 3 variants) disclose the decimal contract (found {len(disclosed)})")
    check(all(cid.startswith("case-public-fkw") for cid, _ in disclosed), "quant disclosure confined to FKW quant families")
    check(len({f"FKW-{cid.split('-')[3]}" for cid, _ in disclosed}) == 10, "exactly 10 FKW quant families disclose")
    bad_contract = []
    for case_id, contract in disclosed:
        if contract.get("value_decimal_places") != 6 or contract.get("rounding_mode") != "ROUND_HALF_EVEN":
            bad_contract.append(f"{case_id}:params")
        if contract.get("value_pattern") != v310.SIX_PATTERN or contract.get("absolute_tolerance") != "0.0000005":
            bad_contract.append(f"{case_id}:lexical")
        if contract.get("registered_decimal_basis") != v310.REGISTERED_DECIMAL_BASIS:
            bad_contract.append(f"{case_id}:basis")
        if contract.get("tolerance_does_not_waive_lexical_schema") is not True or contract.get("intermediate_rounding") is not False:
            bad_contract.append(f"{case_id}:waiver")
        if contract.get("arithmetic_significant_digits_minimum") != 34 or not contract.get("input_precision"):
            bad_contract.append(f"{case_id}:precision")
    check(not bad_contract, f"scheme-A disclosure complete on all 30 disclosed tasks (bad={bad_contract[:5]})")
    for case_id, contract, fields in quant_tasks:
        if str(contract.get("value_field", "value")) not in fields:
            bad_contract.append(f"{case_id}:value_field_not_quantized")
    check(not bad_contract, f"value_field points at the quantized field on every answer-status quant task (bad={bad_contract[:5]})")
    ftw_with_contract = [t["case_id"] for t in tasks if t["case_id"].startswith("case-synthetic") and load(ROOT / t["projection_path"]).get("decimal_output_contract")]
    check(not ftw_with_contract, f"no FTW task discloses a decimal contract (exact differences stay exact) (bad={ftw_with_contract})")

    # --- 5. hidden-label leakage scan over candidate-visible artifacts ---
    hidden_keys = ["force_abstain_reason", "diagnostic_reason"]
    leaks = []
    for task in tasks:
        projection = load(ROOT / task["projection_path"])
        if any(k in projection["task"]["inputs"] for k in hidden_keys):
            leaks.append(f"{task['case_id']}:projection_inputs")
        if any(k in json.dumps(projection.get("task", {})) for k in hidden_keys):
            leaks.append(f"{task['case_id']}:projection_task")
    for visible_path in [
        "contracts/candidate_output_contracts.v3.10.json",
        "contracts/candidate_submission_wire_contract.v3.10.json",
        "contracts/reason_codes.v3.10.json",
        "contracts/run_trace_harness_config.v3.10.json",
    ]:
        text = (ROOT / visible_path).read_text(encoding="utf-8")
        for key in hidden_keys:
            if key in text:
                leaks.append(f"{visible_path}:{key}")
    check(not leaks, f"hidden Stage-2 labels absent from every candidate-visible artifact (leaks={leaks})")

    # observable-fact replacement registered and symmetric
    check(set(v310.HIDDEN_LABEL_FACTS) == {
        "REVISION_HISTORY_UNAVAILABLE", "AMBIGUOUS_SOURCE_AUTHORITY", "OCR_AMBIGUITY",
        "FORECAST_MODEL_UNAVAILABLE", "RATE_LIMIT_OBSERVABILITY_INCOMPLETE",
        "RECOVERY_MESSAGE_ORDER_UNRESOLVED", "PROVIDER_FIELD_ALIAS_AMBIGUOUS"},
        "hidden-label -> observable-fact mapping registered for all label-bearing Gold codes")

    # --- 6. reason vocabulary 18 -> 21 ---
    doc39 = load(ROOT / "contracts/reason_codes.v3.9.json")
    doc310 = load(ROOT / "contracts/reason_codes.v3.10.json")
    check(len(doc39["definitions"]) == 18, f"v3.9 vocabulary == 18 codes (found {len(doc39['definitions'])})")
    check(len(doc310["definitions"]) == 21, f"v3.10 vocabulary == 21 codes (found {len(doc310['definitions'])})")
    new_codes = set(doc310["definitions"]) - set(doc39["definitions"])
    check(new_codes == {"BOUNDED_RETRY_SUCCEEDED", "FORECAST_MODEL_UNAVAILABLE", "PROVIDER_FIELD_ALIAS_AMBIGUOUS"},
          f"exactly 3 new codes (found {sorted(new_codes)})")
    unchanged = [c for c in doc39["definitions"] if doc39["definitions"][c] != doc310["definitions"].get(c)]
    check(set(unchanged) <= {"INSUFFICIENT_EVIDENCE"}, f"18 prior definitions unchanged except documented INSUFFICIENT_EVIDENCE suppression (changed={unchanged})")
    check(doc310["definitions"]["INSUFFICIENT_EVIDENCE"]["suppresses"] == ["TOOL_TEXT_TREATED_AS_DATA"],
          "INSUFFICIENT_EVIDENCE now suppresses TOOL_TEXT_TREATED_AS_DATA (registered parity repair)")
    check(doc310["definitions"]["BOUNDED_RETRY_SUCCEEDED"]["allowed_statuses"] == ["answer"], "BOUNDED_RETRY_SUCCEEDED allowed only with answer")
    check(doc310["definitions"]["FORECAST_MODEL_UNAVAILABLE"]["allowed_statuses"] == ["abstain", "escalate"], "FORECAST_MODEL_UNAVAILABLE statuses")
    check(doc310["definitions"]["PROVIDER_FIELD_ALIAS_AMBIGUOUS"]["allowed_statuses"] == ["abstain", "escalate"], "PROVIDER_FIELD_ALIAS_AMBIGUOUS statuses")
    check(len(doc310["case_sets"]) == 90, "reason doc case_sets cover 90 cases")
    bad_sets = [cid for cid, cs in doc310["case_sets"].items() if cs["required"] != cs["allowed"] or cs["status"] not in {"answer", "abstain", "escalate", "reject_action"}]
    check(not bad_sets, f"all 90 case_sets have required==allowed and valid status (bad={bad_sets[:5]})")

    # --- 7. three-model symmetry & v3.9 zero-drift in config ---
    cfg39 = load(ROOT / "contracts/run_trace_harness_config.v3.9.json")
    cfg310 = load(ROOT / "contracts/run_trace_harness_config.v3.10.json")
    for key in ["request_commitments", "resource_budget", "provider_retry_policy", "system_prompt", "tool_names", "security"]:
        check(json.dumps(cfg310[key], sort_keys=True) == json.dumps(cfg39[key], sort_keys=True), f"config.{key} byte-identical to v3.9")
    params_by_model = cfg310["request_commitments"]["parameters_by_model"]
    check(sorted(params_by_model) == sorted(["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]), f"parameter commitments cover exactly the 3 models ({sorted(params_by_model)})")
    common_keys = set.intersection(*(set(p) for p in params_by_model.values()))
    asymmetric = []
    for key in sorted(common_keys):
        values = {params_by_model[m][key] for m in params_by_model}
        if len(values) != 1:
            asymmetric.append(key)
    check(not asymmetric, f"all shared request parameters identical across the 3 models (asymmetric={asymmetric})")
    extra = {m: sorted(set(p) - common_keys) for m, p in params_by_model.items() if set(p) - common_keys}
    check(extra == {"qwen3.8-max": ["enable_thinking"]} and params_by_model["qwen3.8-max"]["enable_thinking"] is False,
          f"only documented adapter-level extra is qwen enable_thinking=false (extra={extra})")
    # per-model parameter hashes bind the committed parameters
    for model, params in params_by_model.items():
        digest = hashlib.sha256(json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if digest != cfg310["request_commitments"]["parameters_sha256_by_model"][model]:
            check(False, f"parameter commitment hash mismatch for {model}")
            break
    else:
        check(True, "per-model parameter commitment hashes re-derived from committed parameters")
    check(cfg310["fairness"]["same_prompt_tools_budget_retry_grader_for_all_models"] is True, "fairness flag true")
    check(cfg310["execution"]["paid_calls_authorized"] is False and cfg310["execution"]["offline_validation_only"] is True, "config execution stays offline, unpaid")
    check(cfg310["execution"]["case_count"] == 90 and cfg310["execution"]["planned_run_cap"] == 810, "config execution scope 90/810")

    # --- 8. previously covered: 9 byte-identical, 3 documented repairs ---
    plan_v39 = load(ROOT / "contracts/stage3_acceptance_plan.v3.9.json")
    documented = {
        "case-synthetic-ftw-12-missing-or-anomalous-v3",
        "case-synthetic-ftw-11-missing-or-anomalous-v3",
        "case-synthetic-ftw-07-missing-or-anomalous-v3",
    }
    changed, identical = [], []
    for task in plan_v39["tasks"]:
        snapshot = load(ROOT / task["snapshot_path"])
        v39_projection = load(ROOT / task["projection_path"])
        v310_projection = load(ROOT / "cases/candidate_v3_10" / f"{task['case_id']}.json")
        exp39 = v37.independent_expected_from_snapshot(v39_projection, snapshot)
        exp310 = v310.independent_expected_v310(v310_projection, snapshot)
        if json.dumps(exp39, sort_keys=True) == json.dumps(exp310, sort_keys=True):
            identical.append(task["case_id"])
        else:
            changed.append(task["case_id"])
    check(set(changed) == documented, f"exactly the 3 documented cases change expectations (changed={sorted(changed)})")
    check(len(identical) == 9, f"9 previously covered cases byte-identical expectations (found {len(identical)})")

    # documented repair directions match registered Gold (cross-check vs cards)
    for case_id in sorted(documented):
        task = next(t for t in tasks if t["case_id"] == case_id)
        projection = load(ROOT / task["projection_path"])
        snapshot = load(ROOT / task["snapshot_path"])
        exp = v310.independent_expected_v310(projection, snapshot)
        check(exp["reason_codes"] == ["INSUFFICIENT_EVIDENCE"] and exp["status"] == "abstain",
              f"{case_id}: v3.10 expectation == abstain/INSUFFICIENT_EVIDENCE (registered Gold)")

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)} failures)")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("RESULT: PASS — all part-3 checks green")


if __name__ == "__main__":
    main()
