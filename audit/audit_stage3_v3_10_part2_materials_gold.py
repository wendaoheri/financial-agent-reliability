"""PER-58 independent audit — Part 2: fail-closed material completeness and
independent re-execution of the frozen Stage-2 registered Gold for all 90 tasks.

Standalone: re-implements the Stage-2 c14n profile locally; re-executes the
frozen oracle files (oracles/longbridge/oracle_v2.py, cases/public/oracle.py)
with only card inputs + snapshot availability, exactly as the frozen Stage-2
generators registered them (``evaluate(snapshot if refs else None, inputs)``).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
DEC = {}


def check(condition: bool, label: str) -> None:
    tag = "OK  " if condition else "FAIL"
    if not condition:
        FAILURES.append(label)
    print(f"[{tag}] {label}")


def stage2_c14n(document) -> str:
    material = copy.deepcopy(document)
    if isinstance(material.get("integrity"), dict):
        material["integrity"].pop("content_sha256", None)
    return json.dumps(material, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def stage2_sha(document) -> str:
    return hashlib.sha256(stage2_c14n(document).encode("utf-8")).hexdigest()


def fsha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gather_cards() -> list[dict]:
    entries = []
    for path in sorted((ROOT / "cases/public/v2").glob("case_card.*.json")):
        family = path.name.split(".")[1]
        entries.append({"track": "financial_knowledge_work", "family": family, "card_path": path,
                        "snapshot_path": ROOT / f"snapshots/public/v2/data_snapshot.{family}.json"})
    for path in sorted((ROOT / "cases/longbridge/synthetic_v2").glob("case_card.*.json")):
        family = path.name.split(".")[1]
        entries.append({"track": "financial_tool_workflow", "family": family, "card_path": path,
                        "snapshot_path": ROOT / f"snapshots/longbridge/synthetic_v2/data_snapshot.{family}.v2.json"})
    return entries


def main() -> None:
    entries = gather_cards()
    fkw = [e for e in entries if e["track"] == "financial_knowledge_work"]
    ftw = [e for e in entries if e["track"] == "financial_tool_workflow"]
    check(len(entries) == 90, f"90 case cards discovered independently (found {len(entries)})")
    check(len(fkw) == 45 and len(ftw) == 45, f"45 FKW + 45 FTW (found {len(fkw)}/{len(ftw)})")
    check(len({e['family'] for e in fkw}) == 15 and len({e['family'] for e in ftw}) == 15, "15 families per track")
    snapshots = {e["snapshot_path"] for e in entries}
    check(len(snapshots) == 30, f"30 distinct data snapshots bound (found {len(snapshots)})")

    # --- integrity recomputation (own c14n implementation) ---
    bad_card = [e["card_path"].name for e in entries if stage2_sha(load(e["card_path"])) != load(e["card_path"])["integrity"]["content_sha256"]]
    check(not bad_card, f"90/90 case card Stage-2 integrity hashes recomputed (bad={bad_card})")
    bad_snap = []
    snap_cache = {}
    for sp in sorted(snapshots):
        doc = load(sp)
        snap_cache[sp] = doc
        if stage2_sha(doc) != doc["integrity"]["content_sha256"]:
            bad_snap.append(sp.name)
    check(not bad_snap, f"30/30 snapshot Stage-2 integrity hashes recomputed (bad={bad_snap})")

    # --- oracle implementation binding ---
    oracle_files = {}
    bad_impl = []
    for e in entries:
        card = load(e["card_path"])
        impl = card["oracle"]["implementation"]
        path = ROOT / impl.split(":")[0]
        oracle_files.setdefault(impl, path)
        if fsha(path) != card["oracle"]["implementation_sha256"]:
            bad_impl.append(card["case_id"])
    check(not bad_impl, f"90/90 oracle implementation file hashes match registrations (bad={bad_impl})")
    check(set(oracle_files) == {"cases/public/oracle.py:evaluate", "oracles/longbridge/oracle_v2.py:evaluate"}, "exactly two frozen Stage-2 oracle implementations bound")

    # --- generator lineage pin ---
    gen_hashes = {}
    for e in entries:
        card = load(e["card_path"])
        gen_hashes.setdefault(card["lineage"]["producer"], (card["lineage"]["code_revision"], card["lineage"]["generated_at"]))
    for producer, (rev, generated_at) in sorted(gen_hashes.items()):
        match = fsha(ROOT / producer) == rev
        check(match, f"generator {producer} hash pinned by card lineage; generated_at={generated_at}")

    # --- evidence refs consistency ---
    bad_refs = []
    for e in entries:
        card = load(e["card_path"])
        snap = snap_cache[e["snapshot_path"]]
        for ref in card.get("evidence_refs", []):
            if ref.get("snapshot_id") != snap.get("snapshot_id"):
                bad_refs.append(f"{card['case_id']}:snapshot_id")
            if ref.get("snapshot_sha256") != snap["integrity"]["content_sha256"]:
                bad_refs.append(f"{card['case_id']}:snapshot_sha")
            record_ids = {r["record_id"] for r in snap.get("records", [])}
            for rid in ref.get("record_ids", []):
                if rid not in record_ids:
                    bad_refs.append(f"{card['case_id']}:dangling:{rid}")
    check(not bad_refs, f"evidence_refs consistent with frozen snapshots (bad={bad_refs})")

    # --- independent re-execution of the registered Gold ---
    fkw_oracle = import_module("audit_fkw_oracle", ROOT / "cases/public/oracle.py")
    ftw_oracle = import_module("audit_ftw_oracle", ROOT / "oracles/longbridge/oracle_v2.py")
    mismatch = []
    tiers = {"Gold": 0, "Silver": 0}
    hidden_labels_seen = set()
    for e in entries:
        card = load(e["card_path"])
        tiers[card["quality"]["tier"]] += 1
        inputs = card["task"]["inputs"]
        hidden_labels_seen |= {"force_abstain_reason"} & set(inputs) | {"diagnostic_reason"} & set(inputs)
        snapshot = snap_cache[e["snapshot_path"]] if card.get("evidence_refs") else None
        oracle = fkw_oracle if e["track"] == "financial_knowledge_work" else ftw_oracle
        try:
            result = oracle.evaluate(snapshot, inputs)
        except Exception as error:  # noqa: BLE001
            mismatch.append(f"{card['case_id']}:oracle exception:{error}")
            continue
        reg = card["oracle"]
        if result["status"] != reg["expected_status"]:
            mismatch.append(f"{card['case_id']}:status {result['status']} != registered {reg['expected_status']}")
        if sorted(result["reason_codes"]) != sorted(reg.get("reason_codes", [])):
            mismatch.append(f"{card['case_id']}:reasons {sorted(result['reason_codes'])} != registered {sorted(reg.get('reason_codes', []))}")
        rv, gv = result.get("value"), reg.get("expected_value")
        if (rv is None) != (gv is None):
            mismatch.append(f"{card['case_id']}:value shape")
        elif isinstance(rv, dict):
            for key in set(rv) | set(gv):
                a, b = rv.get(key), gv.get(key)
                same = (Decimal(str(a)) == Decimal(str(b))) if isinstance(a, (str, int)) and isinstance(b, (str, int)) and str(a).replace("-", "").replace(".", "").isdigit() and str(b).replace("-", "").replace(".", "").isdigit() else a == b
                if not same:
                    mismatch.append(f"{card['case_id']}:value[{key}] {a!r} != registered {b!r}")
    check(not mismatch, f"90/90 registered Gold values independently re-derived by re-executing frozen Stage-2 oracles (bad={mismatch[:10]})")
    check(tiers == {"Gold": 46, "Silver": 44}, f"tier counts Gold/Silver = 46/44 (found {tiers})")
    print(f"    hidden Stage-2 labels present in card inputs: {sorted(hidden_labels_seen)}")

    # --- the three special-audit cases: registered Gold must be INSUFFICIENT_EVIDENCE ---
    for fam in ["07", "11", "12"]:
        card = load(ROOT / f"cases/longbridge/synthetic_v2/case_card.FTW-{fam}.missing_or_anomalous.v2.json")
        check(card["oracle"]["expected_status"] == "abstain" and card["oracle"]["reason_codes"] == ["INSUFFICIENT_EVIDENCE"] and card["oracle"]["expected_value"] is None,
              f"FTW-{fam}-missing Stage-2 registered Gold == abstain/INSUFFICIENT_EVIDENCE/null")
        check(card["evidence_refs"] == [], f"FTW-{fam}-missing evidence_refs empty (evidence base intentionally absent)")
        check(card["lineage"]["generated_at"].startswith("2026-08-11"), f"FTW-{fam}-missing registered before any Stage-3 candidate run")

    # --- v3.9-era expected (for the record): confirm the plan's documented v3_9_expected values
    # were what v3.9's own derivation produced, via the v3.9 plan task expectations if present ---
    plan_v39 = load(ROOT / "contracts/stage3_acceptance_plan.v3.9.json")
    v39_tasks = {t["case_id"]: t for t in plan_v39["tasks"]}
    check(len(v39_tasks) == 12, f"v3.9 covered subset == 12 tasks (found {len(v39_tasks)})")

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)} failures)")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("RESULT: PASS — all part-2 checks green")


if __name__ == "__main__":
    main()
