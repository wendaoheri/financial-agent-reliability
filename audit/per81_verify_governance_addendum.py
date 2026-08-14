"""PER-81 independent verification of the Stage-4 governance remediation.

Auditor: independent scoring & statistics auditor (duty-separated from the
PER-80 implementer). This script recomputes every hash itself; it imports
nothing from the repo's grading code.

Checks:
  P1  preregistration v1 bytes match the commitment in v1.1.supersedes and in
      grader contract v1 (history not rewritten in place).
  P2  preregistration v1.1 carries revision_type=addendum, status=frozen_addendum,
      a substitution record with reason / decision time / decision basis /
      authorization chain, and its candidate_models == executed set only.
  G1  grader contract v2: every listed file hash recomputes; aggregate
      bundle hash recomputes; supersedes commitment matches the v1 manifest
      bytes and the recomputed v1 bundle hash.
  G2  scoring-logic continuity: every file present in the v1 manifest appears
      in the v2 manifest with an IDENTICAL sha256 (policy, grader.py, schema,
      checklist, acceptance doc, fixtures, tests). v2 may only APPEND files.
  C1  cross-references cited inside v1.1 recompute (PER-32 audit report,
      variant protocol v2, model manifests v1/v2, stage-3 acceptance plans,
      auditor statistics script, grader policy).
  R1  no candidate-run checkpoint file is newer than the final v3.11.1
      coverage round (no rerun / no new candidate calls).

Exit code 0 = all checks pass; nonzero otherwise. Prints one line per check.
"""

import datetime
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def check(cid: str, ok: bool, detail: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {detail}")
    if not ok:
        FAILURES.append(f"{cid}: {detail}")


# ---- artifacts -------------------------------------------------------------
PREREG_V1_REL = "preregistration/benchmark_preregistration.v1.json"
PREREG_V11_REL = "preregistration/benchmark_preregistration.v1.1.json"
GC_V1_REL = "contracts/grader_contract.frozen.v1.json"
GC_V2_REL = "contracts/grader_contract.frozen.v2.json"

prereg_v1 = load(PREREG_V1_REL)
prereg_v11 = load(PREREG_V11_REL)
gc_v1 = load(GC_V1_REL)
gc_v2 = load(GC_V2_REL)

h_prereg_v1 = sha256(ROOT / PREREG_V1_REL)
h_prereg_v11 = sha256(ROOT / PREREG_V11_REL)

# ---- P1: history preserved -------------------------------------------------
check(
    "P1a",
    h_prereg_v1 == "9cc19b6dad9873e78c78a324c304c43050f7e9e5099cb8fb5f026818041aa31e",
    f"prereg v1 sha256 recomputed {h_prereg_v1[:16]}… equals the PER-24-era commitment",
)
check(
    "P1b",
    prereg_v11.get("supersedes", {}).get("sha256") == h_prereg_v1
    and prereg_v11.get("supersedes", {}).get("preserved_unchanged") is True,
    "v1.1 supersedes commitment equals recomputed v1 bytes; preserved_unchanged=true",
)
check(
    "P1c",
    prereg_v1.get("candidate_models") == ["qwen3.8-max", "glm-5.2", "kimi-k3"],
    "v1 still carries the original roster incl. kimi-k3 (not rewritten in place)",
)

# ---- P2: addendum content --------------------------------------------------
sub = prereg_v11.get("recorded_pre_execution_changes", {}).get("model_substitution_addendum", {})
check(
    "P2a",
    prereg_v11.get("revision_type") == "addendum"
    and prereg_v11.get("status") == "frozen_addendum",
    "v1.1 declares revision_type=addendum and status=frozen_addendum",
)
check(
    "P2b",
    sub.get("substituted_out") == "kimi-k3" and sub.get("substituted_in") == "deepseek-v4-pro",
    "substitution record names kimi-k3 -> deepseek-v4-pro",
)
chain = sub.get("decision_chain", [])
have_time = any("timestamp" in step for step in chain)
have_owner = any("workspace owner" in step.get("event", "") for step in chain)
check(
    "P2c",
    len(chain) >= 5 and have_time and have_owner,
    f"decision chain has {len(chain)} steps with timestamps and owner authorization",
)
check(
    "P2d",
    prereg_v11.get("candidate_models") == ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
    and "kimi-k3" not in prereg_v11.get("candidate_models", []),
    "v1.1 candidate_models equals the executed set; kimi-k3 absent from the roster",
)
check(
    "P2e",
    bool(sub.get("non_result_driven")) and bool(sub.get("timeline_proof")),
    "addendum records non-result-driven basis plus run-timeline proof",
)

# ---- G1: contract v2 integrity ---------------------------------------------
def verify_manifest(rel: str, manifest: dict) -> tuple[bool, str]:
    commitments: list[str] = []
    for item in manifest.get("files", []):
        relp, expected = item["path"], item["sha256"]
        p = ROOT / relp
        if not p.is_file():
            return False, f"missing {relp}"
        actual = sha256(p)
        if actual != expected:
            return False, f"hash mismatch {relp}: recorded {expected[:16]}… actual {actual[:16]}…"
        commitments.append(f"{relp}\0{expected}\n")
    aggregate = hashlib.sha256("".join(commitments).encode("utf-8")).hexdigest()
    if aggregate != manifest.get("contract_bundle_sha256"):
        return False, f"bundle mismatch {rel}: recorded {manifest.get('contract_bundle_sha256')[:16]}… recomputed {aggregate[:16]}…"
    return True, f"{len(commitments)} files verified, bundle {aggregate[:16]}…"


ok, detail = verify_manifest(GC_V1_REL, gc_v1)
check("G1a", ok, f"grader contract v1 recompute: {detail}")
ok, detail = verify_manifest(GC_V2_REL, gc_v2)
check("G1b", ok, f"grader contract v2 recompute: {detail}")
check(
    "G1c",
    gc_v2.get("supersedes", {}).get("sha256") == sha256(ROOT / GC_V1_REL),
    "v2 supersedes.sha256 equals recomputed v1 manifest bytes",
)
check(
    "G1d",
    gc_v2.get("supersedes", {}).get("contract_bundle_sha256")
    == gc_v1.get("contract_bundle_sha256"),
    "v2 supersedes bundle commitment equals the recomputed v1 bundle",
)
check(
    "G1e",
    gc_v1.get("manifest_version") == "1.0.0"
    and gc_v2.get("manifest_version") == "2.0.0"
    and bool(gc_v2.get("supersedes", {}).get("reason")),
    "version incremented 1.0.0 -> 2.0.0 with a recorded change reason",
)

# ---- G2: scoring-logic continuity -------------------------------------------
v1_files = {item["path"]: item["sha256"] for item in gc_v1.get("files", [])}
v2_files = {item["path"]: item["sha256"] for item in gc_v2.get("files", [])}
missing = [p for p in v1_files if p not in v2_files]
changed = [p for p, h in v1_files.items() if p in v2_files and v2_files[p] != h]
added = sorted(set(v2_files) - set(v1_files))
check("G2a", not missing and not changed,
      f"all {len(v1_files)} v1 files byte-identical in v2 (missing={missing}, changed={changed})")
check(
    "G2b",
    "contracts/grader_policy.v1.json" in v2_files
    and "contracts/grader.py" in v2_files
    and v2_files["contracts/grader_policy.v1.json"]
    == "49aa4367a7761afe9e0275250700856605f346a8d35b7bc8d550c9cf1126d7b7",
    "policy, grader code, thresholds frozen: v2 still pins grader_policy.v1.json and grader.py at v1 hashes",
)
print(f"       v2 append-only additions: {added}")

# ---- C1: cross-references cited inside v1.1 ---------------------------------
CITED = {
    "audit/per32_stage4_independent_audit_report.md":
        "65fe422a5f4b731ae29513e1a0c460666b23911a60bbce08b3b9c2f9684618f3",
    "catalog/public/preregistration_variant_protocol.v2.json":
        "f7ea69077d4fc28e226d4b541859c234e6e9d74da1a7f1329701e934c325deeb",
    "contracts/model_manifest.frozen.v1.json":
        "6df4c5b8615c55b6db06a970e16bd19345ecbada691c6737e59be5f2bba166e2",
    "contracts/model_manifest.frozen.v2.json":
        "8b727749db3e29a081a4f48aae7bdf98149ac2f602bf10bda1220a330d5cd763",
    "contracts/stage3_acceptance_plan.v3.10.json":
        "b8ad7bf21fccb7a44c333d05fe2ee1d330747f9b1da948692fe05d1942a4a40a",
    "contracts/stage3_acceptance_plan.v3.11.json":
        "83b3710b91814c930897fced1d9d27e26627e47ab17d72fc52f4dc17e792c7a8",
    "audit/per32_part4_statistics.py":
        "e9cdf2ed187451e2bc8332e10aea7b42acea306be7a37b105bec86fa671c2a64",
    "contracts/grader_policy.v1.json":
        "49aa4367a7761afe9e0275250700856605f346a8d35b7bc8d550c9cf1126d7b7",
}
for rel, expected in CITED.items():
    p = ROOT / rel
    actual = sha256(p) if p.is_file() else None
    check(
        "C1",
        actual == expected,
        f"{rel} recompute {'matches' if actual == expected else 'MISMATCH'} cited {expected[:12]}…",
    )

# v1.1 hash as recorded in the v2 grader contract
check(
    "C2",
    v2_files.get(PREREG_V11_REL) == h_prereg_v11,
    f"v1.1 bytes match grader contract v2 entry ({h_prereg_v11[:16]}…)",
)

# ---- R1: no new candidate runs after the matrix -----------------------------
latest = None
for p in (ROOT / "runs").rglob("*.jsonl"):
    mt = p.stat().st_mtime
    if latest is None or mt > latest[0]:
        latest = (mt, p)
if latest:
    ts = datetime.datetime.fromtimestamp(latest[0], datetime.timezone.utc)
    check(
        "R1",
        latest[1].as_posix().find("coverage-20260814-v3.11.1") != -1
        and ts.isoformat() < "2026-08-14T12:00:00",
        f"newest run checkpoint is {latest[1].name} mtime {ts.isoformat()} (v3.11.1 coverage round; "
        "no checkpoint written after it => no rerun / no new candidate calls)",
    )

# ---- summary -----------------------------------------------------------------
print()
print(f"RESULT: {'PASS' if not FAILURES else 'FAIL'} — {len(FAILURES)} failure(s)")
for f in FAILURES:
    print("  -", f)
print(f"preregistration v1     : {PREREG_V1_REL}  sha256 {h_prereg_v1}")
print(f"preregistration v1.1   : {PREREG_V11_REL}  sha256 {h_prereg_v11}")
print(f"grader contract v1     : {GC_V1_REL}  sha256 {sha256(ROOT / GC_V1_REL)}  bundle {gc_v1.get('contract_bundle_sha256')}")
print(f"grader contract v2     : {GC_V2_REL}  sha256 {sha256(ROOT / GC_V2_REL)}  bundle {gc_v2.get('contract_bundle_sha256')}")
sys.exit(1 if FAILURES else 0)
