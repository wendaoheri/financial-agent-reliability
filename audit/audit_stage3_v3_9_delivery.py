"""Independent delivery audit of the PER-48 v3.9 superseding contracts (PER-51).

Auditor: independent scoring & statistics auditor (separated from case authoring,
oracle, and harness implementation). Read-only audit: this script never writes
frozen artifacts, never reads credentials, and never triggers provider calls.

Hashing primitives below are a clean-room re-implementation of the canonical
hash convention (sorted-key compact JSON, UTF-8, SHA-256). They are NOT
imported from the harness under audit. The oracle (`independent_expected_from_snapshot`)
and the new visibility gate are imported only because they are themselves
hash-locked frozen artifacts under audit (v3.7 bundle artifacts).

Usage:
    uv run python -m audit.audit_stage3_v3_9_delivery
Prints one line per check and a final `total checks=N failures=M` /
`AUDIT_VERDICT=PASS|FAIL` line.
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- declared values (implementation-side claims to verify) -----------------
# PER-52 re-declaration: the four v3.9 values below were updated to the re-frozen
# hashes after the minimal fix of semantic_bindings.calculation; every other
# declared value is unchanged from PER-51.
DECLARED = {
    "v3_9_bundle": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "v3_9_plan": "235b0415bf43c356a5f2c3801a7793606ed5e943a5e8ce60f0aa3b20abeeb185",
    "v3_9_plan_core": "bf1d1ed48b0f5728b0f2f71bcd13af91dc7a9ed586c0f2ffbe9cebaf7e804ebd",
    "v3_9_config": "e06b3fae6acf1ab76716c3a507163601fa6249f6160a8dbfce1216f8080e0cfa",
    "proj_fkw03": "9a1cb68f7bfd0fbd106c712ea3cefc76cafc6de5429be22f217d1150ecf6e4f2",
    "proj_fkw07": "9d7605a5127310d08207b1131e3a5a7a76467b84f1b570c253771a2964b0483a",
    "v3_5_bundle": "d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8",
    "v3_6_bundle": "afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959",
    "v3_7_bundle": "354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44",
    "v3_8_bundle": "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609",
    "v3_8_plan": "636d94fbb6d08d58adfd018dfba6115bb44ac193480a5380e3228c623a4c3d22",
    "v3_8_plan_core": "f272700eddfb1e91d405ab30079dd93324dd87eda666a164d10ede81cff666ae",
    "audit_report_v3_8": "ba5fbd7a49507a7f04ddd7f90273d0bda0b4433f97cde206067a48a921b1e076",
    "oracle_file": "9097915075c71bf6344cfadbe0486c508259dd5de8dd47d6c325fccde169858d",
}
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
SIX_PATTERN = r"^-?\d+\.\d{6}$"
FKW03 = "case-public-fkw-03-single-factor-perturbation-v3"
FKW07 = "case-public-fkw-07-single-factor-perturbation-v3"

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(f"[{'ok' if ok else 'FAIL'}] {label}")


# --- independent canonical-hash re-implementation (clean room) ---------------


def my_canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def my_content_sha256(value: Any) -> str:
    return hashlib.sha256(my_canonical(value).encode("utf-8")).hexdigest()


def my_file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def my_build_run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{my_content_sha256(dict(identity))[:32]}"


# --- subjects under audit (hash-locked frozen artifacts) ---------------------
# harness/acceptance_v3_7.py is an artifact of the frozen v3.7 bundle; its hash
# is verified below before any result derived from it is trusted.
from harness.acceptance_v3_7 import independent_expected_from_snapshot, tool_schemas_v37  # noqa: E402
from harness.acceptance_v3_9 import (  # noqa: E402
    oracle_visibility_report,
    run_gate_negative_scenarios,
    visibility_gate_errors,
)


def main() -> None:
    # =========================================================================
    # A. frozen-hash recomputation (v3.5-v3.9) and supersedes chain
    # =========================================================================
    b39 = read_json(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.9.json")
    p39 = read_json(ROOT / "contracts/stage3_acceptance_plan.v3.9.json")
    cfg39_path = ROOT / "contracts/run_trace_harness_config.v3.9.json"

    # A1 v3.9 bundle hash + artifact list
    artifacts = b39["artifacts"]
    check(len(artifacts) == 21, f"A1a v3.9 bundle artifact count == 21 (found {len(artifacts)})")
    artifact_drift = [a["path"] for a in artifacts if not (ROOT / a["path"]).is_file() or my_file_sha256(ROOT / a["path"]) != a["sha256"]]
    check(not artifact_drift, f"A1b v3.9 bundle 21/21 artifact file hashes match (drift: {artifact_drift})")
    recomputed_bundle = my_content_sha256(artifacts)
    check(recomputed_bundle == DECLARED["v3_9_bundle"] == b39["bundle_sha256"],
          f"A1c v3.9 bundle_sha256 independent recompute == declared {DECLARED['v3_9_bundle'][:12]}...")

    # A2 v3.9 projection hashes
    check(my_file_sha256(ROOT / f"cases/candidate_v3_9/{FKW03}.json") == DECLARED["proj_fkw03"], "A2a fkw-03 v3.9 projection hash matches declared")
    check(my_file_sha256(ROOT / f"cases/candidate_v3_9/{FKW07}.json") == DECLARED["proj_fkw07"], "A2b fkw-07 v3.9 projection hash matches declared")

    # A3 v3.9 config hash
    cfg39_hash = my_file_sha256(cfg39_path)
    check(cfg39_hash == DECLARED["v3_9_config"], "A3 v3.9 config file hash matches declared")

    # A4 v3.9 plan hash + plan_core + run identities
    plan_for_hash = {k: v for k, v in p39.items() if k != "plan_sha256"}
    check(my_content_sha256(plan_for_hash) == DECLARED["v3_9_plan"] == p39["plan_sha256"],
          "A4a v3.9 plan_sha256 independent recompute == declared")
    check(p39["plan_core_sha256"] == DECLARED["v3_9_plan_core"], "A4b v3.9 plan_core_sha256 matches declared")
    tasks39 = p39["tasks"]
    check(len(tasks39) == 12 and len(p39["runs"]) == 36 and p39["run_cap"] == 36, "A4c v3.9 plan: 12 tasks, 36 runs, run_cap 36")
    core_inputs = []
    for task in tasks39:
        proj_hash = my_file_sha256(ROOT / task["projection_path"])
        snap_hash = my_file_sha256(ROOT / task["snapshot_path"])
        tool_hash = my_content_sha256(tool_schemas_v37(read_json(ROOT / task["projection_path"])))
        check(proj_hash == task["projection_sha256"] and snap_hash == task["snapshot_sha256"] and tool_hash == task["tool_schema_sha256"],
              f"A4d task input hashes recompute: {task['case_id']}")
        core_inputs.append({k: task[k] for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]})
    core = {"contract_version": "3.9.0", "config_sha256": cfg39_hash, "models": MODELS, "task_inputs": core_inputs}
    check(my_content_sha256(core) == DECLARED["v3_9_plan_core"], "A4e v3.9 plan_core independently reconstructed from documented fields")
    bad_identity = []
    for row in p39["runs"]:
        identity = row["run_identity"]
        if my_build_run_id(identity) != row["run_id"]:
            bad_identity.append(row["run_id"])
        if identity.get("plan_core_sha256") != p39["plan_core_sha256"] or identity.get("harness_config_sha256") != cfg39_hash:
            bad_identity.append(f"{row['run_id']}:binding")
        if identity.get("benchmark_id") != "financial-agent-reliability-v3.9" or identity.get("repeat") != 1:
            bad_identity.append(f"{row['run_id']}:benchmark")
    check(not bad_identity, f"A4f 36/36 run_id == run_sha256(run_identity)[:32] with plan/config binding (bad: {bad_identity})")
    task_run_ids = {rid for task in tasks39 for rid in task["run_ids"]}
    check(task_run_ids == {row["run_id"] for row in p39["runs"]} and len(task_run_ids) == 36, "A4g task.run_ids and plan.runs are the same 36 unique ids")
    per_case_models = {task["case_id"]: sorted(next(r["model_id"] for r in p39["runs"] if r["run_id"] == rid) for rid in task["run_ids"]) for task in tasks39}
    check(all(models == sorted(MODELS) for models in per_case_models.values()), "A4h every case carries exactly the three registered models")

    # A5 historical bundles zero-drift (v3.5-v3.8)
    prior = [("3.5", DECLARED["v3_5_bundle"]), ("3.6", DECLARED["v3_6_bundle"]), ("3.7", DECLARED["v3_7_bundle"]), ("3.8", DECLARED["v3_8_bundle"])]
    for version, wanted in prior:
        bundle = read_json(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        drift = [a["path"] for a in bundle.get("artifacts", []) if not (ROOT / a["path"]).is_file() or my_file_sha256(ROOT / a["path"]) != a["sha256"]]
        check(bundle.get("bundle_sha256") == wanted and not drift,
              f"A5 v{version} bundle hash + {len(bundle.get('artifacts', []))} artifact hashes zero-drift (drift: {drift})")

    # A6 v3.7 oracle artifact lock (clean-room oracle used by the v3.9 grader)
    v37_bundle = read_json(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.7.json")
    v37_artifacts = {a["path"]: a["sha256"] for a in v37_bundle["artifacts"]}
    check(v37_artifacts.get("harness/acceptance_v3_7.py") == my_file_sha256(ROOT / "harness/acceptance_v3_7.py"),
          "A6 harness/acceptance_v3_7.py (clean-room oracle) hash-locked in frozen v3.7 bundle")

    # A7 v3.8 plan hash + supersedes chain
    p38 = read_json(ROOT / "contracts/stage3_acceptance_plan.v3.8.json")
    check(my_content_sha256({k: v for k, v in p38.items() if k != "plan_sha256"}) == DECLARED["v3_8_plan"] == p38["plan_sha256"],
          "A7a v3.8 plan_sha256 independent recompute == declared")
    check(p38["plan_core_sha256"] == DECLARED["v3_8_plan_core"], "A7b v3.8 plan_core_sha256 matches declared")
    check(p39["supersedes"]["path"] == "contracts/stage3_acceptance_plan.v3.8.json"
          and p39["supersedes"]["sha256"] == my_file_sha256(ROOT / "contracts/stage3_acceptance_plan.v3.8.json")
          and p39["supersedes"]["plan_sha256"] == p38["plan_sha256"], "A7c v3.9 plan supersedes v3.8 (file hash + plan hash)")
    check(b39["supersedes"]["path"] == "contracts/stage3_acceptance_contracts.frozen.v3.8.json"
          and b39["supersedes"]["sha256"] == my_file_sha256(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.8.json")
          and b39["supersedes"]["v3_8_bundle_sha256"] == DECLARED["v3_8_bundle"], "A7d v3.9 bundle supersedes v3.8 (file hash + bundle hash)")
    cfg39 = read_json(cfg39_path)
    check(cfg39["supersedes"]["path"] == "contracts/run_trace_harness_config.v3.8.json"
          and cfg39["supersedes"]["sha256"] == my_file_sha256(ROOT / "contracts/run_trace_harness_config.v3.8.json"), "A7e v3.9 config supersedes v3.8 config")
    for cid in (FKW03, FKW07):
        proj = read_json(ROOT / f"cases/candidate_v3_9/{cid}.json")
        src = ROOT / f"cases/candidate_v3_6/{cid}.json"
        check(proj["supersedes"]["path"] == f"cases/candidate_v3_6/{cid}.json" and proj["supersedes"]["sha256"] == my_file_sha256(src),
              f"A7f {cid} v3.9 projection supersedes v3.6 source")
    # historical bundle supersedes chain (v3.6 -> v3.5 ... v3.8 -> v3.7)
    chain_ok = True
    for version, prev in [("3.6", "3.5"), ("3.7", "3.6"), ("3.8", "3.7")]:
        bundle = read_json(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        prev_path = ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{prev}.json"
        sup = bundle.get("supersedes") or {}
        if not (isinstance(sup, Mapping) and sup.get("sha256") == my_file_sha256(prev_path)):
            chain_ok = False
    check(chain_ok, "A7g historical bundle supersedes chain v3.5<-v3.6<-v3.7<-v3.8 file-hash consistent")
    # preserved block
    check(b39["preserved"] == {"v3_5_bundle_sha256": DECLARED["v3_5_bundle"], "v3_6_bundle_sha256": DECLARED["v3_6_bundle"],
                               "v3_7_bundle_sha256": DECLARED["v3_7_bundle"], "v3_8_bundle_sha256": DECLARED["v3_8_bundle"],
                               "retroactive_regrading": False}, "A7h preserved block pins all four historical bundle hashes, retroactive_regrading=false")

    # A8 run-identity churn: v3.8 vs v3.9 disjoint, seeds/models preserved
    ids38 = {row["run_id"] for row in p38["runs"]}
    ids39 = {row["run_id"] for row in p39["runs"]}
    check(not (ids38 & ids39), "A8a v3.8 ∩ v3.9 run ids == ∅ (all 36 identities renewed)")
    seed38 = {(row["model_id"], row["seed"]) for row in p38["runs"]}
    seed39 = {(row["model_id"], row["seed"]) for row in p39["runs"]}
    check(seed38 == seed39, "A8b (model_id, seed) multiset preserved v3.8 -> v3.9")
    by_case_38 = {task["case_id"]: sorted(task["run_ids"]) for task in p38["tasks"]}
    check({task["case_id"] for task in tasks39} == set(by_case_38), "A8c same 12 case ids in v3.8 and v3.9 plans")

    # =========================================================================
    # B. repair content: audit option A, PER-28 derivation, three-model symmetry
    # =========================================================================
    snap03 = read_json(ROOT / "snapshots/public/v2/data_snapshot.FKW-03.json")
    snap07 = read_json(ROOT / "snapshots/public/v2/data_snapshot.FKW-07.json")
    proj03_39 = read_json(ROOT / f"cases/candidate_v3_9/{FKW03}.json")
    proj07_39 = read_json(ROOT / f"cases/candidate_v3_9/{FKW07}.json")

    # B1 independent arithmetic against the frozen PER-28 oracle convention
    with localcontext() as ctx:
        ctx.prec = 34
        raw03 = next(Decimal(str(r["payload"]["value"])) for r in snap03["records"] if str(r["payload"].get("year")) == "2023")
        quotient = raw03 / Decimal("1000000000")
        q03 = format(quotient.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), ".6f")
        values07 = [Decimal(str(r["payload"]["value"])) for r in snap07["records"]]
        mean07 = sum(values07) / Decimal(len(values07))
        q07 = format(mean07.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), ".6f")
    check(q03 == "0.000035", f"B1a independent Decimal recompute fkw-03 quotient quantized 6dp HALF_EVEN == '0.000035' (got {q03})")
    check(q07 == "6.073667", f"B1b independent Decimal recompute fkw-07 mean quantized 6dp HALF_EVEN == '6.073667' (got {q07})")
    check(str(raw03) == "35215.003535366", f"B1c fkw-03 source record value is 35215.003535366 (got {raw03})")

    # B2 registered expected values predate the v3.8 run; oracle file hash-locked
    card03 = read_json(ROOT / "cases/public/case_card.FKW-03.single_factor_perturbation.json")
    card07 = read_json(ROOT / "cases/public/case_card.FKW-07.single_factor_perturbation.json")
    check(card03["oracle"]["expected_value"] == {"divisor": "1000000000", "scaled_value": "0.000035"}, "B2a FKW-03 case-card registered expected value == '0.000035'")
    check(card07["oracle"]["expected_value"] == {"method": "three_year_average", "value": "6.073667"}, "B2b FKW-07 case-card registered expected value == '6.073667'")
    check(card03["oracle"]["implementation_sha256"] == DECLARED["oracle_file"] == my_file_sha256(ROOT / "cases/public/oracle.py"),
          "B2c cases/public/oracle.py file hash == PER-28 registered implementation_sha256")
    check(card03["lineage"]["generated_at"] == "2026-08-11T02:00:00Z" and card07["lineage"]["generated_at"] == "2026-08-11T02:00:00Z",
          "B2d case cards generated 2026-08-11T02:00Z, before the v3.8 run window (2026-08-12 13:54-14:13 UTC)")
    # PER-28 oracle convention text check: quantize 1e-6 ROUND_HALF_EVEN
    oracle_src = (ROOT / "cases/public/oracle.py").read_text(encoding="utf-8")
    check('SCALE = Decimal("0.000001")' in oracle_src and "ROUND_HALF_EVEN" in oracle_src and "quantize(SCALE" in oracle_src,
          "B2e PER-28 oracle source quantizes to 1e-6 ROUND_HALF_EVEN")

    # B3 disclosure is NOT back-derived from v3.8 candidate answers
    ev_dir = ROOT / "evidence/stage3/acceptance-20260812-v3.8/candidates"
    task03_38 = next(t for t in p38["tasks"] if t["case_id"] == FKW03)
    v38_answers03 = [read_json(ev_dir / f"{rid}.json")["value"] for rid in task03_38["run_ids"]]
    check(all(a == {"divisor": "1000000000", "scaled_value": "0.000035215003535366"} for a in v38_answers03),
          "B3a all three v3.8 fkw-03 candidates submitted the exact quotient 0.000035215003535366")
    check(all(a["scaled_value"] != "0.000035" for a in v38_answers03),
          "B3b disclosed value '0.000035' differs from every v3.8 candidate answer -> not back-derived")

    # B4 option-A contract content, isomorphic to FKW-12's frozen v3.6 contract
    proj12_36 = read_json(ROOT / "cases/candidate_v3_6/case-public-fkw-12-normal-v3.json")
    ref = proj12_36["decimal_output_contract"]
    for cid, proj, field in [(FKW03, proj03_39, "scaled_value"), (FKW07, proj07_39, "value")]:
        contract = proj.get("decimal_output_contract") or {}
        shared_ok = (
            contract.get("value_decimal_places") == ref["value_decimal_places"] == 6
            and contract.get("rounding_mode") == ref["rounding_mode"] == "ROUND_HALF_EVEN"
            and contract.get("value_pattern") == ref["value_pattern"] == SIX_PATTERN
            and contract.get("absolute_tolerance") == ref["absolute_tolerance"] == "0.0000005"
            and contract.get("tolerance_does_not_waive_lexical_schema") is True
            and contract.get("arithmetic_significant_digits_minimum") == ref["arithmetic_significant_digits_minimum"] == 34
            and contract.get("intermediate_rounding") is False
            and contract.get("input_precision") == ref["input_precision"]
        )
        check(shared_ok, f"B4a {cid}: decimal_output_contract isomorphic to frozen FKW-12 v3.6 contract")
        check(contract.get("value_field") == field and proj["answer_value_schema"]["properties"][field].get("pattern") == SIX_PATTERN,
              f"B4b {cid}: value_field={field} and lexical schema pattern tightened to the 6dp pattern (no waiver)")
        tol_ok = Decimal(contract["absolute_tolerance"]) == Decimal("0.0000005") == Decimal("0.000001") / 2
        check(tol_ok, f"B4c {cid}: tolerance 0.0000005 == half of the 1e-6 quantum (financially consistent with half-even rounding)")
    # B5 three-model symmetry: disclosures are per-case, plan fairness intact
    check(p39["fairness"] == {"same_prompt_tools_budget_retry_grader": True, "models": MODELS}, "B5a plan.fairness asserts same prompt/tools/budget/retry/grader for the 3 models")
    v39_src = (ROOT / "harness/acceptance_v3_9.py").read_text(encoding="utf-8")
    model_refs = [line for line in v39_src.splitlines() if any(m in line for m in MODELS)]
    benign = all(("MODELS" in line or "__MODEL_GUARD_" in line or "guarded" in line or "_fixture_trace(" in line or line.strip().startswith("#")) for line in model_refs)
    check(benign, f"B5b no per-model semantic special-casing in harness/acceptance_v3_9.py ({len(model_refs)} model-id references: MODELS constant, schema guard, synthetic-fixture builder only)")
    cfg38 = read_json(ROOT / "contracts/run_trace_harness_config.v3.8.json")
    check(set(cfg39["request_commitments"]["parameters_sha256_by_model"]) == set(MODELS)
          and cfg39["request_commitments"]["parameters_sha256_by_model"] == cfg38["request_commitments"]["parameters_sha256_by_model"],
          "B5c per-model request parameter commitments cover exactly the 3 models and are unchanged from v3.8")

    # =========================================================================
    # C. disclosure-only diff and oracle immutability
    # =========================================================================
    IGNORED = {"contract_version", "supersedes", "decimal_output_contract", "answer_value_schema"}
    for cid, field in [(FKW03, "scaled_value"), (FKW07, "value")]:
        old = read_json(ROOT / f"cases/candidate_v3_6/{cid}.json")
        new = read_json(ROOT / f"cases/candidate_v3_9/{cid}.json")
        changed = [k for k in set(old) | set(new) if k not in IGNORED and my_canonical(old.get(k)) != my_canonical(new.get(k))]
        check(not changed, f"C1a {cid}: projection diff outside version/supersedes/schema/new contract is empty (changed: {changed})")
        old_schema, new_schema = old["answer_value_schema"], new["answer_value_schema"]
        same_fields = set(old_schema["properties"]) == set(new_schema["properties"]) and old_schema["required"] == new_schema["required"]
        field_changes = {}
        if same_fields:
            for fname, fschema in old_schema["properties"].items():
                diffs = {k for k in set(fschema) | set(new_schema["properties"][fname]) if my_canonical(fschema.get(k)) != my_canonical(new_schema["properties"][fname].get(k))}
                if diffs:
                    field_changes[fname] = diffs
        check(same_fields and field_changes == {field: {"pattern"}},
              f"C1b {cid}: answer schema changed only {field}.pattern (changes: {field_changes})")
        check(old_schema["properties"][field].get("pattern") != SIX_PATTERN and re.fullmatch(old_schema["properties"][field].get("pattern", ""), "0.000035215003535366") is not None,
              f"C1c {cid}: v3.6 pattern was loose (accepted arbitrary decimals incl. the exact quotient)")
    # C2 oracle expected values byte-identical for all 12 cases (v3.8-era projections vs v3.9 projections)
    mismatch = []
    for task39 in tasks39:
        cid = task39["case_id"]
        task38 = next(t for t in p38["tasks"] if t["case_id"] == cid)
        snapshot = read_json(ROOT / task39["snapshot_path"])
        exp_new = independent_expected_from_snapshot(read_json(ROOT / task39["projection_path"]), snapshot)
        exp_old = independent_expected_from_snapshot(read_json(ROOT / task38["projection_path"]), snapshot)
        if my_canonical(exp_new) != my_canonical(exp_old):
            mismatch.append(cid)
        if task39["snapshot_path"] != task38["snapshot_path"] or task39["snapshot_sha256"] != task38["snapshot_sha256"]:
            mismatch.append(f"{cid}:snapshot-moved")
    check(not mismatch, "C2 12/12 oracle expected values canonical-identical v3.8-era vs v3.9 projections; snapshots unmoved")
    # C3 repair metadata claims
    check(b39["audit_repair"]["audit_report_sha256"] == DECLARED["audit_report_v3_8"]
          and my_file_sha256(ROOT / "audit/stage3-v3.8-delivery-audit-20260812.md") == DECLARED["audit_report_v3_8"],
          "C3a audit_repair binds the v3.8 delivery audit report; report file hash verified")
    check(b39["audit_repair"]["audit_recommendation"] == "A_candidate_visible_decimal_output_contract"
          and sorted(b39["audit_repair"]["changed_projection_case_ids"]) == sorted([FKW03, FKW07]), "C3b audit_repair names option A and exactly the two repaired cases")
    check(cfg39["contract_repair"]["oracle_behavior_changed"] is False and cfg39["contract_repair"]["candidate_answers_back_derived"] is False,
          "C3c config contract_repair declares oracle unchanged and no back-derivation")

    # =========================================================================
    # D. visibility gate: positive/negative reproduction and v3.8 replay
    # =========================================================================
    # D1 independent mini-probe (clean-room): the v3.6 fkw-03 oracle quantizes
    # and the v3.6 projection discloses nothing -> the defect the gate must catch.
    proj03_36 = read_json(ROOT / f"cases/candidate_v3_6/{FKW03}.json")
    base_expected = independent_expected_from_snapshot(proj03_36, snap03)
    probed = []
    for probe in ["12.345678912345", "2.0000025", "2.0000035"]:
        mutated = copy.deepcopy(snap03)
        for record in mutated["records"]:
            if str(record["payload"].get("year")) == "2023":
                with localcontext() as ctx:
                    ctx.prec = 34
                    planted = Decimal(probe) * Decimal("1000000000")
                record["payload"]["value"] = format(planted, "f").rstrip("0").rstrip(".")
        observed = independent_expected_from_snapshot(proj03_36, mutated)["value"]["scaled_value"]
        with localcontext() as ctx:
            ctx.prec = 34
            exact = Decimal(probe)
        is_quantized = observed == format(exact.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), ".6f")
        is_exact = observed == format(exact, "f").rstrip("0").rstrip(".")
        probed.append((probe, observed, is_quantized, is_exact))
    all_quantized = all(p[2] and not p[3] for p in probed)
    check(all_quantized, f"D1a independent probe: v3.6 fkw-03 oracle renders 6dp HALF_EVEN for probes {[(p[0], p[1]) for p in probed]}")
    check("decimal_output_contract" not in proj03_36 and "decimal_output_contract" not in read_json(ROOT / "cases/candidate_v3_6/case-public-fkw-07-single-factor-perturbation-v3.json"),
          "D1b v3.6 fkw-03/fkw-07 projections contain no decimal_output_contract (defect real)")
    # rounding-mode discrimination: 2.0000025 -> HALF_EVEN gives 2.000002, HALF_UP gives 2.000003
    tie = next(p for p in probed if p[0] == "2.0000025")
    check(tie[1] == "2.000002", "D1c tie probe 2.0000025 -> 2.000002 discriminates ROUND_HALF_EVEN (not HALF_UP)")

    # D2 gate replay over the frozen v3.8 task set: exactly fkw-03/fkw-07 violate
    gate_errors_38 = visibility_gate_errors(p38)
    violated_cases = sorted({err.split(":")[1] for err in gate_errors_38 if err.startswith("oracle visibility violation:")})
    check(violated_cases == sorted([FKW03, FKW07]), f"D2a gate over frozen v3.8 task set violates exactly fkw-03/fkw-07 (got {violated_cases})")
    check(all("undisclosed_quantization_convention" in err for err in gate_errors_38) and len(gate_errors_38) == 2,
          f"D2b both violations are undisclosed_quantization_convention ({len(gate_errors_38)} errors)")
    # D3 gate over v3.9 plan: 12/12 visible
    gate_errors_39 = visibility_gate_errors(p39)
    check(not gate_errors_39, f"D3a gate over v3.9 plan: 0 violations (got {gate_errors_39})")
    fixture_report = read_json(ROOT / "tests/fixtures/acceptance_v3_9/oracle_visibility.report.json")
    check(fixture_report["all_visible"] is True and len(fixture_report["cases"]) == 12, "D3b frozen fixture oracle_visibility.report.json: 12/12 visible")
    live_cases = [oracle_visibility_report(read_json(ROOT / t["projection_path"]), read_json(ROOT / t["snapshot_path"])) for t in tasks39]
    check(all(c["visible"] for c in live_cases) and [c["case_id"] for c in live_cases] == [c["case_id"] for c in fixture_report["cases"]],
          "D3c independently re-run gate report == frozen fixture (case order and visibility)")
    # D4 negative scenarios: 5/5 caught, re-run matches frozen fixture
    negative_fixture = read_json(ROOT / "tests/fixtures/acceptance_v3_9/oracle_visibility.negative.json")
    negative_live = run_gate_negative_scenarios()
    check(negative_fixture["all_caught"] is True and len(negative_fixture["scenarios"]) == 5, "D4a frozen negative fixture: 5 scenarios all caught")
    check([(s["id"], s["caught"], s["observed_violations"]) for s in negative_live] == [(s["id"], s["caught"], s["observed_violations"]) for s in negative_fixture["scenarios"]],
          "D4b independently re-run negative scenarios == frozen fixture (5/5 caught)")
    neg_ids = [s["id"] for s in negative_live]
    check(neg_ids == ["v3.6-fkw-03-undisclosed-six-decimal-convention", "v3.6-fkw-07-undisclosed-six-decimal-convention",
                      "contract-decimal-places-mismatch", "contract-rounding-mode-mismatch", "lexical-schema-waived"],
          f"D4c negative scenarios cover both historical defects + digits/rounding/waiver mutations (got {neg_ids})")

    # =========================================================================
    # E. rerun scope, authorization structure, no retroactive regrading
    # =========================================================================
    # E1 plan_core delta attribution: only the two repaired projections + config moved
    moved = []
    for task39 in tasks39:
        task38 = next(t for t in p38["tasks"] if t["case_id"] == task39["case_id"])
        for key in ["source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]:
            if task39[key] != task38[key]:
                moved.append(f"{task39['case_id']}:{key}")
    check(sorted(moved) == sorted([f"{FKW03}:projection_sha256", f"{FKW03}:tool_schema_sha256",
                                   f"{FKW07}:projection_sha256", f"{FKW07}:tool_schema_sha256"]),
          f"E1a plan_core input delta limited to the two repaired projections (+ their tool schemas) (delta: {moved})")
    check(p39["plan_core_sha256"] != p38["plan_core_sha256"], "E1b plan_core_sha256 actually changed v3.8 -> v3.9")
    check(all(row["run_identity"]["plan_core_sha256"] == p39["plan_core_sha256"] for row in p39["runs"]),
          "E1c every v3.9 run identity embeds the new plan_core -> all-36 rerun preregistration is the only consistent scope")
    check(p39["audit_repair"]["rerun_scope_preregistration"].startswith("all 36 runs"), "E1d rerun scope preregistered as all 36 runs in the plan")
    # E2 authorization structure unchanged
    check(p39["authorization"] == {"paid_calls_authorized": False, "execution_state": "offline_validation_only",
                                   "separate_plan_bound_authorization_required": True, "passing_identity_preflight_required": True},
          "E2a plan authorization: separate plan-bound authorization + passing identity preflight required, paid calls not authorized")
    check(b39["paid_calls_authorized"] is False and cfg39["execution"]["paid_calls_authorized"] is False and cfg39["execution"]["offline_validation_only"] is True,
          "E2b bundle/config agree: paid_calls_authorized=false, offline_validation_only=true")
    check(cfg39["semantic_bindings"]["decimal_output_contract_visibility_gate"] == "oracle_expectations_subset_of_candidate_visible_contract_v3_9",
          "E2c config binds the new visibility gate into semantic_bindings")
    # E3 config diff limited to disclosure plumbing
    diff_keys = sorted(k for k in set(cfg38) | set(cfg39) if my_canonical(cfg38.get(k)) != my_canonical(cfg39.get(k)))
    expected_diff = ["contract_repair", "contract_version", "semantic_bindings", "supersedes"]
    check(diff_keys == expected_diff, f"E3 v3.9 config delta vs v3.8 limited to {expected_diff} (got {diff_keys})")
    exec_diff = sorted(k for k in set(cfg38["execution"]) | set(cfg39["execution"]) if my_canonical(cfg38["execution"].get(k)) != my_canonical(cfg39["execution"].get(k)))
    check(exec_diff == [] and cfg38["execution"]["paid_calls_authorized"] is False and cfg38["execution"]["offline_validation_only"] is True,
          f"E3b execution block byte-identical to v3.8 (already paid_calls_authorized=false, offline_validation_only=true) (delta {exec_diff})")
    sem_diff = {k: (cfg38.get("semantic_bindings", {}).get(k), cfg39["semantic_bindings"].get(k)) for k in set(cfg38.get("semantic_bindings", {})) | set(cfg39["semantic_bindings"]) if my_canonical(cfg38.get("semantic_bindings", {}).get(k)) != my_canonical(cfg39["semantic_bindings"].get(k))}
    check(sem_diff == {"calculation": ("executed_decimal_rational_v3_8", "executed_decimal_rational_v3_9"),
                       "decimal_output_contract_visibility_gate": (None, "oracle_expectations_subset_of_candidate_visible_contract_v3_9")},
          f"E3c semantic_bindings delta limited to calculation tag version bump + new visibility gate (got {sem_diff})")
    # E4 no retroactive pass for the v3.8 answers under v3.9 grading semantics
    from harness.acceptance_v3_9 import grade_candidate_v39  # noqa: E402 (hash-locked subject under audit)
    fixture03 = read_json(ROOT / "tests/fixtures/acceptance_v3_9/grader.fkw03.decimal_contract.json")
    grade_ok = grade_candidate_v39(fixture03["candidate"], read_json(ROOT / fixture03["projection_path"]), read_json(ROOT / fixture03["snapshot_path"]), fixture03["trace"])
    check(grade_ok["all_applicable_checks_passed"] is True, "E4a v3.9 grader passes the conforming 6dp fixture candidate on fkw-03")
    old_style = copy.deepcopy(fixture03["candidate"])
    old_style["value"]["scaled_value"] = "0.000035215003535366"
    grade_old = grade_candidate_v39(old_style, read_json(ROOT / fixture03["projection_path"]), read_json(ROOT / fixture03["snapshot_path"]), fixture03["trace"])
    check(grade_old["all_applicable_checks_passed"] is False and grade_old["checks"]["structure_parsed"] is False,
          "E4b the v3.8-style exact-quotient answer still fails under v3.9 (tightened lexical schema rejects it; no retroactive relaxation)")

    # =========================================================================
    # F. security & hygiene
    # =========================================================================
    from contracts.run_trace_validator_v3_7 import scan_persisted_value_for_secrets  # noqa: E402
    fixture_findings = [f"{path.name}:{finding}" for path in sorted((ROOT / "tests/fixtures/acceptance_v3_9").glob("*.json")) for finding in scan_persisted_value_for_secrets(read_json(path))]
    check(not fixture_findings, f"F1 v3.9 fixture secret scan 0 findings (got {fixture_findings})")
    check('"api_key"' not in v39_src and "sk-" not in v39_src.replace("task", ""), "F2 no credential material in harness/acceptance_v3_9.py")

    failures = [label for ok, label in RESULTS if not ok]
    print(f"\ntotal checks={len(RESULTS)} failures={len(failures)}")
    for label in failures:
        print(f"FAILED: {label}")
    print("AUDIT_VERDICT=" + ("PASS" if not failures else "FAIL"))


if __name__ == "__main__":
    main()
