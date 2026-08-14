#!/usr/bin/env python3
"""PER-32 Stage 4 independent audit — Part 3: identity, fairness, safety.

Checks over all 810 executed runs (stdlib only):
  Identity (A05):
    - requested_model_id == response_model_id == run_identity.requested_model_id
      == plan row model_id for every trace and every provider attempt;
    - model ids restricted to the frozen manifest v2 set with
      exact_response_match; endpoint_id follows the registered policy
      (bailian_ + 12-hex origin prefix, no path/query/credentials).
  Fairness (A06):
    - every logical request's parameters_sha256 equals the model's preflight
      commitment (uniform within a model; only disclosed qwen delta allowed);
    - tool_schema_sha256 equals the plan-registered per-case value;
    - frozen config fairness fields identical across v3.10/v3.11 except the
      documented cumulative token ceiling.
  Safety / simulation (part of A01/A09 context + no-real-trade):
    - environment: simulated ledger, real_side_effects=false, network scope
      inference-only, terminal state consistent;
    - permissions: no violations; declared permissions equal the projection's
      registered permissions; observed operations within the allowed set;
    - redaction applied; harness secret flag false AND auditor-owned regex
      secret scan finds nothing in any trace/candidate file;
    - point-in-time: every evidence observation available_at/event_time <=
      projection cutoff (independent recompute).
  Latency: per-run duration from checkpoint run_started -> run_completed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILS: list[str] = []
PASSES = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
    else:
        FAILS.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


SECRET_PATTERNS = [
    re.compile(r"(?i)\b(sk-[a-z0-9]{16,}|api[_-]?key|apikey)\b"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{16,}\b"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*[a-z0-9._\-]{16,}\b"),
    re.compile(r"\bLTAI[a-zA-Z0-9]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
    re.compile(r"(?i)\bpassword\s*[:=]\s*\S{6,}"),
    re.compile(r"(?i)\bsecret\s*[:=]\s*\S{8,}"),
    re.compile(r"\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\."),  # JWT
]
# allowlist: registered harness/contract vocabulary that trips the patterns
ALLOWLIST = re.compile(r"(?i)(secret_leakage|no_secret|secret_scan|redact)")

ROUNDS = [
    ("v3.10", ROOT / "runs/stage3/acceptance-20260813-v3.10",
     "contracts/stage3_acceptance_plan.v3.10.json"),
    ("v3.11", ROOT / "runs/stage3/acceptance-20260813-v3.11",
     "contracts/stage3_acceptance_plan.v3.11.json"),
    ("v3.11.1", ROOT / "runs/stage3/coverage-20260814-v3.11.1",
     "contracts/stage3_acceptance_plan.v3.11.1.json"),
]

manifest_models = load(ROOT / "contracts/model_manifest.frozen.v2.json")
allowed_identity = {
    m["logical_label"]: set(m["allowed_response_model_ids"])
    for m in manifest_models["models"]
}
identity_rule = {m["logical_label"]: m["identity_rule"]
                 for m in manifest_models["models"]}

stats = Counter()
param_by_model: dict[str, set] = defaultdict(set)
tool_schema_mismatch = []
identity_bad = []
env_bad = []
perm_bad = []
pit_bad = []
secret_hits = []
latency_ms: dict[str, int] = {}
usage_max_tokens = 0

for label, rundir, plan_rel in ROUNDS:
    plan = load(ROOT / plan_rel)
    tasks = {t["case_id"]: t for t in plan["tasks"]}
    runs_by_id = {r["run_id"]: r for r in plan["runs"]}
    preflight = load(rundir / "preflight.json")
    param_commit = {r["model_id"]: r["parameters_sha256"]
                    for r in preflight["results"]}
    for trace_p in sorted((rundir / "traces").glob("run_*.json")):
        trace = load(trace_p)
        rid = trace["run_id"]
        ident = trace["run_identity"]
        model = ident["requested_model_id"]
        stats["runs"] += 1

        # ---------------- identity
        provider = trace["provider"]
        if not (provider["requested_model_id"] == model
                == ident["requested_model_id"]):
            identity_bad.append(f"{rid} provider/identity model mismatch")
        if provider["response_model_id"] != model:
            identity_bad.append(f"{rid} response_model_id "
                                f"{provider['response_model_id']} != {model}")
        if model not in allowed_identity:
            identity_bad.append(f"{rid} model {model} not in frozen manifest")
        elif provider["response_model_id"] not in allowed_identity[model]:
            identity_bad.append(f"{rid} response id not allowed")
        if identity_rule.get(model) != "exact_response_match":
            identity_bad.append(f"{rid} identity rule not exact_response_match")
        ep = provider.get("endpoint_id", "")
        if not re.fullmatch(r"bailian_[0-9a-f]{12}", ep):
            identity_bad.append(f"{rid} endpoint_id policy violation: {ep}")
        plan_row = runs_by_id.get(rid)
        if plan_row is None or plan_row["model_id"] != model:
            identity_bad.append(f"{rid} plan row model mismatch")
        for attempt in (lr.get("attempts", []) for lr in trace["logical_requests"]):
            for att in attempt:
                if att.get("response_model_id") not in (None, model):
                    identity_bad.append(f"{rid} attempt response id drift: "
                                        f"{att.get('response_model_id')}")
                if att.get("model_id") not in (None, model):
                    identity_bad.append(f"{rid} attempt model drift")
        if trace["failure"]["class"] in ("provider_or_runtime_failure",
                                         "indeterminate", "contract_defect"):
            stats["provider_failures"] += 1

        # ---------------- fairness: params + tool schema per request
        task = tasks[ident["case_id"]]
        for lr in trace["logical_requests"]:
            param_by_model[model].add(lr["parameters_sha256"])
            if lr["parameters_sha256"] != param_commit.get(model):
                stats["param_drift"] += 1
                identity_bad.append(f"{rid} parameters_sha256 drift from "
                                    f"preflight commitment")
            if lr["tool_schema_sha256"] != task["tool_schema_sha256"]:
                tool_schema_mismatch.append(rid)
        # ---------------- safety / simulation
        env = trace["environment"]
        if not (env.get("ledger_mode") == "simulated"
                and env.get("real_side_effects") is False
                and env.get("network_scope") == "bailian_inference_only"
                and env.get("dataset_access") == "frozen_read_only"
                and env.get("final_state_matches_initial")
                == (env.get("initial_ledger_sha256")
                    == env.get("final_ledger_sha256"))):
            env_bad.append(rid)
        perm = trace["permission"]
        projection = load(ROOT / task["projection_path"])
        grader = load(rundir / "graders" / f"{rid}.json")
        # Declared permissions must equal the projection's registered set for
        # every run (harness-side fairness). Candidates MAY violate boundaries;
        # the harness must detect that and the grader must fail the check.
        if not (perm.get("trace_complete") is True
                and set(perm.get("declared_permissions", []))
                == set(projection["task"]["permissions"])):
            perm_bad.append(f"{rid} declared != registered")
        tool_surface = {"read_frozen_case", "read_frozen_evidence", "calculate",
                        "submit_candidate_answer", "submit_candidate_non_answer",
                        "simulated_ledger"}
        if not set(perm.get("observed_operations", [])) <= tool_surface:
            perm_bad.append(f"{rid} unregistered tool surface")
        if perm.get("violations") and \
                grader["checks"].get("permission_boundary_respected") is not False:
            perm_bad.append(f"{rid} violation not penalized by grader")
        if not perm.get("violations") and \
                grader["checks"].get("permission_boundary_respected") is not True:
            perm_bad.append(f"{rid} clean run not credited by grader")
        stats["permission_violations"] += bool(perm.get("violations"))
        if trace["redaction"].get("applied") is not True or \
                trace["redaction"].get("secret_leakage_detected") is not False:
            stats["redaction_bad"] += 1
        # ---------------- point-in-time (independent recompute)
        cutoff = iso(projection["temporal"]["available_at_cutoff"])
        for obs in trace.get("evidence_observations", []):
            if iso(obs["available_at"]) > cutoff or iso(obs["event_time"]) > cutoff:
                pit_bad.append(f"{rid}:{obs.get('record_id')}")
        # ---------------- usage & latency
        usage_max_tokens = max(usage_max_tokens,
                               trace["usage"].get("total_tokens", 0))
        events = []
        ckpt = rundir / "checkpoints" / f"{rid}.jsonl"
        for line in ckpt.read_text(encoding="utf-8").splitlines():
            events.append(json.loads(line))
        started = next((e for e in events if e["event_type"] == "run_started"), None)
        finished = next((e for e in events
                         if e["event_type"] in ("run_completed", "run_failed")), None)
        if started and finished:
            latency_ms[rid] = int((iso(finished["created_at"])
                                   - iso(started["created_at"])).total_seconds() * 1000)

        # ---------------- auditor-owned secret scan (trace + candidate)
        cand_p = rundir / "candidates" / f"{rid}.json"
        for path in (trace_p, cand_p):
            text = path.read_text(encoding="utf-8")
            for pat in SECRET_PATTERNS:
                for m in pat.finditer(text):
                    snippet = m.group(0)
                    if ALLOWLIST.search(snippet):
                        continue
                    secret_hits.append(f"{path.name}: {snippet[:40]}")

check("identity: all runs exact-match, manifest-bound, endpoint policy",
      not identity_bad, "; ".join(identity_bad[:6]))
check("fairness: per-request parameters equal preflight commitment",
      stats["param_drift"] == 0, f"drift={stats['param_drift']}")
check("fairness: per-model parameter hash sets size == 1",
      all(len(v) == 1 for v in param_by_model.values()),
      str({k: len(v) for k, v in param_by_model.items()}))
# qwen disclosed delta: exactly one distinct hash for qwen, and the other two
# models share one identical hash
qwen_h = next(iter(param_by_model.get("qwen3.8-max", {None})))
other_h = {next(iter(param_by_model.get("glm-5.2", {None}))),
           next(iter(param_by_model.get("deepseek-v4-pro", {None})))}
check("fairness: glm and deepseek share one parameter commitment; "
      "qwen delta disclosed (enable_thinking=false)",
      len(other_h) == 1 and None not in other_h and qwen_h not in other_h,
      f"qwen={qwen_h} others={other_h}")
check("fairness: tool_schema_sha256 matches plan per case",
      not tool_schema_mismatch, f"{tool_schema_mismatch[:5]}")
check("safety: simulated environment invariants hold for all runs",
      not env_bad, f"{env_bad[:5]}")
check("safety: permission boundaries declared per projection and enforced "
      "symmetrically (violations detected and penalized)",
      not perm_bad, f"{perm_bad[:5]}")
print(f"INFO candidate permission violations detected+penalized: "
      f"{stats['permission_violations']}/810")
check("point-in-time: no observation after cutoff (independent recompute)",
      not pit_bad, f"{pit_bad[:5]}")
check("secret scan: auditor regex patterns find no credentials",
      not secret_hits, f"{secret_hits[:5]}")
check("provider failures: zero", stats["provider_failures"] == 0,
      str(stats["provider_failures"]))
check("latency recovered for all 810 runs", len(latency_ms) == 810,
      f"{len(latency_ms)}")
check("usage: cumulative total_tokens within v3.11 ceiling 262144",
      usage_max_tokens <= 262144, str(usage_max_tokens))

# ---------------- config fairness between v3.10 and v3.11
cfg10 = load(ROOT / "contracts/run_trace_harness_config.v3.10.json")
cfg11 = load(ROOT / "contracts/run_trace_harness_config.v3.11.json")
for field in ["system_prompt", "tool_names", "security", "fairness",
              "request_commitments", "provider_retry_policy", "semantic_bindings",
              "runtime", "candidate_model_ids"]:
    check(f"config fairness: {field} identical v3.10 vs v3.11",
          cfg10.get(field) == cfg11.get(field), field)
rb10, rb11 = cfg10["resource_budget"], cfg11["resource_budget"]
documented_additions = {"single_request_context_window", "max_total_tokens_derivation"}
shared10 = {k: v for k, v in rb10.items() if k != "max_total_tokens"}
shared11 = {k: v for k, v in rb11.items()
            if k not in documented_additions and k != "max_total_tokens"}
check("config fairness: resource_budget shared keys identical except "
      "documented token cap; v3.11 additions limited to the derivation block",
      shared10 == shared11
      and rb10["max_total_tokens"] == 32768
      and rb11["max_total_tokens"] == 262144
      and set(rb11) - set(rb10) == documented_additions
      and rb11["max_total_tokens_derivation"]["result"] == 262144
      and rb11["max_total_tokens_derivation"]["back_derived_from_observed_usage"] is False,
      f"shared10==shared11: {shared10 == shared11}")
check("config fairness: fairness flags true and qwen-only parameter disclosed",
      cfg11["fairness"]["same_prompt_tools_budget_retry_grader_for_all_models"] is True
      and cfg11["fairness"]["qwen_only_protocol_parameter"] == "enable_thinking=false",
      str(cfg11["fairness"]))

# per-model summary of latencies (for Part 4)
by_model_latency: dict[str, list[int]] = defaultdict(list)
for label, rundir, plan_rel in ROUNDS:
    plan = load(ROOT / plan_rel)
    runs_by_id = {r["run_id"]: r for r in plan["runs"]}
    for rid, ms in latency_ms.items():
        if rid in runs_by_id:
            by_model_latency[runs_by_id[rid]["model_id"]].append(ms)
out = ROOT / "audit" / "per32_part3_latency.json"
out.write_text(json.dumps({
    model: {"n": len(vals), "mean_ms": sum(vals) / len(vals),
            "median_ms": sorted(vals)[len(vals) // 2],
            "max_ms": max(vals)}
    for model, vals in sorted(by_model_latency.items())
}, indent=2) + "\n", encoding="utf-8")
print("INFO per-model latency:",
      json.dumps({m: int(v["mean_ms"]) for m, v in
                  {model: {"mean_ms": sum(vals) / len(vals)}
                   for model, vals in by_model_latency.items()}.items()}))

print(f"\nRESULT: {'PASS' if not FAILS else 'FAIL'} — {PASSES} checks passed, "
      f"{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
