#!/usr/bin/env python3
"""Fetch and deterministically materialize PER-28 public benchmark seed cases.

Public benchmark artifacts provide task structure only. Facts come from frozen
World Development Indicators API responses; no public benchmark label, program,
or candidate-model output is used as an oracle.
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
from typing import Any, Mapping


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contracts.validate_case_data import content_sha256, file_sha256  # noqa: E402
from cases.public.oracle import evaluate  # noqa: E402


RETRIEVED_AT = "2026-08-11T02:00:00Z"
YEARS = ["2021", "2022", "2023"]
WDI_LICENSE_URL = "https://datacatalog.worldbank.org/search/dataset/0037712/world-development-indicators"
WDI_API_DOC = "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation"
CATALOG_DIR = PROJECT_ROOT / "catalog" / "public"
CASES_DIR = PROJECT_ROOT / "cases" / "public"
SNAPSHOTS_DIR = PROJECT_ROOT / "snapshots" / "public"
RAW_DIR = SNAPSHOTS_DIR / "raw"


BENCHMARKS = {
    "financebench": {
        "name": "FinanceBench structural seed",
        "uri": "https://huggingface.co/datasets/PatronusAI/financebench",
        "revision": "e04404e3a97f69f79c14d42f24981a1c9c3bcd18",
        "license": "CC-BY-NC-4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "redistributable": False,
    },
    "finqa": {
        "name": "FinQA structural seed",
        "uri": "https://github.com/czyssrs/FinQA",
        "revision": "0f16e2867befa6840783e58be38c9efb9229d742",
        "license": "CC-BY-4.0 dataset; MIT code",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistributable": True,
    },
    "tatqa": {
        "name": "TAT-QA structural seed",
        "uri": "https://github.com/NExTplusplus/TAT-QA",
        "revision": "870accc41953dcde885aabeb963d94aabdc0fbc3",
        "license": "CC-BY-4.0 dataset; MIT code",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistributable": True,
    },
    "bizbench": {
        "name": "BizBench structural seed",
        "uri": "https://huggingface.co/datasets/kensho/bizbench",
        "revision": "0a793f2f886156902c72b4a22cab82bb9dceaecf",
        "license": "Apache-2.0 dataset card; no composite row redistributed",
        "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
        "redistributable": True,
    },
}


FAMILIES: list[dict[str, Any]] = [
    {"id": "FKW-01", "benchmark": "financebench", "domain": "research", "risk": "medium", "target": "Gold_candidate", "axis": "as_of_time", "countries": ["USA"], "indicator": "NY.GDP.MKTP.CD", "prompt": "Using only the frozen public-data snapshot available by the cutoff, report the registered year's value.", "inputs": {"operation": "direct", "target_year": "2023"}, "case_patch": {"temporal/as_of": "2026-08-12T02:00:00Z"}, "changed": "/temporal/as_of"},
    {"id": "FKW-02", "benchmark": "financebench", "domain": "research", "risk": "high", "target": "Gold_candidate", "axis": "evidence_completeness", "countries": ["CHN"], "indicator": "NE.EXP.GNFS.CD", "prompt": "Compute the arithmetic mean over exactly the registered evidence years and cite the frozen observations.", "inputs": {"operation": "average", "years": ["2022", "2023"]}, "perturb": {"years": ["2021", "2022", "2023"]}, "changed": "/task/inputs/years"},
    {"id": "FKW-03", "benchmark": "financebench", "domain": "valuation", "risk": "high", "target": "Gold_candidate", "axis": "currency_unit", "countries": ["JPN"], "indicator": "NY.GDP.PCAP.CD", "prompt": "Convert the frozen value using the registered divisor; preserve the source currency and unit basis.", "inputs": {"operation": "scale", "target_year": "2023", "divisor": "1000000"}, "perturb": {"divisor": "1000000000"}, "changed": "/task/inputs/divisor"},
    {"id": "FKW-04", "benchmark": "finqa", "domain": "valuation", "risk": "high", "target": "Gold_candidate", "axis": "accounting_basis", "countries": ["DEU"], "indicator": "NY.GDP.MKTP.CD", "prompt": "Apply the registered calculation basis to the frozen observations and return the deterministic result.", "inputs": {"operation": "basis", "target_year": "2023", "base_year": "2022", "accounting_basis": "reported_value"}, "perturb": {"accounting_basis": "prior_year_index_100"}, "changed": "/task/inputs/accounting_basis"},
    {"id": "FKW-05", "benchmark": "finqa", "domain": "valuation", "risk": "medium", "target": "Gold_candidate", "axis": "fiscal_period", "countries": ["GBR"], "indicator": "FP.CPI.TOTL", "prompt": "Calculate percentage growth across the registered fiscal-period boundary from the frozen observations.", "inputs": {"operation": "growth", "start_year": "2022", "end_year": "2023"}, "perturb": {"start_year": "2021"}, "changed": "/task/inputs/start_year"},
    {"id": "FKW-06", "benchmark": "finqa", "domain": "risk", "risk": "high", "target": "Gold_candidate", "axis": "consolidation_scope", "countries": ["FRA", "DEU"], "indicator": "NY.GDP.MKTP.CD", "prompt": "Aggregate only the countries in the registered consolidation scope for the frozen year.", "inputs": {"operation": "sum_countries", "target_year": "2023", "included_countries": ["DEU", "FRA"]}, "perturb": {"included_countries": ["FRA"]}, "changed": "/task/inputs/included_countries"},
    {"id": "FKW-07", "benchmark": "finqa", "domain": "risk", "risk": "critical", "target": "Gold_candidate", "axis": "method_applicability", "countries": ["CAN"], "indicator": "SL.UEM.TOTL.ZS", "prompt": "Use only the registered method on the frozen series; reject methods outside the preregistered set.", "inputs": {"operation": "method", "method": "latest_value"}, "perturb": {"method": "three_year_average"}, "changed": "/task/inputs/method"},
    {"id": "FKW-08", "benchmark": "tatqa", "domain": "risk", "risk": "high", "target": "Gold_candidate", "axis": "event_regime", "countries": ["AUS"], "indicator": "NE.TRD.GNFS.ZS", "prompt": "Compute the latest change and apply only the registered event-regime multiplier.", "inputs": {"operation": "regime", "event_regime": "stable", "regime_multiplier": "1.0"}, "perturb": {"event_regime": "stress", "regime_multiplier": "1.5"}, "changed": "/task/inputs"},
    {"id": "FKW-09", "benchmark": "tatqa", "domain": "research", "risk": "high", "target": "Gold_candidate", "axis": "source_revision", "countries": ["IND"], "indicator": "NY.GDP.MKTP.CD", "prompt": "Reconcile the requested source revision; abstain if an immutable revision history is not present.", "inputs": {"operation": "direct", "target_year": "2023", "revision_selector": "original", "force_abstain_reason": "REVISION_HISTORY_UNAVAILABLE"}, "perturb": {"revision_selector": "corrected"}, "changed": "/task/inputs/revision_selector", "gold_ready": False, "failure": "The WDI response exposes the current release but not immutable observation-level revision history."},
    {"id": "FKW-10", "benchmark": "tatqa", "domain": "research", "risk": "low", "target": "Gold_candidate", "axis": "language", "countries": ["BRA"], "indicator": "SP.POP.TOTL", "prompt": "Return the frozen value in the registered response language without changing the numeric answer.", "inputs": {"operation": "language_invariant", "target_year": "2023", "language": "en"}, "perturb": {"language": "zh"}, "changed": "/task/inputs/language"},
    {"id": "FKW-11", "benchmark": "tatqa", "domain": "operations", "risk": "medium", "target": "Gold_candidate", "axis": "document_modality", "countries": ["ZAF"], "indicator": "NY.GDP.PCAP.CD", "prompt": "Read the same frozen observation through the registered representation and return the invariant value.", "inputs": {"operation": "modality_invariant", "target_year": "2023", "modality": "table"}, "perturb": {"modality": "text"}, "changed": "/task/inputs/modality"},
    {"id": "FKW-12", "benchmark": "bizbench", "domain": "portfolio", "risk": "high", "target": "Gold_candidate", "axis": "claim_materiality", "countries": ["MEX"], "indicator": "NE.EXP.GNFS.ZS", "prompt": "Compare the frozen portfolio proxy with the registered materiality threshold.", "inputs": {"operation": "threshold", "target_year": "2023", "threshold": "40"}, "perturb": {"threshold": "35"}, "changed": "/task/inputs/threshold"},
    {"id": "FKW-13", "benchmark": "bizbench", "domain": "wealth_compliance", "risk": "high", "target": "Silver_diagnostic_only", "axis": "source_ambiguity", "countries": ["ITA"], "indicator": "NY.GDP.MKTP.CD", "prompt": "Assess the request only if source authority is unambiguous; otherwise abstain.", "inputs": {"operation": "direct", "target_year": "2023", "source_authority": "ambiguous", "force_abstain_reason": "AMBIGUOUS_SOURCE_AUTHORITY"}, "perturb": {"source_authority": "conflicting"}, "changed": "/task/inputs/source_authority"},
    {"id": "FKW-14", "benchmark": "bizbench", "domain": "operations", "risk": "medium", "target": "Silver_diagnostic_only", "axis": "ocr_quality", "countries": ["KOR"], "indicator": "SP.POP.TOTL", "prompt": "Extract a value only when OCR quality supports a unique reading; otherwise abstain.", "inputs": {"operation": "direct", "target_year": "2023", "ocr_confidence": "0.70", "force_abstain_reason": "OCR_AMBIGUITY"}, "perturb": {"ocr_confidence": "0.40"}, "changed": "/task/inputs/ocr_confidence"},
    {"id": "FKW-15", "benchmark": "bizbench", "domain": "wealth_compliance", "risk": "medium", "target": "Silver_diagnostic_only", "axis": "forecast_horizon", "countries": ["IDN"], "indicator": "NY.GDP.PCAP.CD", "prompt": "Do not invent a point forecast when the evidence contains no registered forecasting model.", "inputs": {"operation": "direct", "target_year": "2023", "forecast_horizon_years": 3, "force_abstain_reason": "FORECAST_MODEL_UNAVAILABLE"}, "perturb": {"forecast_horizon_years": 5}, "changed": "/task/inputs/forecast_horizon_years"},
]


def _write_json(path: pathlib.Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _query_url(family: Mapping[str, Any]) -> str:
    countries = ";".join(family["countries"])
    path = f"https://api.worldbank.org/v2/country/{countries}/indicator/{family['indicator']}"
    query = urllib.parse.urlencode({"date": "2021:2023", "format": "json", "per_page": 1000, "source": 2})
    return f"{path}?{query}"


def fetch_raw(*, overwrite: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for family in FAMILIES:
        target = RAW_DIR / f"{family['id']}.json"
        if target.exists() and not overwrite:
            continue
        url = _query_url(family)
        request = urllib.request.Request(url, headers={"User-Agent": "financial-agent-reliability/PER-28 (research snapshot)"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        envelope = {"retrieved_at": RETRIEVED_AT, "request_urls": [url], "responses": [body]}
        _write_json(target, envelope)


def _subject(family: Mapping[str, Any], indicator_name: str) -> dict[str, Any]:
    identifiers = [{"scheme": "WB_COUNTRY", "value": code} for code in family["countries"]]
    identifiers.append({"scheme": "WB_INDICATOR", "value": family["indicator"]})
    return {
        "subject_type": "macro_series",
        "entity_name": f"{'+'.join(family['countries'])} — {indicator_name}",
        "identifiers": identifiers,
        "market": {"mic": "XXXX", "country": "+".join(family["countries"]), "timezone": "UTC"},
        "currency": {"code": "USD"},
        "units": {"amount_scale": "unit", "price_basis": "not_applicable", "accounting_basis": "World Development Indicators; indicator-specific unit is preserved in each record"},
    }


def _snapshot(family: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_path = RAW_DIR / f"{family['id']}.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
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
        records.append({
            "record_id": f"{family['id']}-{row['countryiso3code']}-{row['date']}",
            "evidence_type": "wdi_indicator_observation",
            "source_locator": f"snapshots/public/raw/{family['id']}.json#/responses/0/1/{index}",
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
        })
    snapshot = {
        "contract_type": "data_snapshot",
        "contract_version": "1.0.0",
        "snapshot_id": f"snapshot-public-{family['id'].lower()}-wdi-2021-2023-v1",
        "revision": 1,
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
        "temporal": {"event_time": "2023-12-31T23:59:59Z", "as_of": RETRIEVED_AT, "available_at": RETRIEVED_AT, "retrieved_at": RETRIEVED_AT},
        "records": records,
        "lineage": {
            "collector": "cases/public/build_public_cases.py:fetch_raw",
            "collector_version": "1.0.0",
            "schema_version": "case-data/1.0.0",
            "query_args": {"request_urls": raw["request_urls"]},
            "raw_response_sha256": file_sha256(raw_path),
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
        "name": f"{benchmark['name']} (task structure only; facts re-authored from WDI)",
        "uri": benchmark["uri"],
        "license": {"name": benchmark["license"], "url": benchmark["license_url"], "redistributable": benchmark["redistributable"]},
    }


def _loss_class(domain: str) -> str:
    return {"research": "informational", "valuation": "financial", "risk": "financial", "portfolio": "financial", "wealth_compliance": "regulatory", "operations": "operational"}[domain]


def _case(family: Mapping[str, Any], snapshot: Mapping[str, Any], kind: str, oracle_hash: str) -> dict[str, Any]:
    normal_id = f"case-public-{family['id'].lower()}-normal-v1"
    case_id = f"case-public-{family['id'].lower()}-{kind.replace('_', '-')}-v1"
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
        "revision": 1,
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
        "lineage": {"producer": "cases/public/build_public_cases.py", "generator_version": "1.0.0", "code_revision": file_sha256(pathlib.Path(__file__)), "generated_at": RETRIEVED_AT, "source_case_id": None if kind == "normal" else normal_id, "parent_case_id": None if kind == "normal" else normal_id},
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


def build() -> None:
    oracle_hash = file_sha256(CASES_DIR / "oracle.py")
    reference_hash = file_sha256(CASES_DIR / "oracle_reference.py")
    catalog_families = []
    for family in FAMILIES:
        snapshot, snapshot_meta = _snapshot(family)
        snapshot_path = SNAPSHOTS_DIR / f"data_snapshot.{family['id']}.json"
        _write_json(snapshot_path, snapshot)
        cases = []
        for kind in ("normal", "single_factor_perturbation", "missing_or_anomalous"):
            case = _case(family, snapshot, kind, oracle_hash)
            path = CASES_DIR / f"case_card.{family['id']}.{kind}.json"
            _write_json(path, case)
            cases.append({"case_id": case["case_id"], "kind": kind, "tier": case["quality"]["tier"], "sha256": file_sha256(path)})
        benchmark = BENCHMARKS[family["benchmark"]]
        primary_evidence_key = _sha(["world_development_indicators", family["countries"], family["indicator"], YEARS, RETRIEVED_AT])
        family_key = _sha([primary_evidence_key, family["domain"], family["inputs"]["operation"], family["indicator"], family["axis"]])
        catalog_families.append({
            "family_id": family["id"],
            "track": "financial_knowledge_work",
            "source_id": family["benchmark"],
            "source_revision": benchmark["revision"],
            "source_license": {"name": benchmark["license"], "evidence_url": benchmark["uri"], "verified_at": "2026-08-11", "applicability_limit": "Task structure only; no benchmark row, answer, program, context, or completion is redistributed."},
            "primary_evidence": {"dataset": "World Development Indicators", "dataset_revision": snapshot_meta["metadata"].get("lastupdated", "unknown"), "license": "CC-BY-4.0", "license_evidence_url": WDI_LICENSE_URL, "api_documentation": WDI_API_DOC, "available_at_policy": "Conservative: available_at equals authenticated-free API retrieval time; no earlier availability is asserted.", "snapshot_id": snapshot["snapshot_id"], "snapshot_sha256": snapshot["integrity"]["content_sha256"], "raw_response_sha256": snapshot["lineage"]["raw_response_sha256"]},
            "task": {"domain": family["domain"], "risk": family["risk"], "variant_axis": family["axis"], "changed_pointer": family["changed"], "operator": family["inputs"]["operation"]},
            "quality": {"frozen_target": family["target"], "materialized_gold": family.get("gold_ready", family["target"] == "Gold_candidate"), "promotion_failure": family.get("failure"), "main_ranking_release_gate": "pending_two_person_source/license/time review; automated contract and independent-oracle checks are complete"},
            "prohibitions": {"benchmark_answer_used_as_oracle": False, "candidate_output_used_as_oracle": False, "original_benchmark_row_redistributed": False},
            "deduplication": {"upstream_record_key": _sha([family["benchmark"], benchmark["revision"], f"structure-only:{family['id']}"]), "primary_evidence_key": primary_evidence_key, "cross_source_task_key": _sha([primary_evidence_key, family["prompt"], family["inputs"]["operation"], family["indicator"], family["axis"]]), "family_key": family_key},
            "oracle": {"production_path": "cases/public/oracle.py", "production_sha256": oracle_hash, "independent_path": "cases/public/oracle_reference.py", "independent_sha256": reference_hash},
            "cases": cases,
        })

    catalog = {
        "catalog_type": "public_benchmark_materialized_seed_catalog",
        "version": "1.0.0",
        "status": "frozen_before_candidate_runs",
        "frozen_by_issue": "PER-28",
        "generated_at": RETRIEVED_AT,
        "frozen_contract_refs": {"seed_plan": "catalog/spec.seed-catalog.frozen.v1.json", "case_data": "contracts/case_data_contracts.frozen.v1.json"},
        "selection": {"family_count": 15, "variants_per_family": ["normal", "single_factor_perturbation", "missing_or_anomalous"], "case_count": 45, "frozen_target_gold_candidate_families": 12, "frozen_silver_only_families": 3, "public_benchmark_labels_as_oracle": False, "post_result_selection_or_reweighting": False},
        "release": {"candidate_runs_allowed": False, "blocking_gate": "Two-person source/license/time review is not represented by automated checks and remains required before release.", "crosswalk_protocol": "catalog/public/preregistration_variant_protocol.v2.json"},
        "families": catalog_families,
    }
    catalog_path = CATALOG_DIR / "seed_catalog.v1.json"
    _write_json(catalog_path, catalog)
    _write_manifest()


def _write_manifest() -> None:
    manifest_path = CATALOG_DIR / "frozen_manifest.v1.json"
    paths = [
        CATALOG_DIR / "README.md",
        CATALOG_DIR / "acceptance_report.v1.json",
        CATALOG_DIR / "seed_catalog.v1.json",
        CATALOG_DIR / "preregistration_variant_protocol.v2.json",
        CASES_DIR / "build_public_cases.py",
        CASES_DIR / "oracle.py",
        CASES_DIR / "oracle_reference.py",
        PROJECT_ROOT / "tests" / "test_public_cases.py",
        *sorted(RAW_DIR.glob("FKW-*.json")),
        *sorted(SNAPSHOTS_DIR.glob("data_snapshot.FKW-*.json")),
        *sorted(CASES_DIR.glob("case_card.FKW-*.json")),
    ]
    entries = []
    lines = []
    for path in paths:
        digest = file_sha256(path)
        relative = pathlib.Path(path).relative_to(CATALOG_DIR) if pathlib.Path(path).is_relative_to(CATALOG_DIR) else pathlib.Path(path).relative_to(PROJECT_ROOT)
        manifest_relative = str(relative) if pathlib.Path(path).is_relative_to(CATALOG_DIR) else "../../" + str(relative)
        entries.append({"path": manifest_relative, "sha256": digest})
        lines.append(f"{digest}  {manifest_relative}\n")
    manifest = {"manifest_type": "per_28_public_case_bundle", "version": "1.0.0", "status": "frozen", "files": entries, "contract_bundle_sha256": hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()}
    _write_json(manifest_path, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "build", "fetch-and-build"))
    parser.add_argument("--overwrite", action="store_true", help="replace already frozen raw responses")
    args = parser.parse_args()
    if args.command in ("fetch", "fetch-and-build"):
        fetch_raw(overwrite=args.overwrite)
    if args.command in ("build", "fetch-and-build"):
        build()


if __name__ == "__main__":
    main()
