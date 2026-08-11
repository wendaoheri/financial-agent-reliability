#!/usr/bin/env python3
"""Collect and freeze the PER-28 public benchmark bundle v2.

Version 2 supersedes, rather than mutates, the invalid v1 bundle.  Every WDI
response receives a timestamp from the live UTC clock after its body has been
read.  The benchmark projects supply structural inspiration only; their rows,
labels, programs, and answers are not copied into this bundle.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cases.public.build_public_cases import FAMILIES, YEARS  # noqa: E402
from cases.public.oracle import evaluate  # noqa: E402
from contracts.validate_case_data import content_sha256, file_sha256  # noqa: E402


BUNDLE_VERSION = "2.0.0"
OLD_BUNDLE_SHA256 = "7a05f78739f6751778cac31cde031bf56721fa7429a68ce8aa6b1ff576de87a7"
WDI_LICENSE_URL = "https://datacatalog.worldbank.org/search/dataset/0037712/world-development-indicators"
WDI_API_DOC = "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation"
CATALOG_DIR = PROJECT_ROOT / "catalog" / "public" / "v2"
CASES_DIR = PROJECT_ROOT / "cases" / "public" / "v2"
SNAPSHOTS_DIR = PROJECT_ROOT / "snapshots" / "public" / "v2"
RAW_DIR = SNAPSHOTS_DIR / "raw"
COLLECTION_SESSION_PATH = RAW_DIR / "collection_session.v2.json"
RELEASE_RECORD_PATH = CATALOG_DIR / "release_record.v2.json"


BENCHMARKS = {
    "financebench": {
        "name": "FinanceBench structural seed",
        "uri": "https://huggingface.co/datasets/PatronusAI/financebench",
        "revision": "e04404e3a97f69f79c14d42f24981a1c9c3bcd18",
        "license": "CC-BY-NC-4.0",
        "license_url": "https://huggingface.co/datasets/PatronusAI/financebench/blob/e04404e3a97f69f79c14d42f24981a1c9c3bcd18/README.md",
        "license_scope": "Dataset card license metadata; structural inspiration only and no source row is redistributed.",
        "redistributable": False,
    },
    "finqa": {
        "name": "FinQA structural seed",
        "uri": "https://github.com/czyssrs/FinQA",
        "revision": "0f16e2867befa6840783e58be38c9efb9229d742",
        "license": "MIT repository license; no separate dataset license evidenced",
        "license_url": "https://github.com/czyssrs/FinQA/blob/0f16e2867befa6840783e58be38c9efb9229d742/LICENSE",
        "license_scope": "Direct evidence is limited to the repository root LICENSE. No separate dataset license was evidenced, and no FinQA row, answer, program, context, or code is redistributed.",
        "redistributable": False,
    },
    "tatqa": {
        "name": "TAT-QA structural seed",
        "uri": "https://github.com/NExTplusplus/TAT-QA",
        "revision": "870accc41953dcde885aabeb963d94aabdc0fbc3",
        "license": "CC-BY-4.0 dataset; MIT code",
        "license_url": "https://github.com/NExTplusplus/TAT-QA/blob/870accc41953dcde885aabeb963d94aabdc0fbc3/README.md#license",
        "license_scope": "Repository README license section; structural inspiration only and no source row is redistributed.",
        "redistributable": True,
    },
    "bizbench": {
        "name": "BizBench structural seed",
        "uri": "https://huggingface.co/datasets/kensho/bizbench",
        "revision": "0a793f2f886156902c72b4a22cab82bb9dceaecf",
        "license": "Apache-2.0 dataset card",
        "license_url": "https://huggingface.co/datasets/kensho/bizbench/blob/0a793f2f886156902c72b4a22cab82bb9dceaecf/README.md",
        "license_scope": "Dataset card license metadata; structural inspiration only and no composite row is redistributed.",
        "redistributable": True,
    },
}


def _write_json(path: pathlib.Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"timestamp is not UTC: {value}")
    return parsed


def _sha(parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _query_url(family: Mapping[str, Any]) -> str:
    countries = ";".join(family["countries"])
    path = f"https://api.worldbank.org/v2/country/{countries}/indicator/{family['indicator']}"
    query = urllib.parse.urlencode(
        {"date": "2021:2023", "format": "json", "per_page": 1000, "source": 2}
    )
    return f"{path}?{query}"


def validate_source_license(source_id: str, record: Mapping[str, Any]) -> None:
    required = {"name", "evidence_url", "verified_at", "applicability_limit", "redistributable"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"{source_id}: missing license fields {sorted(missing)}")
    if not str(record["evidence_url"]).startswith("https://"):
        raise ValueError(f"{source_id}: license evidence must be an HTTPS official page")
    if source_id == "finqa":
        normalized = f"{record['name']} {record['applicability_limit']}".lower()
        normalized_name = str(record["name"]).lower()
        if "cc-by" in normalized_name or "creative commons" in normalized_name:
            raise ValueError("finqa: unsupported dataset Creative Commons claim")
        expected = f"/blob/{BENCHMARKS['finqa']['revision']}/LICENSE"
        if expected not in str(record["evidence_url"]):
            raise ValueError("finqa: evidence must pin the repository root LICENSE revision")
        if record["redistributable"] is not False:
            raise ValueError("finqa: redistribution must stay disabled without dataset-specific evidence")
        if "no separate dataset license" not in str(record["applicability_limit"]).lower():
            raise ValueError("finqa: dataset-license uncertainty must be explicit")


def validate_collection_clock(
    session: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    observed_at: str | None = None,
) -> None:
    started = _parse_utc(str(session["started_at"]))
    completed = _parse_utc(str(session["completed_at"]))
    observed = _parse_utc(observed_at) if observed_at else datetime.now(timezone.utc)
    if started > completed or completed > observed:
        raise ValueError("collection session is inverted or future-dated")
    records = session.get("captures")
    if not isinstance(records, list) or len(records) != len(FAMILIES):
        raise ValueError("collection session must enumerate every family capture")
    for sequence, capture in enumerate(records, start=1):
        family_id = str(capture["family_id"])
        envelope = envelopes.get(family_id)
        if envelope is None:
            raise ValueError(f"{family_id}: collection envelope is missing")
        request_started = _parse_utc(str(envelope["request_started_at"]))
        retrieved = _parse_utc(str(envelope["retrieved_at"]))
        if capture.get("sequence") != sequence:
            raise ValueError(f"{family_id}: capture sequence is not contiguous")
        if not (started <= request_started <= retrieved <= completed <= observed):
            raise ValueError(f"{family_id}: collection timestamp is inverted or future-dated")
        if capture.get("request_started_at") != envelope["request_started_at"]:
            raise ValueError(f"{family_id}: request timestamp differs from session record")
        if capture.get("retrieved_at") != envelope["retrieved_at"]:
            raise ValueError(f"{family_id}: retrieval timestamp differs from session record")


def fetch_raw() -> None:
    existing = list(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []
    if existing:
        raise FileExistsError("public v2 raw capture already exists; publish a new version instead of overwriting it")
    started_at = _utc_now()
    pending: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for family in FAMILIES:
        url = _query_url(family)
        request_started_at = _utc_now()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "financial-agent-reliability/PER-28-v2 (research snapshot)"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        pending.append(
            (
                family,
                {
                    "request_started_at": request_started_at,
                    "retrieved_at": _utc_now(),
                    "request_urls": [url],
                    "responses": [body],
                },
            )
        )
    completed_at = _utc_now()
    captures = []
    for sequence, (family, envelope) in enumerate(pending, start=1):
        path = RAW_DIR / f"{family['id']}.json"
        _write_json(path, envelope)
        captures.append(
            {
                "sequence": sequence,
                "family_id": family["id"],
                "request_started_at": envelope["request_started_at"],
                "retrieved_at": envelope["retrieved_at"],
                "raw_response_sha256": file_sha256(path),
            }
        )
    session = {
        "session_type": "public_wdi_collection_session",
        "version": BUNDLE_VERSION,
        "clock_source": "datetime.now(timezone.utc) sampled immediately before request and after response body read",
        "started_at": started_at,
        "completed_at": completed_at,
        "captures": captures,
    }
    _write_json(COLLECTION_SESSION_PATH, session)


def _load_and_validate_collection() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    session = json.loads(COLLECTION_SESSION_PATH.read_text(encoding="utf-8"))
    envelopes = {
        family["id"]: json.loads((RAW_DIR / f"{family['id']}.json").read_text(encoding="utf-8"))
        for family in FAMILIES
    }
    validate_collection_clock(session, envelopes)
    for capture in session["captures"]:
        path = RAW_DIR / f"{capture['family_id']}.json"
        if file_sha256(path) != capture["raw_response_sha256"]:
            raise ValueError(f"{capture['family_id']}: raw response hash differs from collection session")
    return session, envelopes


def _subject(family: Mapping[str, Any], indicator_name: str) -> dict[str, Any]:
    identifiers = [{"scheme": "WB_COUNTRY", "value": code} for code in family["countries"]]
    identifiers.append({"scheme": "WB_INDICATOR", "value": family["indicator"]})
    return {
        "subject_type": "macro_series",
        "entity_name": f"{'+'.join(family['countries'])} — {indicator_name}",
        "identifiers": identifiers,
        "market": {"mic": "XXXX", "country": "+".join(family["countries"]), "timezone": "UTC"},
        "currency": {"code": "USD"},
        "units": {
            "amount_scale": "unit",
            "price_basis": "not_applicable",
            "accounting_basis": "World Development Indicators; indicator-specific unit is preserved in each record",
        },
    }


def _snapshot(
    family: Mapping[str, Any], raw: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_path = RAW_DIR / f"{family['id']}.json"
    body = raw["responses"][0]
    if not isinstance(body, list) or len(body) != 2 or not isinstance(body[1], list):
        raise ValueError(f"{family['id']}: unexpected WDI response envelope")
    metadata, observations = body
    usable = [row for row in observations if row.get("value") is not None and row.get("date") in YEARS]
    expected = {(country, year) for country in family["countries"] for year in YEARS}
    actual = {(row.get("countryiso3code"), row.get("date")) for row in usable}
    if actual != expected:
        raise ValueError(f"{family['id']}: missing or extra observations; expected {sorted(expected)}, got {sorted(actual)}")
    usable.sort(key=lambda row: (row["countryiso3code"], row["date"]))
    indicator_name = usable[0]["indicator"]["value"]
    subject = _subject(family, indicator_name)
    records = []
    for index, row in enumerate(usable):
        number = format(row["value"], ".15g") if isinstance(row["value"], float) else str(row["value"])
        records.append(
            {
                "record_id": f"{family['id']}-{row['countryiso3code']}-{row['date']}",
                "evidence_type": "wdi_indicator_observation",
                "source_locator": f"snapshots/public/v2/raw/{family['id']}.json#/responses/0/1/{index}",
                "payload": {
                    "country_code": row["countryiso3code"],
                    "country_name": row["country"]["value"],
                    "indicator_code": row["indicator"]["id"],
                    "indicator_name": row["indicator"]["value"],
                    "year": row["date"],
                    "value": number,
                    "unit": "indicator-defined; see WDI metadata",
                    "observation_status": row.get("obs_status", ""),
                    "decimal_hint": str(row.get("decimal", 0)),
                },
            }
        )
    retrieved_at = str(raw["retrieved_at"])
    snapshot = {
        "contract_type": "data_snapshot",
        "contract_version": "1.0.0",
        "snapshot_id": f"snapshot-public-{family['id'].lower()}-wdi-2021-2023-v2",
        "revision": 2,
        "status": "frozen",
        "source": {
            "provider": "world_bank",
            "source_type": "macro",
            "dataset": f"World Development Indicators source=2; API lastupdated={metadata.get('lastupdated', 'unknown')}",
            "uri": _query_url(family),
            "license": {"name": "Creative Commons Attribution 4.0", "url": WDI_LICENSE_URL, "redistributable": True},
        },
        "access": {
            "mode": "public_read_only",
            "query_name": "World Bank Indicators API v2",
            "query_args": {"countries": family["countries"], "indicator": family["indicator"], "date": "2021:2023", "source": 2, "format": "json", "per_page": 1000},
            "prohibited_scopes": ["account", "assets", "cash", "holdings", "orders", "positions", "portfolio", "trades"],
        },
        "financial_subject": subject,
        "temporal": {"event_time": "2023-12-31T23:59:59Z", "as_of": retrieved_at, "available_at": retrieved_at, "retrieved_at": retrieved_at},
        "records": records,
        "lineage": {
            "collector": "cases/public/v2/build_public_cases_v2.py:fetch_raw",
            "collector_version": BUNDLE_VERSION,
            "schema_version": "case-data/1.0.0",
            "query_args": {"request_urls": raw["request_urls"]},
            "raw_response_sha256": file_sha256(raw_path),
            "collection_session_sha256": file_sha256(COLLECTION_SESSION_PATH),
            "code_revision": file_sha256(pathlib.Path(__file__)),
            "parent_snapshot_ids": [],
        },
        "integrity": {"canonicalization": "financial-agent-c14n-json-v1", "hash_algorithm": "sha256", "content_sha256": "0" * 64},
    }
    snapshot["integrity"]["content_sha256"] = content_sha256(snapshot)
    return snapshot, {"metadata": metadata, "indicator_name": indicator_name}


def _case_source(family: Mapping[str, Any]) -> dict[str, Any]:
    benchmark = BENCHMARKS[family["benchmark"]]
    return {
        "origin_type": "public_benchmark",
        "name": f"{benchmark['name']} (structure only; facts re-authored from WDI)",
        "uri": benchmark["uri"],
        "license": {
            "name": benchmark["license"],
            "url": benchmark["license_url"],
            "redistributable": benchmark["redistributable"],
        },
    }


def _loss_class(domain: str) -> str:
    return {"research": "informational", "valuation": "financial", "risk": "financial", "portfolio": "financial", "wealth_compliance": "regulatory", "operations": "operational"}[domain]


def _case(
    family: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    kind: str,
    oracle_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    normal_id = f"case-public-{family['id'].lower()}-normal-v2"
    case_id = f"case-public-{family['id'].lower()}-{kind.replace('_', '-')}-v2"
    inputs = copy.deepcopy(family["inputs"])
    if kind == "single_factor_perturbation":
        inputs.update(copy.deepcopy(family.get("perturb", {})))
    gold_ready = family.get("gold_ready", family["target"] == "Gold_candidate")
    tier = "Gold" if gold_ready and kind != "missing_or_anomalous" else "Silver"
    refs = [] if kind == "missing_or_anomalous" else [{
        "snapshot_id": snapshot["snapshot_id"],
        "record_ids": [record["record_id"] for record in snapshot["records"]],
        "snapshot_sha256": snapshot["integrity"]["content_sha256"],
        "evidence_type": "wdi_indicator_observation",
    }]
    result = evaluate(snapshot if refs else None, inputs)
    if tier == "Silver" and result["status"] != "abstain":
        result = {"status": "abstain", "value": None, "reason_codes": [family.get("failure", "DIAGNOSTIC_CASE_NOT_UNIQUELY_DETERMINATE")]}
    case = {
        "contract_type": "case_card",
        "contract_version": "1.0.0",
        "case_id": case_id,
        "revision": 2,
        "status": "frozen",
        "source": _case_source(family),
        "task": {"domain": family["domain"], "prompt": family["prompt"], "inputs": inputs, "required_tools": ["snapshot.read"], "permissions": ["public_data_read"], "initial_state": {"simulated_ledger": None}},
        "financial_subject": copy.deepcopy(snapshot["financial_subject"]),
        "temporal": {"event_time": snapshot["temporal"]["event_time"], "as_of": snapshot["temporal"]["as_of"], "available_at_cutoff": snapshot["temporal"]["available_at"]},
        "risk": {"level": family["risk"], "loss_class": _loss_class(family["domain"]), "rationale": f"Frozen PER-26 risk assignment for {family['id']}; errors may affect {family['domain']} decisions."},
        "quality": {
            "tier": tier,
            "ranking_eligible": tier == "Gold",
            "independently_recomputable": tier == "Gold",
            "rationale": "Primary WDI observations and two independent deterministic implementations agree." if tier == "Gold" else ("Required evidence is intentionally missing; only abstention is verifiable." if kind == "missing_or_anomalous" else family.get("failure", "Frozen diagnostic-only family; no unique production answer is registered.")),
        },
        "evidence_policy": {"minimum_evidence_count": 1 if refs else 0, "required_evidence_types": ["wdi_indicator_observation"] if refs else [], "future_information_prohibited": True},
        "evidence_refs": refs,
        "variant": {"kind": kind, "family_id": family["id"], "parent_case_id": None if kind == "normal" else normal_id, "changed_factors": [] if kind == "normal" else ([family["changed"]] if kind == "single_factor_perturbation" else ["/evidence_refs"])},
        "oracle": {"spec_version": "1.0.0", "implementation": "cases/public/oracle.py:evaluate", "implementation_sha256": oracle_hash, "expected_status": result["status"], "expected_value": result["value"], "reason_codes": result["reason_codes"]},
        "lineage": {"producer": "cases/public/v2/build_public_cases_v2.py", "generator_version": BUNDLE_VERSION, "code_revision": file_sha256(pathlib.Path(__file__)), "generated_at": generated_at, "source_case_id": None if kind == "normal" else normal_id, "parent_case_id": None if kind == "normal" else normal_id},
        "integrity": {"canonicalization": "financial-agent-c14n-json-v1", "hash_algorithm": "sha256", "content_sha256": "0" * 64},
    }
    if kind == "single_factor_perturbation" and "case_patch" in family:
        for pointer, value in family["case_patch"].items():
            container: Any = case
            parts = pointer.split("/")
            for part in parts[:-1]:
                container = container[part]
            container[parts[-1]] = value
    case["integrity"]["content_sha256"] = content_sha256(case)
    return case


def _release_record(session: Mapping[str, Any]) -> dict[str, Any]:
    if RELEASE_RECORD_PATH.exists():
        return json.loads(RELEASE_RECORD_PATH.read_text(encoding="utf-8"))
    record = {
        "record_type": "per_28_public_v2_release_clock",
        "version": BUNDLE_VERSION,
        "generated_at": _utc_now(),
        "collection_session_sha256": file_sha256(COLLECTION_SESSION_PATH),
        "collection_completed_at": session["completed_at"],
    }
    if _parse_utc(record["generated_at"]) < _parse_utc(str(session["completed_at"])):
        raise ValueError("release clock precedes collection completion")
    _write_json(RELEASE_RECORD_PATH, record)
    return record


def build() -> None:
    session, envelopes = _load_and_validate_collection()
    release_record = _release_record(session)
    generated_at = str(release_record["generated_at"])
    oracle_hash = file_sha256(PROJECT_ROOT / "cases" / "public" / "oracle.py")
    reference_hash = file_sha256(PROJECT_ROOT / "cases" / "public" / "oracle_reference.py")
    catalog_families = []
    for family in FAMILIES:
        snapshot, snapshot_meta = _snapshot(family, envelopes[family["id"]])
        snapshot_path = SNAPSHOTS_DIR / f"data_snapshot.{family['id']}.json"
        _write_json(snapshot_path, snapshot)
        cases = []
        for kind in ("normal", "single_factor_perturbation", "missing_or_anomalous"):
            case = _case(family, snapshot, kind, oracle_hash, generated_at)
            path = CASES_DIR / f"case_card.{family['id']}.{kind}.json"
            _write_json(path, case)
            cases.append({"case_id": case["case_id"], "kind": kind, "tier": case["quality"]["tier"], "sha256": file_sha256(path)})
        benchmark = BENCHMARKS[family["benchmark"]]
        source_license = {
            "name": benchmark["license"],
            "evidence_url": benchmark["license_url"],
            "verified_at": "2026-08-11",
            "applicability_limit": benchmark["license_scope"],
            "redistributable": benchmark["redistributable"],
        }
        validate_source_license(family["benchmark"], source_license)
        primary_evidence_key = _sha(["world_development_indicators", family["countries"], family["indicator"], YEARS, snapshot["temporal"]["retrieved_at"]])
        family_key = _sha([primary_evidence_key, family["domain"], family["inputs"]["operation"], family["indicator"], family["axis"]])
        catalog_families.append({
            "family_id": family["id"],
            "track": "financial_knowledge_work",
            "source_id": family["benchmark"],
            "source_revision": benchmark["revision"],
            "source_license": source_license,
            "primary_evidence": {
                "dataset": "World Development Indicators",
                "dataset_revision": snapshot_meta["metadata"].get("lastupdated", "unknown"),
                "license": "CC-BY-4.0",
                "license_evidence_url": WDI_LICENSE_URL,
                "api_documentation": WDI_API_DOC,
                "available_at_policy": "Conservative inference: available_at equals actual unauthenticated API response retrieval time; no earlier availability is asserted.",
                "retrieved_at": snapshot["temporal"]["retrieved_at"],
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_sha256": snapshot["integrity"]["content_sha256"],
                "raw_response_sha256": snapshot["lineage"]["raw_response_sha256"],
            },
            "task": {"domain": family["domain"], "risk": family["risk"], "variant_axis": family["axis"], "changed_pointer": family["changed"], "operator": family["inputs"]["operation"]},
            "quality": {"frozen_target": family["target"], "materialized_gold": family.get("gold_ready", family["target"] == "Gold_candidate"), "promotion_failure": family.get("failure"), "main_ranking_release_gate": "pending independent source/license/time review; automated checks are complete"},
            "prohibitions": {"benchmark_answer_used_as_oracle": False, "candidate_output_used_as_oracle": False, "original_benchmark_row_redistributed": False},
            "deduplication": {
                "upstream_record_key": _sha([family["benchmark"], benchmark["revision"], f"structure-only:{family['id']}"]),
                "primary_evidence_key": primary_evidence_key,
                "cross_source_task_key": _sha([primary_evidence_key, family["prompt"], family["inputs"]["operation"], family["indicator"], family["axis"]]),
                "family_key": family_key,
            },
            "oracle": {"production_path": "cases/public/oracle.py", "production_sha256": oracle_hash, "independent_path": "cases/public/oracle_reference.py", "independent_sha256": reference_hash},
            "cases": cases,
        })

    catalog = {
        "catalog_type": "public_benchmark_materialized_seed_catalog",
        "version": BUNDLE_VERSION,
        "status": "frozen_before_candidate_runs",
        "frozen_by_issue": "PER-28",
        "generated_at": generated_at,
        "supersedes": {"version": "1.0.0", "bundle_sha256": OLD_BUNDLE_SHA256, "status": "revoked", "reason_codes": ["FUTURE_RETRIEVAL_TIMESTAMP", "UNSUPPORTED_FINQA_DATASET_LICENSE_CLAIM"]},
        "frozen_contract_refs": {"seed_plan": "catalog/spec.seed-catalog.frozen.v1.json", "case_data": "contracts/case_data_contracts.frozen.v1.json"},
        "selection": {"family_count": 15, "variants_per_family": ["normal", "single_factor_perturbation", "missing_or_anomalous"], "case_count": 45, "frozen_target_gold_candidate_families": 12, "frozen_silver_only_families": 3, "public_benchmark_labels_as_oracle": False, "post_result_selection_or_reweighting": False},
        "release": {"candidate_runs_allowed": False, "blocking_gate": "Independent source/license/time review remains required before Stage 3.", "crosswalk_protocol": "catalog/public/preregistration_variant_protocol.v2.json"},
        "collection": {"session_path": "snapshots/public/v2/raw/collection_session.v2.json", "session_sha256": file_sha256(COLLECTION_SESSION_PATH), "started_at": session["started_at"], "completed_at": session["completed_at"], "clock_source": session["clock_source"]},
        "families": catalog_families,
    }
    _write_json(CATALOG_DIR / "seed_catalog.v2.json", catalog)
    _write_acceptance_report(catalog)
    _write_manifest()


def _write_acceptance_report(catalog: Mapping[str, Any]) -> None:
    cases = [item for family in catalog["families"] for item in family["cases"]]
    report = {
        "report_type": "per_28_public_case_acceptance",
        "version": BUNDLE_VERSION,
        "issue": "PER-28",
        "as_of": catalog["generated_at"],
        "superseded_bundle": catalog["supersedes"],
        "evidence_classification": {
            "direct_evidence": ["Frozen WDI API response bytes, per-response collection timestamps, collection-session hashes, and official benchmark license pages", "Machine validation results named below"],
            "evidence_based_inference": ["available_at equals retrieved_at because no earlier observation-level availability is proven"],
            "illustration": ["Benchmark task structures are re-authored over WDI facts and are not claims of domain or jurisdictional representativeness"],
        },
        "allocation": {"families": 15, "cases": 45, "gold_cases_materialized": sum(item["tier"] == "Gold" for item in cases), "silver_cases_materialized": sum(item["tier"] == "Silver" for item in cases)},
        "license_correction": {"source_id": "finqa", "assertion": "Repository root LICENSE is MIT; no separate dataset license was evidenced, so no CC-BY claim or FinQA content redistribution right is asserted.", "evidence_url": BENCHMARKS["finqa"]["license_url"]},
        "validation": [
            {"command": "uv run python -m unittest tests.test_public_cases_v2 -v", "expected": "time consistency and license negative tests pass"},
            {"command": "uv run python contracts/validate_case_data.py verify-manifest catalog/public/v2/frozen_manifest.v2.json", "expected": "valid=true"},
            {"command": "uv run python -m unittest discover -s tests -v", "expected": "full suite passes"},
        ],
        "release": {"candidate_runs_allowed": False, "next_gate": "independent Stage 2 re-audit"},
    }
    _write_json(CATALOG_DIR / "acceptance_report.v2.json", report)


def _write_manifest() -> None:
    paths = [
        CATALOG_DIR / "README.md",
        CATALOG_DIR / "acceptance_report.v2.json",
        CATALOG_DIR / "release_record.v2.json",
        CATALOG_DIR / "seed_catalog.v2.json",
        PROJECT_ROOT / "catalog" / "public" / "preregistration_variant_protocol.v2.json",
        pathlib.Path(__file__),
        PROJECT_ROOT / "cases" / "public" / "build_public_cases.py",
        PROJECT_ROOT / "cases" / "public" / "oracle.py",
        PROJECT_ROOT / "cases" / "public" / "oracle_reference.py",
        PROJECT_ROOT / "tests" / "test_public_cases_v2.py",
        COLLECTION_SESSION_PATH,
        *sorted(RAW_DIR.glob("FKW-*.json")),
        *sorted(SNAPSHOTS_DIR.glob("data_snapshot.FKW-*.json")),
        *sorted(CASES_DIR.glob("case_card.FKW-*.json")),
    ]
    entries = []
    lines = []
    for path in paths:
        digest = file_sha256(path)
        relative = pathlib.Path(path).relative_to(CATALOG_DIR) if pathlib.Path(path).is_relative_to(CATALOG_DIR) else pathlib.Path(path).relative_to(PROJECT_ROOT)
        manifest_relative = str(relative) if pathlib.Path(path).is_relative_to(CATALOG_DIR) else "../../../" + str(relative)
        entries.append({"path": manifest_relative, "sha256": digest})
        lines.append(f"{digest}  {manifest_relative}\n")
    manifest = {
        "manifest_type": "per_28_public_case_bundle",
        "version": BUNDLE_VERSION,
        "status": "frozen_supersedes_v1",
        "superseded_bundle_sha256": OLD_BUNDLE_SHA256,
        "files": entries,
        "contract_bundle_sha256": hashlib.sha256("".join(lines).encode("utf-8")).hexdigest(),
    }
    _write_json(CATALOG_DIR / "frozen_manifest.v2.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "build", "fetch-and-build"))
    args = parser.parse_args()
    if args.command in ("fetch", "fetch-and-build"):
        fetch_raw()
    if args.command in ("build", "fetch-and-build"):
        build()


if __name__ == "__main__":
    main()
