"""PER-56 independent delivery audit of the v3.9 final 36-run round.

Stdlib-only (no harness / validator imports) so the recomputation is
independent of the implementation code paths. Read-only over the frozen
run directory; the only write is this script's own report file.

Hash schemes (verified against the v3.8 round with known-good hashes
before being applied to v3.9):
  * content_sha256(x)  = SHA-256(json.dumps(x, sort_keys, compact, ensure_ascii=False))
  * file_sha256(p)     = SHA-256(raw bytes)
  * plan_sha256        = content_sha256(plan without the plan_sha256 key)
  * preflight_sha256   = content_sha256(artifact without the preflight_sha256 key)
  * contract bundle_sha256 = content_sha256(bundle["artifacts"])
  * evidence bundle_sha256 = content_sha256(manifest["artifacts"])
  * build_run_id(identity) = "run_" + content_sha256(identity)[:32]
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.9"
PLAN_PATH = RUN_DIR / "stage3_acceptance_plan.v3.9.json"
BUNDLE_PATH = RUN_DIR / "stage3_acceptance_contracts.frozen.v3.9.json"
CONFIG_PATH = RUN_DIR / "run_trace_harness_config.v3.9.json"
PREFLIGHT_PATH = RUN_DIR / "preflight.json"
MANIFEST_PATH = RUN_DIR / "bundle.manifest.json"

# Declared values: PER-56 issue body (implementation-side claims to verify).
DECLARED = {
    "contract_bundle": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "plan": "235b0415bf43c356a5f2c3801a7793606ed5e943a5e8ce60f0aa3b20abeeb185",
    "plan_core": "bf1d1ed48b0f5728b0f2f71bcd13af91dc7a9ed586c0f2ffbe9cebaf7e804ebd",
    "config": "e06b3fae6acf1ab76716c3a507163601fa6249f6160a8dbfce1216f8080e0cfa",
    "preflight": "ebfdf45d495800aa0de5433ee082340a5ab71dba511f3f64448e541db42ca65d",
    "preflight_file": "880085b7c2bba632003c704aaae55f9b9eb377b7617fe8288f47b1010a9a9a0d",
    "evidence_bundle": "af08a8c9929a6086264e243490ccae26e187384aae9eb7d78d01f5cd269afa1a",
    "summary_file": "749c033115d13add748360e7c33329c399cd54e97f5d960c4011474338f79b0f",
    "runtime_summary_file": "8a76aa6d21a438be71d780d8454f6a8450b7527973ca3a4cb4a4711a3a9c0fdd",
}

# PER-52 delivery comment 12939662-0b46-491b-96e5-344b221f3344 (pre-registered,
# published before the PER-55 paid execution): ordered 36 run identities.
PREREG: list[tuple[int, str, str]] = [
    (1, "deepseek-v4-pro", "run_154def7b1005fe1825639b60b2c575ca"),
    (2, "qwen3.8-max", "run_f850e1b6a392d28b85ad80743da21ccd"),
    (3, "glm-5.2", "run_fa2b0ffb7ae316d9886a88aff1463ab5"),
    (4, "glm-5.2", "run_e65b454cf6c2b0b3224632eb4258fc11"),
    (5, "deepseek-v4-pro", "run_1deb170d82ce5ea1e8bda97e2a3d4804"),
    (6, "qwen3.8-max", "run_4c0af3f5fdcb19c56d5e9103d021bf71"),
    (7, "glm-5.2", "run_f3ff16f6beda69905ff2bedeca1c3fa1"),
    (8, "deepseek-v4-pro", "run_5372db02e86b5c0044b6cb56e88f9f22"),
    (9, "qwen3.8-max", "run_3fe3cf8f7b12da13b979fc3445d6fb74"),
    (10, "deepseek-v4-pro", "run_9cc11c43343b52dcaebbfb768d9a5fff"),
    (11, "glm-5.2", "run_5796abe85d6bc9d5a8d12c4d5a2105f0"),
    (12, "qwen3.8-max", "run_d61d65baddb4a75221b8c6a8f91967e0"),
    (13, "glm-5.2", "run_58d632a379e97b828d6b080d87b707fe"),
    (14, "deepseek-v4-pro", "run_702a786469cacd9724e65271dfcce77c"),
    (15, "qwen3.8-max", "run_080c4c10c2557d38dd2808db2778fc53"),
    (16, "qwen3.8-max", "run_cef929eb6cd93c58c6a6c5a6d866b781"),
    (17, "deepseek-v4-pro", "run_7cf87fb0673fc5280df031386c4b9fe9"),
    (18, "glm-5.2", "run_176d9756cccede4b4765e1f432f47928"),
    (19, "deepseek-v4-pro", "run_cf6f4a199a9176fbfcededc0b2ecc6c7"),
    (20, "qwen3.8-max", "run_00ada2f0a449fd6a7e2f871ec7db0783"),
    (21, "glm-5.2", "run_006027fb74080f37848aee6533d968ba"),
    (22, "qwen3.8-max", "run_8cd83805079ef4a46b411b988818caac"),
    (23, "deepseek-v4-pro", "run_ecc6dac5ff77d905805485a483e543f4"),
    (24, "glm-5.2", "run_102e196a0fd6fd8b883fea3eb151fa0f"),
    (25, "glm-5.2", "run_cbad311351c833409a97ceabfa848616"),
    (26, "deepseek-v4-pro", "run_5f70f7fe81a6b78b32a70b5789343078"),
    (27, "qwen3.8-max", "run_f2d70199139be75120b430befdf78545"),
    (28, "glm-5.2", "run_e2f213794ebe35c1a88222d3e70dc4fe"),
    (29, "qwen3.8-max", "run_5ee65963d82ddc460bc9a9da1190ed08"),
    (30, "deepseek-v4-pro", "run_1f8d714a475f9eee1bf1ff26ff390a8e"),
    (31, "glm-5.2", "run_87150cab4dcc1f1ebc4b8602c6dc9a03"),
    (32, "deepseek-v4-pro", "run_ba6e7e75f9cc7938d349d5b996bdc043"),
    (33, "qwen3.8-max", "run_8f5784930878cd8aa4aac5437e20ffc9"),
    (34, "glm-5.2", "run_b524592255df5e46697dd55e8470da7a"),
    (35, "deepseek-v4-pro", "run_6b3f53b29a9f7e291314c54a57deb1b8"),
    (36, "qwen3.8-max", "run_0775d6733cf3dec94c8d97983036b0de"),
]

ZERO_SHA = "0" * 64
# Canonical exact key set used by the frozen v3.7 validator, plus value patterns.
SECRET_KEYS = {"api_key", "authorization", "bearer_token", "password", "client_secret", "access_token"}
SECRET_TEXT_RE = re.compile(r"(?:Bearer\s+[A-Za-z0-9._-]{16,}|sk-[A-Za-z0-9_-]{16,}|AKID[A-Za-z0-9_-]{8,}|LTAI[A-Za-z0-9]{12,})", re.I)


def canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csha(value: Any) -> str:
    return hashlib.sha256(canon(value).encode()).hexdigest()


def fsha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{csha(identity)[:32]}"


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Auditor:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        if not ok:
            self.errors.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


def scan_secrets_value(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in SECRET_KEYS:
                findings.append(child_path)
            findings.extend(scan_secrets_value(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_secrets_value(child, f"{path}[{index}]"))
    elif isinstance(value, str) and SECRET_TEXT_RE.search(value):
        findings.append(path)
    return findings


def audit_frozen_inputs(a: Auditor, plan: Mapping[str, Any], bundle: Mapping[str, Any], preflight: Mapping[str, Any]) -> None:
    # config
    a.check(fsha(CONFIG_PATH) == DECLARED["config"], "config file hash drift")
    # plan
    stripped = {k: v for k, v in plan.items() if k != "plan_sha256"}
    a.check(csha(stripped) == DECLARED["plan"], "plan content hash drift")
    a.check(plan.get("plan_sha256") == DECLARED["plan"], "plan self-hash drift")
    a.check(plan.get("plan_core_sha256") == DECLARED["plan_core"], "plan_core hash drift")
    a.check(plan.get("contract_version") == "3.9.0" and plan.get("run_cap") == 36, "plan identity wrong")
    # plan_core independent reconstruction
    config = read_json(CONFIG_PATH)
    core = {
        "contract_version": "3.9.0",
        "config_sha256": DECLARED["config"],
        "models": config.get("candidate_model_ids"),
        "task_inputs": [
            {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in plan["tasks"]
        ],
    }
    a.check(csha(core) == DECLARED["plan_core"], "plan_core independent reconstruction mismatch")
    # contract bundle
    a.check(bundle.get("bundle_sha256") == DECLARED["contract_bundle"], "contract bundle self-hash drift")
    a.check(csha(bundle.get("artifacts", [])) == bundle.get("bundle_sha256"), "contract bundle artifact-list mismatch")
    for item in bundle.get("artifacts", []):
        p = ROOT / item["path"]
        a.check(p.is_file() and fsha(p) == item["sha256"], f"contract artifact drift: {item['path']}")
    # preflight artifact
    pf_stripped = {k: v for k, v in preflight.items() if k != "preflight_sha256"}
    a.check(csha(pf_stripped) == DECLARED["preflight"], "preflight content hash drift")
    a.check(preflight.get("preflight_sha256") == DECLARED["preflight"], "preflight self-hash drift")
    a.check(fsha(PREFLIGHT_PATH) == DECLARED["preflight_file"], "preflight file hash drift")
    a.check(preflight.get("plan_sha256") == DECLARED["plan"], "preflight not plan-bound")
    a.check(preflight.get("contract_version") == "3.9.0" and preflight.get("contract_type") == "stage3_identity_preflight", "preflight contract identity wrong")
    a.check(preflight.get("decision") == "passed_3_of_3", "preflight decision not passed_3_of_3")
    counts = preflight.get("counts", {})
    a.check(counts.get("requested") == 3 and counts.get("passed") == 3 and counts.get("blocked") == 0, "preflight counts not 3/3")
    models = config.get("candidate_model_ids")
    rows = preflight.get("results", [])
    a.check([row.get("model_id") for row in rows] == models, "preflight model set/order mismatch")
    for row in rows:
        a.check(row.get("passed") is True and row.get("response_model_id") == row.get("model_id") and row.get("parameters_honored") is True and row.get("tool_capability_passed") is True, f"preflight unit not exact-pass: {row.get('model_id')}")


def audit_run_identity(a: Auditor, plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = plan["runs"]
    a.check(len(rows) == 36, f"plan runs count {len(rows)} != 36")
    by_run: dict[str, Mapping[str, Any]] = {}
    plan_order: list[str] = []
    for index, row in enumerate(rows):
        identity = row.get("run_identity", {})
        a.check(build_run_id(identity) == row.get("run_id"), f"run id derivation mismatch: {row.get('run_id')}")
        a.check(identity.get("harness_config_sha256") == DECLARED["config"], f"identity config binding wrong: {row.get('run_id')}")
        a.check(identity.get("plan_core_sha256") == DECLARED["plan_core"], f"identity plan_core binding wrong: {row.get('run_id')}")
        a.check(identity.get("benchmark_id") == "financial-agent-reliability-v3.9", f"identity benchmark id wrong: {row.get('run_id')}")
        a.check(identity.get("repeat") == 1, f"identity repeat != 1: {row.get('run_id')}")
        a.check(identity.get("requested_model_id") == row.get("model_id"), f"identity model mismatch: {row.get('run_id')}")
        a.check(isinstance(identity.get("seed"), int), f"identity seed not int: {row.get('run_id')}")
        plan_order.append(row["run_id"])
        by_run[row["run_id"]] = row
    # exact ordered equality with PER-52 pre-registration
    prereg_order = [run_id for _, _, run_id in PREREG]
    a.check(plan_order == prereg_order, "plan run order != PER-52 pre-registration order")
    a.check(sorted(plan_order) == sorted(prereg_order), "plan run set != PER-52 pre-registration set")
    for (seq, model, run_id), row in zip(PREREG, rows):
        a.check(row.get("run_id") == run_id and row.get("model_id") == model, f"prereg seq {seq} identity mismatch")
    # disjointness with historical rounds
    for version, path in [
        ("v3.5", ROOT / "runs/stage3/acceptance-20260812-v3.5/stage3_acceptance_plan.v3.5.json"),
        ("v3.8", ROOT / "runs/stage3/acceptance-20260812-v3.8/stage3_acceptance_plan.v3.8.json"),
    ]:
        old = {row["run_id"] for row in read_json(path)["runs"]}
        a.check(len(old) == 36, f"{version} historical plan run count != 36")
        overlap = old & set(plan_order)
        a.check(not overlap, f"run id intersection with {version}: {sorted(overlap)[:4]}")
    # task/row consistency: each task's run_ids partition the 36 rows; case_id identity binding
    task_of_run: dict[str, Mapping[str, Any]] = {}
    for task in plan["tasks"]:
        for run_id in task["run_ids"]:
            a.check(run_id in by_run and run_id not in task_of_run, f"task run partition broken at {run_id}")
            task_of_run[run_id] = task
            identity = by_run[run_id]["run_identity"]
            a.check(identity.get("case_id") == task["case_id"], f"identity case mismatch {run_id}")
            a.check(identity.get("variant_id") == task["variant_id"], f"identity variant mismatch {run_id}")
    a.check(len(task_of_run) == 36, "task partition does not cover 36 runs")
    a.check(len(plan["tasks"]) == 12, f"task count {len(plan['tasks'])} != 12")
    # fixture commitments: projection/snapshot file hashes equal plan commitments
    for task in plan["tasks"]:
        proj, snap = ROOT / task["projection_path"], ROOT / task["snapshot_path"]
        a.check(proj.is_file() and fsha(proj) == task["projection_sha256"], f"projection drift: {task['case_id']}")
        a.check(snap.is_file() and fsha(snap) == task["snapshot_sha256"], f"snapshot drift: {task['case_id']}")
    return task_of_run


def audit_checkpoint_chain(a: Auditor, path: pathlib.Path, trace: Mapping[str, Any]) -> int:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = ZERO_SHA
    last_sha = None
    for offset, event in enumerate(lines):
        body = {k: v for k, v in event.items() if k != "event_sha256"}
        claimed = event.get("event_sha256")
        a.check(claimed == csha(body), f"{trace.get('run_id')} checkpoint[{offset}] event hash mismatch")
        a.check(body.get("previous_event_sha256") == previous, f"{trace.get('run_id')} checkpoint[{offset}] chain broken")
        a.check(body.get("offset") == offset, f"{trace.get('run_id')} checkpoint[{offset}] offset gap")
        a.check(body.get("run_id") == trace.get("run_id"), f"{trace.get('run_id')} checkpoint[{offset}] run id mismatch")
        a.check(not scan_secrets_value(event), f"{trace.get('run_id')} checkpoint[{offset}] secret-like value")
        previous = claimed
        last_sha = claimed
    a.check(bool(lines) and lines[0].get("event_type") == "run_started", f"{trace.get('run_id')} checkpoint missing run_started")
    a.check(bool(lines) and lines[0].get("payload", {}).get("plan_sha256") == DECLARED["plan"], f"{trace.get('run_id')} checkpoint not plan-bound")
    a.check(bool(lines) and lines[-1].get("event_type") == "run_completed", f"{trace.get('run_id')} checkpoint missing run_completed")
    checkpoint = trace.get("checkpoint", {})
    a.check(checkpoint.get("event_count") == len(lines), f"{trace.get('run_id')} checkpoint event_count mismatch")
    a.check(checkpoint.get("final_event_sha256") == last_sha, f"{trace.get('run_id')} checkpoint final event mismatch")
    a.check(bool(lines) and lines[-1].get("payload", {}).get("status") == trace.get("status"), f"{trace.get('run_id')} checkpoint terminal status mismatch")
    return len(lines)


def audit_run(a: Auditor, run_id: str, row: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    trace_path = RUN_DIR / "traces" / f"{run_id}.json"
    grader_path = RUN_DIR / "graders" / f"{run_id}.json"
    candidate_path = RUN_DIR / "candidates" / f"{run_id}.json"
    checkpoint_path = RUN_DIR / "checkpoints" / f"{run_id}.jsonl"
    for p in (trace_path, grader_path, candidate_path, checkpoint_path):
        a.check(p.is_file(), f"missing artifact: {p.name}")
    trace = read_json(trace_path)
    grader = read_json(grader_path)
    candidate = read_json(candidate_path)
    # bindings
    a.check(trace.get("run_id") == run_id, f"{run_id} trace run_id mismatch")
    a.check(trace.get("run_identity") == row.get("run_identity"), f"{run_id} trace identity mismatch")
    a.check(trace.get("contract_version") == "3.9.0" and trace.get("contract_type") == "run_trace", f"{run_id} trace contract identity wrong")
    a.check(trace.get("provider", {}).get("requested_model_id") == row.get("model_id"), f"{run_id} requested model mismatch")
    # candidate commitment inside trace
    a.check(trace.get("result", {}).get("candidate_output_sha256") == csha(candidate), f"{run_id} candidate hash binding mismatch")
    # grader self hash (computed over grader without the grader_sha256 key)
    grader_stripped = {k: v for k, v in grader.items() if k != "grader_sha256"}
    a.check(grader.get("grader_sha256") == csha(grader_stripped), f"{run_id} grader self-hash mismatch")
    a.check(grader.get("run_id") == run_id, f"{run_id} grader run_id mismatch")
    # grader internal consistency: failed_checks == checks that are False
    checks = grader.get("checks", {})
    failed = [name for name, value in checks.items() if value is False]
    a.check(sorted(failed) == sorted(grader.get("failed_checks", [])), f"{run_id} failed_checks inconsistent with checks")
    applicable = [name for name, value in checks.items() if value is not None]
    a.check(grader.get("all_applicable_checks_passed") == (all(checks[name] is True for name in applicable)), f"{run_id} all_applicable_checks_passed inconsistent")
    # checkpoint chain
    events = audit_checkpoint_chain(a, checkpoint_path, trace)
    # usage cross-checks
    attempts = [attempt for request in trace.get("logical_requests", []) for attempt in request.get("attempts", [])]
    usage = trace.get("usage", {})
    a.check(usage.get("model_requests") == len(trace.get("logical_requests", [])), f"{run_id} usage model_requests mismatch")
    a.check(usage.get("provider_attempts") == len(attempts), f"{run_id} usage provider_attempts mismatch")
    a.check(usage.get("tool_calls") == len(trace.get("tool_events", [])), f"{run_id} usage tool_calls mismatch")
    a.check(usage.get("total_tokens") == sum(item.get("input_tokens", 0) + item.get("output_tokens", 0) for item in attempts), f"{run_id} token total inconsistent")
    # identity / fallback
    requested = row.get("model_id")
    fallbacks = [item for item in attempts if item.get("response_model_id") is not None and item.get("response_model_id") != requested]
    identity_valid = all(item.get("response_model_id") in (None, requested) for item in attempts) and trace.get("provider", {}).get("response_model_id") in (None, requested)
    a.check(not fallbacks, f"{run_id} fallback attempt detected")
    a.check(identity_valid, f"{run_id} identity invalid")
    # every attempt classification consistent with request classification
    for request in trace.get("logical_requests", []):
        a.check(request.get("attempts", [{}])[-1].get("classification") == request.get("classification"), f"{run_id} request/attempt classification mismatch")
        for attempt in request.get("attempts", []):
            a.check(attempt.get("model_id") == requested, f"{run_id} attempt model mismatch")
    # environment / permission / PIT
    environment = trace.get("environment", {})
    a.check(environment.get("real_side_effects") is False, f"{run_id} real side effects flagged")
    a.check((environment.get("final_state_matches_initial") is True) == (environment.get("initial_ledger_sha256") == environment.get("final_ledger_sha256")), f"{run_id} terminal state claim inconsistent")
    a.check(environment.get("ledger_mode") == "simulated" and environment.get("dataset_access") == "frozen_read_only", f"{run_id} environment mode wrong")
    permission = trace.get("permission", {})
    projection = read_json(ROOT / task["projection_path"])
    a.check(permission.get("declared_permissions") == projection.get("task", {}).get("permissions"), f"{run_id} declared permissions mismatch")
    # Violations are legitimate candidate failures when the grader fails
    # permission_boundary_respected; audit error only if ungraded.
    if permission.get("violations"):
        a.check(checks.get("permission_boundary_respected") is False, f"{run_id} permission violations recorded but not graded failed: {permission.get('violations')}")
    # secret scan over every persisted per-run artifact
    for label, value in (("trace", trace), ("grader", grader), ("candidate", candidate)):
        a.check(not scan_secrets_value(value), f"{run_id} secret-like value in {label}")
    # PIT: evidence observations must match snapshot temporal fields
    snapshot = read_json(ROOT / task["snapshot_path"])
    temporal = snapshot.get("temporal", {})
    for obs in trace.get("evidence_observations", []):
        a.check(obs.get("available_at") == temporal.get("available_at") and obs.get("event_time") == temporal.get("event_time"), f"{run_id} evidence observation temporal mismatch")
    return {
        "run_id": run_id,
        "case_id": task.get("case_id"),
        "model_id": requested,
        "status": trace.get("status"),
        "failure_class": trace.get("failure", {}).get("class"),
        "model_requests": usage.get("model_requests"),
        "provider_attempts": usage.get("provider_attempts"),
        "total_tokens": usage.get("total_tokens"),
        "checkpoint_events": events,
        "structured_output_valid": trace.get("result", {}).get("structured_output_valid"),
        "all_applicable_checks_passed": grader.get("all_applicable_checks_passed"),
        "value_semantic_correct": checks.get("value_semantic_correct"),
        "failed_checks": grader.get("failed_checks", []),
        "provider_failures": sum(1 for item in attempts if item.get("classification") == "provider_or_runtime_failure"),
        "permission_violations": permission.get("violations", []),
    }


def audit_evidence_manifest(a: Auditor, records: list[dict[str, Any]]) -> None:
    manifest = read_json(MANIFEST_PATH)
    artifacts = manifest.get("artifacts", [])
    a.check(len(artifacts) == 152, f"manifest artifact count {len(artifacts)} != 152")
    a.check(manifest.get("bundle_sha256") == DECLARED["evidence_bundle"], "evidence bundle self-hash drift")
    a.check(csha(artifacts) == manifest.get("bundle_sha256"), "evidence bundle content-hash mismatch")
    a.check(manifest.get("plan_sha256") == DECLARED["plan"], "manifest plan binding wrong")
    a.check(manifest.get("config_sha256") == DECLARED["config"], "manifest config binding wrong")
    a.check(manifest.get("contract_bundle_sha256") == DECLARED["contract_bundle"], "manifest contract bundle binding wrong")
    a.check(manifest.get("preflight_sha256") == DECLARED["preflight"], "manifest preflight binding wrong")
    # expected composition: 36x4 per-run + preflight + 2 authorizations + runtime-summary + summary + 3 frozen copies
    expected: set[str] = set()
    for record in records:
        run_id = record["run_id"]
        expected.update(f"{sub}/{run_id}.json" for sub in ("candidates", "traces", "graders"))
        expected.add(f"checkpoints/{run_id}.jsonl")
    expected.update([
        "preflight.json", "authorization.preflight.json", "authorization.run.json",
        "runtime-summary.json", "summary.json",
        "stage3_acceptance_contracts.frozen.v3.9.json", "stage3_acceptance_plan.v3.9.json", "run_trace_harness_config.v3.9.json",
    ])
    paths = [item["path"] for item in artifacts]
    a.check(len(set(paths)) == len(paths), "manifest paths not unique")
    a.check(set(paths) == expected, f"manifest composition mismatch: extra={sorted(set(paths) - expected)[:4]} missing={sorted(expected - set(paths))[:4]}")
    # every artifact byte hash verified against disk
    for item in artifacts:
        p = RUN_DIR / item["path"]
        a.check(p.is_file() and fsha(p) == item["sha256"], f"evidence artifact drift: {item['path']}")
    # summary/runtime-summary file hashes as declared
    a.check(fsha(RUN_DIR / "summary.json") == DECLARED["summary_file"], "summary file hash drift")
    a.check(fsha(RUN_DIR / "runtime-summary.json") == DECLARED["runtime_summary_file"], "runtime-summary file hash drift")


def audit_authorizations(a: Auditor, plan: Mapping[str, Any], preflight: Mapping[str, Any]) -> None:
    run_auth = read_json(RUN_DIR / "authorization.run.json")
    a.check(run_auth.get("paid_calls_authorized") is True and run_auth.get("authorization_kind") == "financial_acceptance_36_run", "36-run authorization kind wrong")
    a.check(run_auth.get("plan_sha256") == DECLARED["plan"], "run authorization plan binding wrong")
    a.check(run_auth.get("preflight_sha256") == DECLARED["preflight"], "run authorization preflight binding wrong")
    a.check(run_auth.get("authorized_run_ids") == [row["run_id"] for row in plan["runs"]], "run authorization run-id scope mismatch")
    pre_auth = read_json(RUN_DIR / "authorization.preflight.json")
    a.check(pre_auth.get("paid_calls_authorized") is True and pre_auth.get("authorization_kind") == "identity_preflight" and pre_auth.get("maximum_model_units") == 3, "preflight authorization kind wrong")
    a.check(pre_auth.get("plan_sha256") == DECLARED["plan"], "preflight authorization plan binding wrong")
    config = read_json(CONFIG_PATH)
    for auth in (run_auth, pre_auth):
        a.check(auth.get("exact_model_ids") == config.get("candidate_model_ids"), "authorization model scope mismatch")
        a.check(not scan_secrets_value(auth), "secret-like value in authorization artifact")


def audit_counts_vs_summary(a: Auditor, records: list[dict[str, Any]]) -> None:
    summary = read_json(RUN_DIR / "summary.json")
    runtime = read_json(RUN_DIR / "runtime-summary.json")

    def count(fn) -> int:
        return sum(1 for record in records if fn(record))

    independent = {
        "planned": len(records),
        "succeeded": count(lambda r: r["status"] == "succeeded"),
        "candidate_failed": count(lambda r: r["status"] == "candidate_failed"),
        "invalid_provider_or_runtime": count(lambda r: r["status"] == "invalid_provider_or_runtime"),
        "structured_results": count(lambda r: r["structured_output_valid"] is True),
        "all_applicable_checks_passed": count(lambda r: r["all_applicable_checks_passed"] is True),
        "value_semantic_correct": count(lambda r: r["value_semantic_correct"] is True),
        "provider_attempts": sum(r["provider_attempts"] for r in records),
        "provider_failures": sum(r["provider_failures"] for r in records),
        "total_tokens": sum(r["total_tokens"] for r in records),
        "checkpoint_events": sum(r["checkpoint_events"] for r in records),
    }
    declared_counts = summary.get("counts", {})
    for key, value in independent.items():
        a.check(declared_counts.get(key) == value, f"summary counts[{key}]={declared_counts.get(key)} != independent {value}")
    a.check(declared_counts.get("fallback") == 0, "summary fallback count nonzero")
    a.check(declared_counts.get("secret_leakage") == 0, "summary secret leakage nonzero")
    a.check(declared_counts.get("unsafe_or_real_side_effect") == 0, "summary unsafe side-effect count nonzero")
    a.check(summary.get("status") == "completed" and summary.get("reconciliation_errors") == [], "implementation-side reconciliation not clean")
    a.check(summary.get("plan_sha256") == DECLARED["plan"] and summary.get("preflight_sha256") == DECLARED["preflight"], "summary bindings wrong")
    a.check(summary.get("cost_usd") is None, "cost_usd not null")
    a.check(runtime.get("counts", {}).get("accepted") == independent["all_applicable_checks_passed"], "runtime-summary accepted count mismatch")
    a.check(runtime.get("plan_sha256") == DECLARED["plan"] and runtime.get("preflight_sha256") == DECLARED["preflight"], "runtime-summary bindings wrong")
    # per-model independent table
    for model in sorted({r["model_id"] for r in records}):
        subset = [r for r in records if r["model_id"] == model]
        by_model = summary.get("by_model", {}).get(model, {})
        a.check(by_model.get("runs") == len(subset) == 12, f"{model} runs != 12")
        a.check(by_model.get("succeeded") == sum(1 for r in subset if r["status"] == "succeeded"), f"{model} succeeded count mismatch")
        a.check(by_model.get("value_semantic_correct") == sum(1 for r in subset if r["value_semantic_correct"] is True), f"{model} semantic count mismatch")
        a.check(by_model.get("all_applicable_checks_passed") == sum(1 for r in subset if r["all_applicable_checks_passed"] is True), f"{model} all-checks count mismatch")
        a.check(by_model.get("provider_attempts") == sum(r["provider_attempts"] for r in subset), f"{model} attempts mismatch")
        a.check(by_model.get("provider_failures") == 0, f"{model} provider failures nonzero")


def audit_raw_secret_sweep(a: Auditor) -> None:
    """Byte-level sweep of the whole run directory (all 152 artifacts + anything else)."""
    env_key = os.environ.get("BENCH_BAILIAN_API_KEY")
    key_marker = env_key.encode() if env_key else None
    if key_marker:
        a.note("BENCH_BAILIAN_API_KEY present in auditor environment; literal sweep enabled")
    patterns = [
        re.compile(rb"Bearer\s+[A-Za-z0-9._-]{16,}"),
        re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(rb"AKID[A-Za-z0-9_-]{8,}"),
        re.compile(rb"LTAI[A-Za-z0-9]{12,}"),
    ]
    scanned = 0
    for path in sorted(RUN_DIR.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        data = path.read_bytes()
        for pattern in patterns:
            a.check(not pattern.search(data), f"secret-like text in {path.relative_to(RUN_DIR)}")
        if key_marker:
            a.check(key_marker not in data, f"literal BENCH_BAILIAN_API_KEY found in {path.relative_to(RUN_DIR)}")
    a.note(f"raw byte sweep covered {scanned} files under the run directory")


def main() -> int:
    a = Auditor()
    plan = read_json(PLAN_PATH)
    bundle = read_json(BUNDLE_PATH)
    preflight = read_json(PREFLIGHT_PATH)

    audit_frozen_inputs(a, plan, bundle, preflight)
    task_of_run = audit_run_identity(a, plan)
    records = [audit_run(a, row["run_id"], row, task_of_run[row["run_id"]]) for row in plan["runs"]]
    audit_evidence_manifest(a, records)
    audit_authorizations(a, plan, preflight)
    audit_counts_vs_summary(a, records)
    audit_raw_secret_sweep(a)

    # permission violations surfaced as findings (deepseek ftw-07 is expected to have one)
    violations = [(r["run_id"], r["case_id"], r["permission_violations"]) for r in records if r["permission_violations"]]
    failed_units = [r for r in records if not r["all_applicable_checks_passed"]]

    report = {
        "audit": "PER-56 v3.9 final delivery audit (independent, stdlib-only)",
        "verdict": "PASS" if not a.errors else "FAIL",
        "error_count": len(a.errors),
        "errors": a.errors,
        "notes": a.notes,
        "counts": {
            "planned": len(records),
            "succeeded": sum(1 for r in records if r["status"] == "succeeded"),
            "candidate_failed": sum(1 for r in records if r["status"] == "candidate_failed"),
            "invalid_provider_or_runtime": sum(1 for r in records if r["status"] == "invalid_provider_or_runtime"),
            "structured_results": sum(1 for r in records if r["structured_output_valid"] is True),
            "value_semantic_correct": sum(1 for r in records if r["value_semantic_correct"] is True),
            "all_applicable_checks_passed": sum(1 for r in records if r["all_applicable_checks_passed"] is True),
            "provider_attempts": sum(r["provider_attempts"] for r in records),
            "provider_failures": sum(r["provider_failures"] for r in records),
            "total_tokens": sum(r["total_tokens"] for r in records),
            "checkpoint_events": sum(r["checkpoint_events"] for r in records),
        },
        "failed_units": [
            {"run_id": r["run_id"], "case_id": r["case_id"], "model_id": r["model_id"], "failed_checks": r["failed_checks"]}
            for r in failed_units
        ],
        "permission_violations": violations,
    }
    out = ROOT / "audit" / "stage3_v3_9_delivery_audit_result.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, ensure_ascii=False, indent=1))
    if a.errors:
        print("ERRORS:", file=sys.stderr)
        for error in a.errors:
            print(" -", error, file=sys.stderr)
    return 0 if not a.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
