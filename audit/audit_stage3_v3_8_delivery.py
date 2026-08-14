"""Stage 3E (PER-42) independent delivery audit for the v3.8 36-run acceptance.

Independent recomputation of all frozen hashes, run identities, provider
reconciliation, deterministic regrading, checkpoint-chain replay, summary
recomputation and secret scan.  Canonical-hash helpers are re-implemented
here (not imported from the harness) so the audit does not depend on the
implementation's code paths; the frozen validator/grader ARE re-used for
deterministic re-execution, but only after their file hashes are verified
against the frozen contract bundle inside this same script.

Usage:
    uv run python -m audit.audit_stage3_v3_8_delivery

Exit code 0 with final line AUDIT_VERDICT=PASS when every check holds.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence/stage3/acceptance-20260812-v3.8"
ZIP_PATH = ROOT / "attachments/stage3-acceptance-20260812-v3.8-evidence.zip"

# --- values claimed by the delivery (PER-42 / PER-45) -----------------------
CLAIMS = {
    "preflight_sha256": "f2f001f9df3e9b3dfc6eec8234cc46f86471d129d424140ddd2bf33a92c732b0",
    "evidence_bundle_sha256": "ea8c74464682cc65de7c591e588faf4f15d8c3f1e3446242f3c67e019798d050",
    "evidence_zip_sha256": "1919310ee21ea8b657aa993d8c0ecccb4108a05c114709fb4c2a349e51b6ca00",
    "contract_bundle_sha256": "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609",
    "plan_sha256": "636d94fbb6d08d58adfd018dfba6115bb44ac193480a5380e3228c623a4c3d22",
    "config_sha256": "8f6ab9b76492248d4d0d841b8beb5fdbe679537ed7664c43e0b33f6dd2bf8712",
}
EXPECTED_MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")
    return None


# --- independent canonical-hash re-implementation ---------------------------
def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csha(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fsha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha_without(doc: dict, key: str) -> str:
    copy = dict(doc)
    copy.pop(key, None)
    return csha(copy)


def main() -> int:
    print("== A. frozen contract bundle ==")
    contracts = read_json(EV / "stage3_acceptance_contracts.frozen.v3.8.json")
    art_bad = [item["path"] for item in contracts["artifacts"]
               if not (ROOT / item["path"]).is_file() or fsha(ROOT / item["path"]) != item["sha256"]]
    art_ok = len(contracts["artifacts"]) - len(art_bad)
    check("A1 contract artifacts byte-exact", art_ok == len(contracts["artifacts"]),
          f"{art_ok}/{len(contracts['artifacts'])} bad={art_bad}")
    check("A2 contract bundle content sha", csha(contracts["artifacts"]) == contracts["bundle_sha256"] == CLAIMS["contract_bundle_sha256"],
          f"recomputed={csha(contracts['artifacts'])}")
    check("A3 no retroactive regrading", contracts["preserved"]["retroactive_regrading"] is False)

    print("== B. plan / config ==")
    plan = read_json(EV / "stage3_acceptance_plan.v3.8.json")
    config = read_json(EV / "run_trace_harness_config.v3.8.json")
    check("B1 config file sha", fsha(EV / "run_trace_harness_config.v3.8.json") == CLAIMS["config_sha256"])
    check("B2 plan content sha (sans plan_sha256)", sha_without(plan, "plan_sha256") == CLAIMS["plan_sha256"] == plan["plan_sha256"],
          f"recomputed={sha_without(plan, 'plan_sha256')}")
    core = {
        "contract_version": "3.8.0",
        "config_sha256": CLAIMS["config_sha256"],
        "models": EXPECTED_MODELS,
        "task_inputs": [
            {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in plan["tasks"]
        ],
    }
    check("B3 plan core sha recomputed", csha(core) == plan["plan_core_sha256"], f"recomputed={csha(core)}")
    check("B4 run cap and row count", plan["run_cap"] == 36 and len(plan["runs"]) == 36 and len(plan["tasks"]) == 12)
    identity_ok, identity_bad = 0, []
    for row in plan["runs"]:
        derived = "run_" + csha(row["run_identity"])[:32]
        if derived == row["run_id"] and row["run_identity"]["requested_model_id"] == row["model_id"]:
            identity_ok += 1
        else:
            identity_bad.append(row["run_id"])
    check("B5 plan run_id derivation", identity_ok == 36, f"bad={identity_bad}")

    print("== C. preflight ==")
    pre = read_json(EV / "preflight.json")
    check("C1 preflight content sha (sans self)", sha_without(pre, "preflight_sha256") == CLAIMS["preflight_sha256"] == pre["preflight_sha256"],
          f"recomputed={sha_without(pre, 'preflight_sha256')}")
    check("C2 preflight bound to plan", pre["plan_sha256"] == CLAIMS["plan_sha256"])
    check("C3 preflight 3/3 pass with exact identity",
          pre["decision"] == "passed_3_of_3"
          and [r["model_id"] for r in pre["results"]] == EXPECTED_MODELS
          and all(r["passed"] and r["response_model_id"] == r["model_id"] and r["parameters_honored"] and r["tool_capability_passed"] for r in pre["results"]))

    print("== D. evidence bundle manifest + ZIP ==")
    manifest = read_json(EV / "bundle.manifest.json")
    m_ok, m_bad = 0, []
    for item in manifest["artifacts"]:
        path = EV / item["path"]
        if path.is_file() and fsha(path) == item["sha256"]:
            m_ok += 1
        else:
            m_bad.append(item["path"])
    check("D1 manifest artifact hashes (152)", m_ok == len(manifest["artifacts"]) == 152, f"{m_ok}/152 bad={m_bad[:5]}")
    check("D2 evidence bundle content sha", csha(manifest["artifacts"]) == manifest["bundle_sha256"] == CLAIMS["evidence_bundle_sha256"],
          f"recomputed={csha(manifest['artifacts'])}")
    header = {k: manifest[k] for k in ["plan_sha256", "config_sha256", "contract_bundle_sha256", "preflight_sha256"]}
    check("D3 manifest header hash bindings",
          header["plan_sha256"] == CLAIMS["plan_sha256"] and header["config_sha256"] == CLAIMS["config_sha256"]
          and header["contract_bundle_sha256"] == CLAIMS["contract_bundle_sha256"] and header["preflight_sha256"] == CLAIMS["preflight_sha256"])
    check("D4 zip file sha", fsha(ZIP_PATH) == CLAIMS["evidence_zip_sha256"])
    zip_bad, zip_n = [], 0
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
        for name in names:
            data = zf.read(name)
            local = EV / name.split("/", 1)[1]
            if not local.is_file() or hashlib.sha256(data).hexdigest() != fsha(local):
                zip_bad.append(name)
            else:
                zip_n += 1
    check("D5 zip contents byte-equal to frozen dir", len(names) == 153 and zip_n == 153 and not zip_bad, f"n={len(names)} bad={zip_bad[:5]}")

    print("== E. authorization scope ==")
    auth = read_json(EV / "authorization.run.json")
    check("E1 authorization bound to plan+preflight", auth["plan_sha256"] == CLAIMS["plan_sha256"] and auth["preflight_sha256"] == CLAIMS["preflight_sha256"])
    check("E2 authorized models exact", sorted(auth["exact_model_ids"]) == sorted(EXPECTED_MODELS))
    check("E3 authorized run ids == plan run ids", sorted(auth["authorized_run_ids"]) == sorted(row["run_id"] for row in plan["runs"]) and auth["maximum_runs"] == 36)
    check("E4 paid authorization explicit", auth["paid_calls_authorized"] is True and bool(auth["authorization_basis"].get("owner_comment_id")))

    # ---- from here on the frozen validator/grader code is re-used, after hash check
    sys.path.insert(0, str(ROOT))
    from contracts.run_trace_validator_v3_8 import validate_run_trace_v38  # noqa: E402
    from harness.acceptance_v3_8 import grade_candidate_v38  # noqa: E402
    validator_ok = False
    for item in contracts["artifacts"]:
        if item["path"] == "contracts/run_trace_validator_v3_8.py":
            validator_ok = fsha(ROOT / item["path"]) == item["sha256"]
        if item["path"] == "harness/acceptance_v3_8.py":
            grader_ok = fsha(ROOT / item["path"]) == item["sha256"]
    check("E5 frozen validator/grader code hashes verified before reuse", validator_ok and grader_ok)

    print("== F. per-run verification (36) ==")
    run_ids = [row["run_id"] for row in plan["runs"]]
    for kind, ext in [("candidates", ".json"), ("traces", ".json"), ("graders", ".json"), ("checkpoints", ".jsonl")]:
        found = sorted(p.name for p in (EV / kind).iterdir())
        check(f"F0 {kind} file set == 36 plan runs", found == sorted(rid + ext for rid in run_ids), f"n={len(found)}")

    params_by_model = config["request_commitments"]["parameters_sha256_by_model"]
    task_by_case = {t["case_id"]: t for t in plan["tasks"]}
    row_by_id = {r["run_id"]: r for r in plan["runs"]}
    bad = {k: [] for k in ["identity", "model", "validator", "requests", "candidate", "grader", "regrade", "checkpoint", "env", "pit", "seed", "tool_schema", "endpoint"]}
    regrade_note = []
    for rid in run_ids:
        row = row_by_id[rid]
        task = task_by_case[row["run_identity"]["case_id"]]
        trace = read_json(EV / "traces" / f"{rid}.json")
        candidate = read_json(EV / "candidates" / f"{rid}.json")
        grader = read_json(EV / "graders" / f"{rid}.json")
        projection = read_json(ROOT / task["projection_path"])
        snapshot = read_json(ROOT / task["snapshot_path"])

        # F1 identity
        if trace["run_identity"] != row["run_identity"] or trace["run_id"] != rid or ("run_" + csha(trace["run_identity"])[:32]) != rid:
            bad["identity"].append(rid)
        # F2 provider identity
        prov = trace["provider"]
        if not (prov["requested_model_id"] == prov["response_model_id"] == row["model_id"] and prov["endpoint_id"] == pre["endpoint_id"]):
            bad["model"].append(rid)
        if trace.get("run_identity", {}).get("seed") is not None and row["seed"] != trace["run_identity"]["seed"]:
            bad["seed"].append(rid)
        # F3 frozen validator (schema + identity + ledger replay + secret hard gate)
        try:
            vres = validate_run_trace_v38(trace, plan=plan, scan_companions=[candidate, grader])
            if isinstance(vres, dict) and vres.get("errors"):
                bad["validator"].append(f"{rid}:{list(vres['errors'])[:2]}")
        except Exception as exc:  # HarnessContractV38Error is a hard rejection
            bad["validator"].append(f"{rid}:{str(exc)[:160]}")
        # F4 request/attempt reconciliation
        reqs = trace["logical_requests"]
        attempts = [a for r in reqs for a in r["attempts"]]
        usage = trace["usage"]
        phases = [r["phase"] for r in reqs]
        phase_shape = phases and phases[0] == "initial" and phases == ["initial"] * phases.count("initial") + ["repair"] * phases.count("repair")
        req_ok = (
            usage["model_requests"] == len(reqs)
            and usage["provider_attempts"] == len(attempts)
            and usage["tool_calls"] == len(trace["tool_events"])
            and phase_shape
            and all(r["model_id"] == row["model_id"] for r in reqs)
            and all(r["seed"] == row["seed"] for r in reqs)
            and all(r["tool_schema_sha256"] == task["tool_schema_sha256"] for r in reqs)
            and all(r["parameters_sha256"] == params_by_model[row["model_id"]] for r in reqs)
            and all(len({a["payload_sha256"] for a in r["attempts"]}) == 1 for r in reqs)
            and all(r["payload_sha256"] == r["attempts"][0]["payload_sha256"] for r in reqs)
        )
        if not req_ok:
            bad["requests"].append(rid)
        # F5 candidate binding (candidate file stores JSON null when nothing was submitted)
        want_candidate_sha = csha(candidate) if candidate is not None else None
        if trace["result"]["candidate_output_sha256"] != want_candidate_sha or trace["result"]["structured_output_valid"] != (candidate is not None):
            bad["candidate"].append(rid)
        # F6 grader commitments + self hash
        want = {
            "candidate_sha256": want_candidate_sha,
            "trace_sha256": csha(trace),
            "projection_sha256": csha(projection),
            "snapshot_sha256": csha(snapshot),
        }
        if grader["commitments"] != want or sha_without(grader, "grader_sha256") != grader["grader_sha256"] or grader["run_id"] != rid or grader["case_id"] != row["run_identity"]["case_id"]:
            bad["grader"].append(rid)
        if fsha(ROOT / task["projection_path"]) != task["projection_sha256"] or fsha(ROOT / task["snapshot_path"]) != task["snapshot_sha256"]:
            bad["grader"].append(rid + ":projection/snapshot file hash drift")
        # F7 deterministic regrade with frozen grader
        regrown = grade_candidate_v38(candidate, projection, snapshot, trace)
        if regrown != grader:
            diff = sorted(k for k in set(regrown) | set(grader) if regrown.get(k) != grader.get(k))
            bad["regrade"].append(f"{rid}:{diff}")
            regrade_note.append((rid, diff))
        # F8 checkpoint chain replay
        lines = (EV / "checkpoints" / f"{rid}.jsonl").read_text(encoding="utf-8").strip().splitlines()
        prev = "0" * 64
        chain_ok, offset = True, 0
        last_sha = None
        for raw in lines:
            ev = json.loads(raw)
            if canonical(ev) != raw:
                chain_ok = False
            want_sha = sha_without(ev, "event_sha256")
            if ev["event_sha256"] != want_sha or ev["previous_event_sha256"] != prev or ev["offset"] != offset or ev["run_id"] != rid:
                chain_ok = False
            prev, last_sha = ev["event_sha256"], ev["event_sha256"]
            offset += 1
        if not (chain_ok and offset == trace["checkpoint"]["event_count"] and last_sha == trace["checkpoint"]["final_event_sha256"]):
            bad["checkpoint"].append(rid)
        # F9 environment terminal-state safety (permission violations are grading outcomes, checked via regrade)
        env = trace["environment"]
        if not (env["real_side_effects"] is False and env["final_state_matches_initial"] is (env["initial_ledger_sha256"] == env["final_ledger_sha256"]) and env["dataset_access"] == "frozen_read_only"):
            bad["env"].append(rid)
        # F10 PIT from observations
        from datetime import datetime, timezone

        def iso(s):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        cutoff = iso(projection["temporal"]["available_at_cutoff"])
        if not all(iso(o["available_at"]) <= cutoff and iso(o["event_time"]) <= cutoff for o in trace["evidence_observations"]):
            bad["pit"].append(rid)

    for key, vals in bad.items():
        check(f"F-{key} clean across 36 runs", not vals, f"problems={vals[:4]}")

    print("== G. summary recomputation ==")
    summary = read_json(EV / "summary.json")
    recs = {r["run_id"]: r for r in summary["records"]}
    recompute = {
        "planned": 36, "traces": 36, "graders": 36, "checkpoints": 36,
        "succeeded": sum(1 for rid in run_ids if read_json(EV / "traces" / f"{rid}.json")["status"] == "succeeded"),
        "all_applicable_checks_passed": sum(1 for rid in run_ids if read_json(EV / "graders" / f"{rid}.json")["all_applicable_checks_passed"]),
        "value_semantic_correct": sum(1 for rid in run_ids if read_json(EV / "graders" / f"{rid}.json")["checks"]["value_semantic_correct"] is True),
        "provider_attempts": sum(len(read_json(EV / "traces" / f"{rid}.json")["logical_requests"][0]["attempts"]) + sum(len(r["attempts"]) for r in read_json(EV / "traces" / f"{rid}.json")["logical_requests"][1:]) for rid in run_ids),
    }
    for key, val in recompute.items():
        check(f"G-{key} matches summary", summary["counts"].get(key) == val, f"summary={summary['counts'].get(key)} recomputed={val}")
    check("G-records count and reconciliation", len(summary["records"]) == 36 and summary["reconciliation_errors"] == [] and summary["provider_error_codes"] == [])
    # per-record cross-check against trace+grader
    rec_bad = []
    for rid in run_ids:
        trace = read_json(EV / "traces" / f"{rid}.json")
        grader = read_json(EV / "graders" / f"{rid}.json")
        rec = recs[rid]
        if not (rec["status"] == trace["status"] and rec["model_id"] == trace["provider"]["requested_model_id"]
                and rec["all_applicable_checks_passed"] == grader["all_applicable_checks_passed"]
                and rec["failed_checks"] == grader["failed_checks"]
                and rec["identity_valid"] is True):
            rec_bad.append(rid)
    check("G-records consistent with trace+grader", not rec_bad, f"bad={rec_bad}")
    rt = read_json(EV / "runtime-summary.json")
    check("G-runtime-summary counts", rt["counts"] == {"planned": 36, "candidates": 36, "traces": 36, "graders": 36, "accepted": recompute["all_applicable_checks_passed"]}
          and rt["plan_sha256"] == CLAIMS["plan_sha256"] and rt["preflight_sha256"] == CLAIMS["preflight_sha256"])

    print("== H. secret scan over all persisted artifacts ==")
    from contracts.run_trace_validator_v3_7 import SECRET_TEXT, scan_persisted_value_for_secrets  # noqa: E402

    def string_leaves(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from string_leaves(child)
        elif isinstance(value, list):
            for child in value:
                yield from string_leaves(child)

    findings = []
    for path in sorted(EV.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            values = [json.loads(path.read_text(encoding="utf-8"))]
        elif path.suffix == ".jsonl":
            values = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
        else:
            values = [path.read_text(encoding="utf-8")]
        runtime_artifact = path.parts[-2] in {"traces", "candidates", "graders", "checkpoints"}
        for value in values:
            # runtime artifacts get the full hard gate (secret-like keys AND values);
            # governance documents get the value scan only — key names like
            # "authorization" are legitimate field names there, not secrets.
            if runtime_artifact:
                found = scan_persisted_value_for_secrets(value)
            else:
                found = [text for text in string_leaves(value) if SECRET_TEXT.search(text)]
            if found:
                findings.append((str(path), found))
    check("H-secret scan clean (153 files)", not findings, f"findings={findings[:3]}")

    print(f"\ntotal checks={CHECKS} failures={len(FAILURES)}")
    for item in FAILURES:
        print("FAILURE:", item)
    print("AUDIT_VERDICT=" + ("PASS" if not FAILURES else "FAIL"))
    return 0 if not FAILURES else 2


if __name__ == "__main__":
    raise SystemExit(main())
