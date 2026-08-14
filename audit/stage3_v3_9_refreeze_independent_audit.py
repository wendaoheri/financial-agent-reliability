"""Independent re-audit of the PER-52 v3.9 re-freeze (PER-54, Stage 3C-5).

Auditor: independent scoring & statistics auditor (separated from case authoring,
oracle, and harness implementation). Read-only audit: this script never writes
frozen artifacts, never reads credentials, and never triggers provider calls.

Everything below the "clean room" line is an independent re-implementation of
the canonical hash convention (sorted-key compact JSON, UTF-8, SHA-256). Nothing
is imported from the harness under audit except hash-locked frozen artifacts
whose hashes are verified FIRST (v3.7-locked clean-room oracle helpers and the
v3.9 gate functions).

Usage:
    uv run python -m audit.stage3_v3_9_refreeze_independent_audit
Prints one line per check and a final `total checks=N failures=M` /
`INDEPENDENT_VERDICT=PASS|FAIL` line.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from decimal import Decimal
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- declared values under audit (PER-52 re-declaration, PER-54 frozen inputs) --
NEW = {
    "bundle": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "plan": "235b0415bf43c356a5f2c3801a7793606ed5e943a5e8ce60f0aa3b20abeeb185",
    "plan_core": "bf1d1ed48b0f5728b0f2f71bcd13af91dc7a9ed586c0f2ffbe9cebaf7e804ebd",
    "config": "e06b3fae6acf1ab76716c3a507163601fa6249f6160a8dbfce1216f8080e0cfa",
    "audit_script": "f4afe6e64716f01c9e957aa5f09295d6f36de373cafbc75c0b4f66870ef35978",
}
OLD_AUDIT_SCRIPT = "9cf92f235c1fd306354a3bbc4175c3a12ede8c6186f9bfc38d37dcf4b19a561d"
# pre-re-freeze v3.9 values as declared by PER-48 delivery comment 7a42b3ce
OLD = {
    "bundle": "f4461964e13869ba2a00c3b8f13394f09d085541655419cf9fe5c36af93b188d",
    "plan": "e5ca961f368018b7d0e24f16c6b633dbfb47c0e05f0d5e935a4921ea5009e9b6",
    "plan_core": "e3b7eeb75780e668975e7a465d27ed52a554541fad1643b8aec84ec8daebed73",
    "config": "f9702fa6e3d8939a1021211a3339ea6a18ec960fc74de2658c6bb06c0dbe192c",
}
BASELINE = {
    "v3_5_bundle": "d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8",
    "v3_6_bundle": "afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959",
    "v3_7_bundle": "354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44",
    "v3_8_bundle": "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609",
    "v3_8_plan": "636d94fbb6d08d58adfd018dfba6115bb44ac193480a5380e3228c623a4c3d22",
    "v3_8_plan_core": "f272700eddfb1e91d405ab30079dd93324dd87eda666a164d10ede81cff666ae",
    "oracle_file": "9097915075c71bf6344cfadbe0486c508259dd5de8dd47d6c325fccde169858d",
    "proj_fkw03": "9a1cb68f7bfd0fbd106c712ea3cefc76cafc6de5429be22f217d1150ecf6e4f2",
    "proj_fkw07": "9d7605a5127310d08207b1131e3a5a7a76467b84f1b570c253771a2964b0483a",
    "audit_report_v3_8": "ba5fbd7a49507a7f04ddd7f90273d0bda0b4433f97cde206067a48a921b1e076",
}
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
FKW03 = "case-public-fkw-03-single-factor-perturbation-v3"
FKW07 = "case-public-fkw-07-single-factor-perturbation-v3"

# 36 run identities published in PER-52 delivery comment 12939662 (seq, model, run_id)
DECLARED_RUNS = [
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

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(f"[{'ok' if ok else 'FAIL'}] {label}")


# --- clean-room canonical hash re-implementation (independent) ----------------


def canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csha(value: Any) -> str:
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def fsha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rjson(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{csha(dict(identity))[:32]}"


def main() -> None:
    b39 = rjson(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.9.json")
    p39 = rjson(ROOT / "contracts/stage3_acceptance_plan.v3.9.json")
    cfg39_path = ROOT / "contracts/run_trace_harness_config.v3.9.json"
    cfg39 = rjson(cfg39_path)
    cfg38 = rjson(ROOT / "contracts/run_trace_harness_config.v3.8.json")
    p38 = rjson(ROOT / "contracts/stage3_acceptance_plan.v3.8.json")

    # =========================================================================
    # H1-H5. independent recomputation of every declared v3.9 hash
    # =========================================================================
    cfg39_hash = fsha(cfg39_path)
    check(cfg39_hash == NEW["config"], "H1 v3.9 config file hash == declared e06b3fae...")
    audit_src_path = ROOT / "audit/audit_stage3_v3_9_delivery.py"
    check(fsha(audit_src_path) == NEW["audit_script"], "H2 implementation audit script file hash == declared f4afe6e6...")

    artifacts = b39["artifacts"]
    drift = [a["path"] for a in artifacts if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
    check(len(artifacts) == 21 and not drift, f"H3a v3.9 bundle manifest: 21 artifacts, every file hash matches disk (drift: {drift})")
    check(csha(artifacts) == NEW["bundle"] == b39["bundle_sha256"], "H3b bundle_sha256 == clean-room content hash of manifest == declared 77aea093...")
    manifest = {a["path"]: a["sha256"] for a in artifacts}
    check(manifest.get("contracts/run_trace_harness_config.v3.9.json") == cfg39_hash, "H3c manifest binds the exact config file hash that plan_core binds")

    plan_minus_self = {k: v for k, v in p39.items() if k != "plan_sha256"}
    check(csha(plan_minus_self) == NEW["plan"] == p39["plan_sha256"], "H4a plan_sha256 == clean-room recompute (sans self-hash field) == declared 235b0415...")
    check(p39["plan_core_sha256"] == NEW["plan_core"], "H4b plan_core_sha256 field == declared bf1d1ed4...")

    # H5 plan_core reconstructed from the documented formula, all inputs off disk
    tasks39 = p39["tasks"]
    core_inputs = []
    task_input_ok = True
    for task in tasks39:
        proj_hash = fsha(ROOT / task["projection_path"])
        snap_hash = fsha(ROOT / task["snapshot_path"])
        if proj_hash != task["projection_sha256"] or snap_hash != task["snapshot_sha256"]:
            task_input_ok = False
        core_inputs.append({k: task[k] for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]})
    check(task_input_ok, "H5a 12/12 task projection/snapshot file hashes match plan-declared values")
    # tool_schemas_v37 comes from harness/acceptance_v3_7.py, hash-locked in the
    # frozen v3.7 bundle; verify the lock BEFORE importing anything from it.
    v37_bundle = rjson(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.7.json")
    v37_manifest = {a["path"]: a["sha256"] for a in v37_bundle["artifacts"]}
    check(v37_manifest.get("harness/acceptance_v3_7.py") == fsha(ROOT / "harness/acceptance_v3_7.py"),
          "H5b harness/acceptance_v3_7.py hash-locked in frozen v3.7 bundle (pre-import lock)")
    from harness.acceptance_v3_7 import independent_expected_from_snapshot, tool_schemas_v37  # noqa: E402
    tool_ok = all(csha(tool_schemas_v37(rjson(ROOT / t["projection_path"]))) == t["tool_schema_sha256"] for t in tasks39)
    check(tool_ok, "H5c 12/12 tool_schema_sha256 recompute via hash-locked tool_schemas_v37")
    core = {"contract_version": "3.9.0", "config_sha256": cfg39_hash, "models": MODELS, "task_inputs": core_inputs}
    check(csha(core) == NEW["plan_core"], "H5d plan_core independently reconstructed (config hash + models + 12 task inputs) == declared bf1d1ed4...")

    # =========================================================================
    # H6-H8. historical zero-drift and supersedes chain
    # =========================================================================
    for version, wanted, count in [("3.5", BASELINE["v3_5_bundle"], 8), ("3.6", BASELINE["v3_6_bundle"], 33),
                                   ("3.7", BASELINE["v3_7_bundle"], 20), ("3.8", BASELINE["v3_8_bundle"], 15)]:
        bundle = rjson(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        adr = [a["path"] for a in bundle.get("artifacts", []) if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
        check(bundle.get("bundle_sha256") == wanted and not adr and len(bundle.get("artifacts", [])) == count,
              f"H6 v{version} bundle: declared hash + {count} artifact file hashes zero-drift (drift: {adr})")
    check(csha({k: v for k, v in p38.items() if k != "plan_sha256"}) == BASELINE["v3_8_plan"] == p38["plan_sha256"],
          "H7a v3.8 plan_sha256 clean-room recompute == declared 636d94fb...")
    check(p38["plan_core_sha256"] == BASELINE["v3_8_plan_core"], "H7b v3.8 plan_core_sha256 == declared f272700e...")

    check(b39["supersedes"]["path"] == "contracts/stage3_acceptance_contracts.frozen.v3.8.json"
          and b39["supersedes"]["sha256"] == fsha(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.8.json")
          and b39["supersedes"]["v3_8_bundle_sha256"] == BASELINE["v3_8_bundle"],
          "H8a v3.9 bundle supersedes v3.8 bundle (file hash + content hash)")
    check(p39["supersedes"]["path"] == "contracts/stage3_acceptance_plan.v3.8.json"
          and p39["supersedes"]["sha256"] == fsha(ROOT / "contracts/stage3_acceptance_plan.v3.8.json")
          and p39["supersedes"]["plan_sha256"] == p38["plan_sha256"],
          "H8b v3.9 plan supersedes v3.8 plan (file hash + plan hash)")
    check(cfg39["supersedes"]["path"] == "contracts/run_trace_harness_config.v3.8.json"
          and cfg39["supersedes"]["sha256"] == fsha(ROOT / "contracts/run_trace_harness_config.v3.8.json"),
          "H8c v3.9 config supersedes v3.8 config (file hash)")
    for cid in (FKW03, FKW07):
        proj = rjson(ROOT / f"cases/candidate_v3_9/{cid}.json")
        src = ROOT / f"cases/candidate_v3_6/{cid}.json"
        check(proj["supersedes"]["path"] == f"cases/candidate_v3_6/{cid}.json" and proj["supersedes"]["sha256"] == fsha(src),
              f"H8d {cid} v3.9 projection supersedes its v3.6 source (file hash)")
    chain_ok = True
    for version, prev in [("3.6", "3.5"), ("3.7", "3.6"), ("3.8", "3.7")]:
        bundle = rjson(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        sup = bundle.get("supersedes") or {}
        if not (isinstance(sup, Mapping) and sup.get("sha256") == fsha(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{prev}.json")):
            chain_ok = False
    check(chain_ok, "H8e historical bundle chain v3.5<-v3.6<-v3.7<-v3.8 file-hash consistent")
    check(b39["preserved"] == {"v3_5_bundle_sha256": BASELINE["v3_5_bundle"], "v3_6_bundle_sha256": BASELINE["v3_6_bundle"],
                               "v3_7_bundle_sha256": BASELINE["v3_7_bundle"], "v3_8_bundle_sha256": BASELINE["v3_8_bundle"],
                               "retroactive_regrading": False},
          "H8f preserved block pins all four historical bundle hashes and retroactive_regrading=false")

    # =========================================================================
    # H9. the single PER-51 failure item is closed: declaration <-> enforcement
    # =========================================================================
    check(cfg39["semantic_bindings"]["calculation"] == "executed_decimal_rational_v3_9",
          "H9a config semantic_bindings.calculation declares executed_decimal_rational_v3_9")
    v39_src = (ROOT / "harness/acceptance_v3_9.py").read_text(encoding="utf-8")
    mjs_src = (ROOT / "harness/live_acceptance_v3_9.mjs").read_text(encoding="utf-8")
    check('CALCULATION_IMPLEMENTATION = "decimal_rational_v3_9"' in v39_src,
          "H9b harness CALCULATION_IMPLEMENTATION == decimal_rational_v3_9 (enforced tag)")
    check('item.get("implementation") == CALCULATION_IMPLEMENTATION' in v39_src,
          "H9c grader binds tool-event implementation to CALCULATION_IMPLEMENTATION")
    check('implementation: "decimal_rational_v3_9"' in mjs_src, "H9d live runner (mjs) emits implementation decimal_rational_v3_9")
    fixture_tag_drift = []
    for path in sorted((ROOT / "tests/fixtures/acceptance_v3_9").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        if '"implementation"' in text and "decimal_rational_v3_9" not in text:
            fixture_tag_drift.append(path.name)
        if "decimal_rational_v3_8" in text:
            fixture_tag_drift.append(f"{path.name}:old-tag")
    check(not fixture_tag_drift, f"H9e all v3.9 fixtures carrying implementation labels use the new tag (drift: {fixture_tag_drift})")
    old_tag_anywhere = [name for name, text in [
        ("config.v3.9", cfg39_path.read_text(encoding="utf-8")), ("acceptance_v3_9.py", v39_src),
        ("live_acceptance_v3_9.mjs", mjs_src),
        ("run_trace_validator_v3_9.py", (ROOT / "contracts/run_trace_validator_v3_9.py").read_text(encoding="utf-8")),
    ] if "decimal_rational_v3_8" in text]
    check(not old_tag_anywhere, f"H9f zero occurrences of the old tag in the v3.9 enforcement surface (hits: {old_tag_anywhere})")
    v38_src = (ROOT / "harness/acceptance_v3_8.py").read_text(encoding="utf-8")
    check('item.get("implementation") == "decimal_rational_v3_8"' in v38_src
          and cfg38["semantic_bindings"]["calculation"] == "executed_decimal_rational_v3_8",
          "H9g pairing convention consistent with v3.8 (declared executed_decimal_rational_v3_8 <-> enforced decimal_rational_v3_8)")

    # =========================================================================
    # H10. config delta vs v3.8: nothing smuggled
    # =========================================================================
    diff_keys = sorted(k for k in set(cfg38) | set(cfg39) if canon(cfg38.get(k)) != canon(cfg39.get(k)))
    check(diff_keys == ["contract_repair", "contract_version", "semantic_bindings", "supersedes"],
          f"H10a v3.9 config top-level delta limited to contract_repair/contract_version/semantic_bindings/supersedes (got {diff_keys})")
    exec_delta = sorted(k for k in set(cfg38["execution"]) | set(cfg39["execution"]) if canon(cfg38["execution"].get(k)) != canon(cfg39["execution"].get(k)))
    check(exec_delta == [] and cfg39["execution"]["paid_calls_authorized"] is False and cfg39["execution"]["offline_validation_only"] is True,
          f"H10b execution block byte-identical to v3.8; paid_calls_authorized=false, offline_validation_only=true (delta {exec_delta})")
    check(cfg39["request_commitments"]["parameters_sha256_by_model"] == cfg38["request_commitments"]["parameters_sha256_by_model"]
          and set(cfg39["request_commitments"]["parameters_sha256_by_model"]) == set(MODELS),
          "H10c per-model request parameter commitments unchanged from v3.8 and cover exactly the 3 models")
    sem_delta = {k: (cfg38.get("semantic_bindings", {}).get(k), cfg39["semantic_bindings"].get(k))
                 for k in set(cfg38.get("semantic_bindings", {})) | set(cfg39["semantic_bindings"])
                 if canon(cfg38.get("semantic_bindings", {}).get(k)) != canon(cfg39["semantic_bindings"].get(k))}
    check(sem_delta == {"calculation": ("executed_decimal_rational_v3_8", "executed_decimal_rational_v3_9"),
                        "decimal_output_contract_visibility_gate": (None, "oracle_expectations_subset_of_candidate_visible_contract_v3_9")},
          f"H10d semantic_bindings delta is exactly the calculation tag bump + the visibility gate (got {sem_delta})")

    # =========================================================================
    # H11. projections / oracle / expectations unchanged by the re-freeze
    # =========================================================================
    check(fsha(ROOT / f"cases/candidate_v3_9/{FKW03}.json") == BASELINE["proj_fkw03"]
          and fsha(ROOT / f"cases/candidate_v3_9/{FKW07}.json") == BASELINE["proj_fkw07"],
          "H11a fkw-03/fkw-07 v3.9 projection hashes unchanged vs the PER-51-era declared values")
    check(fsha(ROOT / "cases/public/oracle.py") == BASELINE["oracle_file"], "H11b cases/public/oracle.py file hash == PER-28 registered hash")
    exp_mismatch = []
    for t39 in tasks39:
        t38 = next(t for t in p38["tasks"] if t["case_id"] == t39["case_id"])
        snapshot = rjson(ROOT / t39["snapshot_path"])
        exp_new = independent_expected_from_snapshot(rjson(ROOT / t39["projection_path"]), snapshot)
        exp_old = independent_expected_from_snapshot(rjson(ROOT / t38["projection_path"]), snapshot)
        if canon(exp_new) != canon(exp_old):
            exp_mismatch.append(t39["case_id"])
        if t39["snapshot_path"] != t38["snapshot_path"] or t39["snapshot_sha256"] != t38["snapshot_sha256"]:
            exp_mismatch.append(f"{t39['case_id']}:snapshot-moved")
    check(not exp_mismatch, "H11c 12/12 oracle expected values canonical-identical v3.8-era vs v3.9 projections; snapshots unmoved")
    check(fsha(ROOT / "audit/stage3-v3.8-delivery-audit-20260812.md") == BASELINE["audit_report_v3_8"]
          and b39["audit_repair"]["audit_report_sha256"] == BASELINE["audit_report_v3_8"],
          "H11d v3.8 delivery audit report hash unchanged and still bound by audit_repair")

    # =========================================================================
    # H12. forensic byte-diff of the implementation audit script
    # =========================================================================
    # The diff scope is derived from the recorded PER-52 edit: inside the DECLARED
    # block only — section header line rewritten, 3 comment lines inserted, and the
    # 4 v3.9 declared hashes updated. Reverting exactly that must reproduce the
    # PER-51-era script byte-for-byte (hash 9cf92f23..., published in the PER-51
    # report BEFORE PER-52 ran).
    new_text = audit_src_path.read_text(encoding="utf-8")
    reverted = (new_text
                .replace(NEW["bundle"], OLD["bundle"])
                .replace(NEW["plan"] + '"', OLD["plan"] + '"')
                .replace(NEW["plan_core"], OLD["plan_core"])
                .replace(NEW["config"], OLD["config"])
                .replace("# --- declared values (implementation-side claims to verify) -----------------\n"
                         "# PER-52 re-declaration: the four v3.9 values below were updated to the re-frozen\n"
                         "# hashes after the minimal fix of semantic_bindings.calculation; every other\n"
                         "# declared value is unchanged from PER-51.\n",
                         "# --- declared values from PER-51 (implementation-side claims to verify) -----\n"))
    check(hashlib.sha256(reverted.encode("utf-8")).hexdigest() == OLD_AUDIT_SCRIPT,
          "H12a reverting the DECLARED-block re-declaration (4 hashes + header + 3 comments) reproduces byte-for-byte the PER-51 script hash 9cf92f23...")
    new_lines, old_lines = new_text.splitlines(), reverted.splitlines()
    check(len(new_lines) - len(old_lines) == 3, f"H12b line-count delta == 3 (the PER-52 comment lines); got {len(new_lines) - len(old_lines)}")
    # explicit pairwise comparison outside the DECLARED block re-declaration (new-file lines 31-34)
    head_changes = [i + 1 for i, (a, b) in enumerate(zip(old_lines[:30], new_lines[:30])) if a != b]
    tail_changes = [i + 35 for i, (a, b) in enumerate(zip(old_lines[31:], new_lines[34:])) if a != b]
    check(not head_changes and len(tail_changes) == 4
          and all(new_lines[ln - 1].strip().startswith(('"v3_9_bundle"', '"v3_9_plan"', '"v3_9_plan_core"', '"v3_9_config"')) for ln in tail_changes),
          f"H12c outside the DECLARED block, exactly the 4 v3.9 hash value lines differ; zero check code touched (head {head_changes}, tail {tail_changes})")

    # =========================================================================
    # H13. harness change surface: exactly the PER-51-prescribed one line
    # =========================================================================
    fix_line = '    source["semantic_bindings"]["calculation"] = "executed_decimal_rational_v3_9"'
    check(v39_src.count(fix_line.strip()) == 1, "H13a the fix assignment appears exactly once in harness/acceptance_v3_9.py")
    # _config must touch semantic_bindings in exactly two keys (calculation + gate)
    config_fn = v39_src.split("def _config(", 1)[1].split("\ndef ", 1)[0]
    sem_assignments = sorted(line.strip() for line in config_fn.splitlines() if 'source["semantic_bindings"]' in line and "=" in line)
    check(sem_assignments == sorted([fix_line.strip(),
                                     'source["semantic_bindings"]["decimal_output_contract_visibility_gate"] = "oracle_expectations_subset_of_candidate_visible_contract_v3_9"']),
          f"H13b _config touches semantic_bindings in exactly calculation + visibility gate (got {sem_assignments})")

    # =========================================================================
    # H14. 36 run identities: recompute, cross-check declaration, disjointness
    # =========================================================================
    bad = []
    for row in p39["runs"]:
        identity = row["run_identity"]
        if run_id(identity) != row["run_id"]:
            bad.append(f"{row['run_id']}:recompute")
        if identity.get("plan_core_sha256") != NEW["plan_core"] or identity.get("harness_config_sha256") != cfg39_hash:
            bad.append(f"{row['run_id']}:binding")
        if identity.get("benchmark_id") != "financial-agent-reliability-v3.9" or identity.get("repeat") != 1:
            bad.append(f"{row['run_id']}:benchmark")
    check(len(p39["runs"]) == 36 and p39["run_cap"] == 36 and len(tasks39) == 12 and not bad,
          f"H14a 36/36 run_id == clean-room sha256(run_identity)[:32], bound to new plan_core + new config hash (bad: {bad})")
    published = [(row["sequence"], row["model_id"], row["run_id"]) for row in p39["runs"]]
    check(published == DECLARED_RUNS, "H14b plan's 36 (seq, model, run_id) rows == PER-52 published table")
    ids38 = {row["run_id"] for row in p38["runs"]}
    ids39 = {row["run_id"] for row in p39["runs"]}
    check(len(ids39) == 36 and not (ids38 & ids39), "H14c v3.8 ∩ v3.9 run ids == empty set (all 36 identities renewed)")
    check({(r["model_id"], r["seed"]) for r in p38["runs"]} == {(r["model_id"], r["seed"]) for r in p39["runs"]},
          "H14d (model_id, seed) multiset preserved v3.8 -> v3.9")
    per_case = {t["case_id"]: sorted(next(r["model_id"] for r in p39["runs"] if r["run_id"] == rid) for rid in t["run_ids"]) for t in tasks39}
    check(all(m == sorted(MODELS) for m in per_case.values()), "H14e every one of the 12 cases carries exactly the 3 registered models")
    task_ids = {rid for t in tasks39 for rid in t["run_ids"]}
    check(task_ids == ids39, "H14f task.run_ids and plan.runs are the same 36 unique ids")
    check(all(r["run_identity"]["plan_core_sha256"] == NEW["plan_core"] for r in p39["runs"])
          and p39["audit_repair"]["rerun_scope_preregistration"].startswith("all 36 runs"),
          "H14g all identities embed the new plan_core; all-36 rerun scope preregistered")

    # =========================================================================
    # H15. authorization/symmetry structure (technical-gate facts)
    # =========================================================================
    check(p39["authorization"] == {"paid_calls_authorized": False, "execution_state": "offline_validation_only",
                                   "separate_plan_bound_authorization_required": True, "passing_identity_preflight_required": True},
          "H15a plan authorization structure: plan-bound authorization + passing identity preflight required; paid calls not authorized")
    check(b39["paid_calls_authorized"] is False, "H15b bundle paid_calls_authorized=false")
    check(p39["fairness"] == {"same_prompt_tools_budget_retry_grader": True, "models": MODELS},
          "H15c plan.fairness: same prompt/tools/budget/retry/grader across exactly the 3 models")
    model_refs = [line for line in v39_src.splitlines() if any(m in line for m in MODELS)]
    benign = all(("MODELS" in line or "__MODEL_GUARD_" in line or "guarded" in line or "_fixture_trace(" in line or line.strip().startswith("#")) for line in model_refs)
    check(benign, f"H15d no per-model semantic special-casing in harness/acceptance_v3_9.py ({len(model_refs)} model-id references)")
    # grader thresholds live in the disclosure-only projections (hash-verified above)
    # and the hash-locked grader fixture expectations; one live confirmation:
    from harness.acceptance_v3_9 import grade_candidate_v39  # noqa: E402 (hash-locked in H3a manifest)
    fixture03 = rjson(ROOT / "tests/fixtures/acceptance_v3_9/grader.fkw03.decimal_contract.json")
    grade = grade_candidate_v39(fixture03["candidate"], rjson(ROOT / fixture03["projection_path"]),
                                rjson(ROOT / fixture03["snapshot_path"]), fixture03["trace"])
    check(grade["all_applicable_checks_passed"] is True, "H15e v3.9 grader passes the conforming 6dp fixture (live re-grade)")

    failures = [label for ok, label in RESULTS if not ok]
    print(f"\ntotal checks={len(RESULTS)} failures={len(failures)}")
    for label in failures:
        print(f"FAILED: {label}")
    print("INDEPENDENT_VERDICT=" + ("PASS" if not failures else "FAIL"))


if __name__ == "__main__":
    main()
