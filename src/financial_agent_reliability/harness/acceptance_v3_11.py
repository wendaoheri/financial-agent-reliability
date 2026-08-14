"""Superseding v3.11 contracts and continuation plan for the PER-61 token-budget
consistency repair.

PER-61 fixes exactly one systemic contract/runtime defect discovered by the
PER-59 v3.10 first-270 execution and freezes a superseding v3.11 bundle plus a
preregistered 550-run continuation plan:

Defect (10/10 invalidated units, root cause identical). ``run_trace.schema.v3.10``
pinned the cumulative ``usage.total_tokens`` ceiling at 32768 (= the single-request
context window), while the frozen execution loop enforces only the *request-count*
budget (8) and the per-request wall clock — never a cumulative token budget. A
legitimately executed multi-request session accumulates per-request input+output
(context is resent and grows each turn), so an 8-request long-context run summed to
35,484–39,795 tokens and produced an unfreezable trace.

Repair direction (documented, option (a)): the schema cumulative cap is changed to
reflect the true session-cumulative semantics. The new cap is derived from the
budget design — ``max_model_requests x single_request_context_window`` =
8 x 32768 = 262144 — and is NOT back-derived from the observed 35k–40k candidate
usage. The runtime request-budget enforcement is unchanged; the schema ceiling is
now consistent with the maximum cumulative usage the enforced request budget can
produce. The repair is three-model symmetric (model-agnostic config + schema) and
contract-visible (derivation recorded in the frozen config).

Scope discipline honored here:
- No change to prompts, oracle expectations, scoring thresholds, reason semantics,
  or case materials. The v3.11 projections are content-identical to v3.10 except
  the version tag and the supersedes rationale; the clean-room oracle, grader
  checks, and reason vocabulary are reused verbatim from v3.10.
- v3.5–v3.10 frozen artifacts stay byte-exact; retroactive regrading is false.
- The 260 frozen v3.10 units remain valid and comparable under v3.11 (only the
  cumulative total_tokens ceiling moves; every graded check is unchanged).
- v3.10 invalidation forensics (invalidated-runs.json, grading-failures/) are
  preserved permanently; the 10 coverage runs never silently replace them.
- No paid calls, no candidate/model requests, no secret reads: offline contract
  construction and validation only.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from contracts.run_trace_validator_v3_7 import canonical, scan_persisted_value_for_secrets
from contracts.run_trace_validator_v3_8 import build_run_id, content_sha256, file_sha256
from contracts.run_trace_validator_v3_11 import validate_run_trace_v311
from financial_agent_reliability.harness.acceptance_v3_7 import tool_schemas_v37
from financial_agent_reliability.harness.acceptance_v3_10 import (
    ALL_CHECKS,
    CALCULATION_IMPLEMENTATION,
    LEDGER_IMPLEMENTATION,
    MODELS,
    VARIANT_IDS,
    build_projection_v310,
    case_card_index,
    derive_seed as _derive_seed_v310,
    expected_calculation_v310,
    gold_cross_check_errors,
    grade_candidate_v310,
    independent_expected_v310,
    material_completeness_errors,
    oracle_visibility_report_v310,
    projection_case_id,
    read_json,
    reason_definitions_v310,
    run_gate_negative_scenarios_v310,
    write_json,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]
V310_BUNDLE = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.10.json"
V310_PLAN = ROOT / "contracts/stage3_acceptance_plan.v3.10.json"
V310_CONFIG = ROOT / "contracts/run_trace_harness_config.v3.10.json"
CONFIG_PATH = ROOT / "contracts/run_trace_harness_config.v3.11.json"
PLAN_PATH = ROOT / "contracts/stage3_acceptance_plan.v3.11.json"
BUNDLE_PATH = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"
TRACE_SCHEMA_PATH = ROOT / "contracts/run_trace.schema.v3.11.json"
GRADER_SCHEMA_PATH = ROOT / "contracts/stage3_independent_grader_result.schema.v3.11.json"
REASON_PATH = ROOT / "contracts/reason_codes.v3.11.json"
WIRE_PATH = ROOT / "contracts/candidate_submission_wire_contract.v3.11.json"
OUTPUT_PATH = ROOT / "contracts/candidate_output_contracts.v3.11.json"
PROJECTION_DIR = ROOT / "cases/candidate_v3_11"
FIXTURE_DIR = ROOT / "tests/fixtures/acceptance_v3_11"
V310_PROJECTION_DIR = ROOT / "cases/candidate_v3_10"
V310_INVALIDATED_RUNS = ROOT / "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json"

BENCHMARK_ID = "financial-agent-reliability-v3.11"
CONTRACT_VERSION = "3.11.0"
MASTER_SEED = 20260813
PRIOR_BUNDLE_SHA256 = {
    "3.5": "d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8",
    "3.6": "afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959",
    "3.7": "354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44",
    "3.8": "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609",
    "3.9": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "3.10": "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180",
}

# --- Token-budget consistency repair (option (a): cumulative schema cap) ------
# The cumulative session total_tokens ceiling is derived from the budget design:
#   max_model_requests x single_request_context_window = 8 x 32768 = 262144.
# It is NOT back-derived from the observed 35,484–39,795 candidate usage in the
# v3.10 round. The per-request context window (32768) is the value the frozen
# transport declares for every candidate model; the runtime enforces the
# request-count budget (8) and the per-request wall clock, so 262144 bounds the
# cumulative usage the enforced budget can produce.
SINGLE_REQUEST_CONTEXT_WINDOW = 32768
MAX_MODEL_REQUESTS = 8
CUMULATIVE_MAX_TOTAL_TOKENS = MAX_MODEL_REQUESTS * SINGLE_REQUEST_CONTEXT_WINDOW
TOKEN_BUDGET_DERIVATION = {
    "formula": "max_model_requests x single_request_context_window",
    "max_model_requests": MAX_MODEL_REQUESTS,
    "single_request_context_window": SINGLE_REQUEST_CONTEXT_WINDOW,
    "result": CUMULATIVE_MAX_TOTAL_TOKENS,
    "semantics": (
        "usage.total_tokens is cumulative over the session: the sum of per-request "
        "input_tokens + output_tokens across all logical requests. Each request's "
        "input+output is bounded by the single-request context window; the runtime "
        "enforces the request-count budget (max_model_requests). The ceiling is the "
        "budget-design product, not a value fitted to observed candidate usage."
    ),
    "back_derived_from_observed_usage": False,
}

# --- v3.10 invalidation forensics (preserved, never replaced) -----------------
V310_INVALIDATED_RUNS_FILE_SHA256 = "e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1"
V310_INVALIDATED_REPORT_SHA256 = "657761b18592af645c2ed13dd1d2f6301c9b41dd06f14b768c191eeef9aad6ba"

# The 10 invalidated (case, model) repeat-1 units to cover, ordered by their v3.10
# execution sequence so the coverage mapping is explicit and auditable.
COVERAGE_UNITS: list[dict[str, Any]] = [
    {"v3_10_sequence": 146, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-02-missing-or-anomalous-v3", "v3_10_run_id": "run_bba344e218f6643126192d6f818f37e2"},
    {"v3_10_sequence": 155, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-03-missing-or-anomalous-v3", "v3_10_run_id": "run_68352ead71639135bb3e5e5e37974dab"},
    {"v3_10_sequence": 164, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-04-missing-or-anomalous-v3", "v3_10_run_id": "run_0a93a3127f34e0cd080080353bdb149e"},
    {"v3_10_sequence": 174, "model_id": "deepseek-v4-pro", "case_id": "case-synthetic-ftw-05-missing-or-anomalous-v3", "v3_10_run_id": "run_e50d4565effc44efa37772bd8c92a2e2"},
    {"v3_10_sequence": 182, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-06-missing-or-anomalous-v3", "v3_10_run_id": "run_026ce7b195076f7aa0d84502403d61c3"},
    {"v3_10_sequence": 191, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-07-missing-or-anomalous-v3", "v3_10_run_id": "run_e41b53663632b0e724f3dcc95d54df94"},
    {"v3_10_sequence": 200, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-08-missing-or-anomalous-v3", "v3_10_run_id": "run_5cb172c4d3621b3cc692598a10460802"},
    {"v3_10_sequence": 218, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-10-missing-or-anomalous-v3", "v3_10_run_id": "run_c5c0ae24d74c577df57b9007b4b7fe74"},
    {"v3_10_sequence": 221, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-10-normal-v3", "v3_10_run_id": "run_a69bf0a682dc5be57f3976aa064a9da3"},
    {"v3_10_sequence": 236, "model_id": "glm-5.2", "case_id": "case-synthetic-ftw-12-missing-or-anomalous-v3", "v3_10_run_id": "run_42e247098cf15f5ad7d6568610466879"},
]
COVERAGE_RUN_COUNT = len(COVERAGE_UNITS)  # 10
EXTENSION_REPEATS = [2, 3]
CONTINUATION_RUN_CAP = COVERAGE_RUN_COUNT + 90 * len(MODELS) * len(EXTENSION_REPEATS)  # 10 + 540 = 550


def derive_seed(case_id: str, model_id: str, repeat: int) -> int:
    identity = {"benchmark_id": BENCHMARK_ID, "case_id": case_id, "master_seed": MASTER_SEED, "repeat": repeat, "requested_model_id": model_id}
    return int(content_sha256(identity)[:16], 16) % 2**32


# ---------------------------------------------------------------------------
# Projections: content-identical to v3.10 except the version tag + rationale.
# ---------------------------------------------------------------------------


def build_projection_v311(card: Mapping[str, Any], *, source_case_path: str) -> dict[str, Any]:
    projection = build_projection_v310(card, source_case_path=source_case_path)
    projection["contract_version"] = CONTRACT_VERSION
    projection["supersedes"] = {
        **projection["supersedes"],
        "supersedes_projection_path": f"cases/candidate_v3_10/{projection['case_id']}.json",
        "rationale": (
            "PER-61 token-budget consistency repair: candidate-visible content is "
            "byte-identical to the v3.10 projection; only the contract version tag "
            "and this supersedes rationale change. Prompts, oracle expectations, "
            "scoring thresholds, reason semantics, and case materials are unchanged."
        ),
    }
    return projection


# ---------------------------------------------------------------------------
# Contract builders.
# ---------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    source = copy.deepcopy(read_json(V310_CONFIG))
    source["contract_version"] = CONTRACT_VERSION
    source["supersedes"] = {"path": "contracts/run_trace_harness_config.v3.10.json", "sha256": file_sha256(V310_CONFIG)}
    budget = source["resource_budget"]
    budget["single_request_context_window"] = SINGLE_REQUEST_CONTEXT_WINDOW
    budget["max_total_tokens"] = CUMULATIVE_MAX_TOTAL_TOKENS
    budget["max_total_tokens_derivation"] = TOKEN_BUDGET_DERIVATION
    source["token_budget_repair"] = {
        "issue": "PER-61",
        "direction": "option_a_cumulative_schema_cap",
        "defect": (
            "run_trace.schema.v3.10 pinned cumulative usage.total_tokens at the "
            "single-request context window (32768) while the frozen execution loop "
            "enforced only the request-count budget, so legitimately executed "
            "multi-request runs produced unfreezable traces"
        ),
        "repair": (
            "the cumulative total_tokens ceiling now reflects session-cumulative "
            "semantics and equals max_model_requests x single_request_context_window; "
            "request-budget enforcement and all graded semantics are unchanged"
        ),
        "schema_maximum": CUMULATIVE_MAX_TOTAL_TOKENS,
        "derivation": TOKEN_BUDGET_DERIVATION,
        "three_model_symmetric": True,
        "prompt_oracle_threshold_reason_case_material_unchanged": True,
    }
    source["semantic_bindings"]["calculation"] = "executed_decimal_rational_v3_10"
    source["semantic_bindings"]["decimal_output_contract_visibility_gate"] = "oracle_expectations_subset_of_candidate_visible_contract_v3_10"
    source["execution"]["planned_run_cap"] = CONTINUATION_RUN_CAP
    source["execution"]["paid_calls_authorized"] = False
    source["execution"]["offline_validation_only"] = True
    source["contract_extension"] = {
        "issue": "PER-61",
        "scope": "token-budget consistency repair + 550-run continuation (10 repeat-1 coverage + repeat 2-3 extension)",
        "new_reason_codes": [],
        "oracle_behavior_changed_for_previously_covered_cases": [],
        "candidate_answers_back_derived": False,
    }
    return source


def _trace_schema() -> dict[str, Any]:
    guarded = {f"__MODEL_GUARD_{index}__": model for index, model in enumerate(MODELS)}
    text = json.dumps(read_json(ROOT / "contracts/run_trace.schema.v3.10.json"))
    for placeholder, model in guarded.items():
        text = text.replace(model, placeholder)
    text = text.replace("3.10", "3.11")
    for placeholder, model in guarded.items():
        text = text.replace(placeholder, model)
    schema = json.loads(text)
    schema["properties"]["usage"]["properties"]["total_tokens"]["maximum"] = CUMULATIVE_MAX_TOTAL_TOKENS
    # The v3.10 schema pinned repeat=1 because only the first round executed.
    # The v3.11 continuation spans repeats 1-3 (10 coverage + repeat 2-3
    # extension), so the identity schema must accept every registered repeat.
    schema["properties"]["run_identity"]["properties"]["repeat"] = {"enum": [1, 2, 3]}
    return schema


def _grader_schema() -> dict[str, Any]:
    guarded = {f"__MODEL_GUARD_{index}__": model for index, model in enumerate(MODELS)}
    text = json.dumps(read_json(ROOT / "contracts/stage3_independent_grader_result.schema.v3.10.json"))
    for placeholder, model in guarded.items():
        text = text.replace(model, placeholder)
    text = text.replace("3.10", "3.11")
    for placeholder, model in guarded.items():
        text = text.replace(placeholder, model)
    return json.loads(text)


def _reason_doc() -> dict[str, Any]:
    v310 = read_json(ROOT / "contracts/reason_codes.v3.10.json")
    definitions = reason_definitions_v310()
    case_sets: dict[str, dict[str, Any]] = {}
    for entry in case_card_index():
        card = entry["card"]
        projection = build_projection_v311(card, source_case_path=entry["card_path"].relative_to(ROOT).as_posix())
        from financial_agent_reliability.harness.acceptance_v3_10 import derive_reason_codes_v310
        derived = derive_reason_codes_v310(projection)
        status = independent_expected_v310(projection, read_json(entry["snapshot_path"]))["status"]
        case_sets[projection["case_id"]] = {"status": status, "required": derived, "allowed": derived}
    return {
        "contract_type": "reason_code_contract",
        "contract_version": CONTRACT_VERSION,
        "status": "frozen",
        "supersedes": {"path": "contracts/reason_codes.v3.10.json", "sha256": file_sha256(ROOT / "contracts/reason_codes.v3.10.json")},
        "definitions": definitions,
        "generic_specificity_rule": v310["generic_specificity_rule"],
        "mutual_exclusion_rule": v310["mutual_exclusion_rule"],
        "status_rule": v310["status_rule"],
        "exact_set_algorithm": v310["exact_set_algorithm"],
        "case_sets": case_sets,
        "implementation_coverage": {
            "trigger_count": len(definitions),
            "positive_negative_fixture_per_code": True,
            "suppression_and_status_fixtures": True,
        },
    }


def _output_contract() -> dict[str, Any]:
    source = copy.deepcopy(read_json(ROOT / "contracts/candidate_output_contracts.v3.10.json"))
    source["contract_version"] = CONTRACT_VERSION
    source["supersedes"] = {"path": "contracts/candidate_output_contracts.v3.10.json", "sha256": file_sha256(ROOT / "contracts/candidate_output_contracts.v3.10.json")}
    return source


def _wire() -> dict[str, Any]:
    source = copy.deepcopy(read_json(ROOT / "contracts/candidate_submission_wire_contract.v3.10.json"))
    source["contract_version"] = CONTRACT_VERSION
    source["supersedes"] = {"path": "contracts/candidate_submission_wire_contract.v3.10.json", "sha256": file_sha256(ROOT / "contracts/candidate_submission_wire_contract.v3.10.json")}
    return source


# ---------------------------------------------------------------------------
# Independent grader v3.11: reuses the v3.10 grader verbatim and re-tags the
# result contract version, so every graded check is byte-identical to v3.10.
# ---------------------------------------------------------------------------


def grade_candidate_v311(candidate: Mapping[str, Any] | None, projection: Mapping[str, Any], snapshot: Mapping[str, Any], trace: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(grade_candidate_v310(candidate, projection, snapshot, trace))
    result.pop("grader_sha256", None)
    result["contract_version"] = CONTRACT_VERSION
    result["grader_sha256"] = content_sha256(result)
    if GRADER_SCHEMA_PATH.is_file():
        errors = list(Draft202012Validator(read_json(GRADER_SCHEMA_PATH)).iter_errors(result))
        if errors:
            raise ValueError(f"grader schema invalid:{errors[0].message}")
    return result


# ---------------------------------------------------------------------------
# Continuation plan: 10 repeat-1 coverage runs + 90x3 repeat 2-3 = 550 new
# run identities. Seeds continue the frozen derivation with the v3.11 benchmark
# id and master seed; every identity is order-independent and disjoint from all
# v3.5-v3.10 run ids.
# ---------------------------------------------------------------------------


def _task_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in case_card_index():
        card = entry["card"]
        case_id = projection_case_id(card)
        projection_path = PROJECTION_DIR / f"{case_id}.json"
        projection = read_json(projection_path)
        rows.append({
            "case_id": case_id,
            "source_case_path": entry["card_path"].relative_to(ROOT).as_posix(),
            "source_case_sha256": file_sha256(entry["card_path"]),
            "projection_path": projection_path.relative_to(ROOT).as_posix(),
            "projection_sha256": file_sha256(projection_path),
            "snapshot_path": entry["snapshot_path"].relative_to(ROOT).as_posix(),
            "snapshot_sha256": file_sha256(entry["snapshot_path"]),
            "family_id": entry["family_id"],
            "variant_id": VARIANT_IDS[entry["variant"]],
            "tier": card["quality"]["tier"],
            "track": entry["track"],
            "tool_schema_sha256": content_sha256(tool_schemas_v37(projection)),
            "run_ids": [],
        })
    return sorted(rows, key=lambda item: item["case_id"])


def _coverage_lookup() -> dict[tuple[str, str], dict[str, Any]]:
    return {(unit["case_id"], unit["model_id"]): unit for unit in COVERAGE_UNITS}


def build_offline_plan(*, write: bool = True) -> dict[str, Any]:
    config_hash = file_sha256(CONFIG_PATH)
    tasks = _task_rows()
    core = {
        "contract_version": CONTRACT_VERSION,
        "config_sha256": config_hash,
        "models": MODELS,
        "task_inputs": [{key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]} for task in tasks],
    }
    core_hash = content_sha256(core)
    coverage_by_cell = _coverage_lookup()
    rows: list[dict[str, Any]] = []
    coverage_map: dict[str, dict[str, Any]] = {}

    def emit(case_id: str, model_id: str, repeat: int, variant_id: str) -> None:
        seed = derive_seed(case_id, model_id, repeat)
        identity = {
            "benchmark_id": BENCHMARK_ID,
            "case_id": case_id,
            "harness_config_sha256": config_hash,
            "plan_core_sha256": core_hash,
            "repeat": repeat,
            "requested_model_id": model_id,
            "seed": seed,
            "variant_id": variant_id,
        }
        run_id = build_run_id(identity)
        next(item for item in tasks if item["case_id"] == case_id)["run_ids"].append(run_id)
        rows.append({"sequence": len(rows) + 1, "model_id": model_id, "repeat": repeat, "seed": seed, "run_id": run_id, "run_identity": identity})

    # Block 1: repeat-1 coverage of the 10 invalidated (case, model) units,
    # ordered by their v3.10 execution sequence.
    for unit in COVERAGE_UNITS:
        task = next(item for item in tasks if item["case_id"] == unit["case_id"])
        emit(unit["case_id"], unit["model_id"], 1, task["variant_id"])
        coverage_map[rows[-1]["run_id"]] = {
            "v3_10_run_id": unit["v3_10_run_id"],
            "v3_10_sequence": unit["v3_10_sequence"],
            "case_id": unit["case_id"],
            "model_id": unit["model_id"],
            "repeat": 1,
        }

    # Block 2: repeat 2-3 extension over all 90 tasks x 3 models, repeat-major,
    # then case_id, then the fixed model order (same blocking as v3.10).
    for repeat in EXTENSION_REPEATS:
        for task in tasks:
            for model_id in MODELS:
                emit(task["case_id"], model_id, repeat, task["variant_id"])

    old_plan = read_json(V310_PLAN)
    plan = {
        "contract_type": "stage3_financial_acceptance_plan",
        "contract_version": CONTRACT_VERSION,
        "status": "frozen_offline_validated",
        "supersedes": {"path": "contracts/stage3_acceptance_plan.v3.10.json", "sha256": file_sha256(V310_PLAN), "plan_sha256": old_plan["plan_sha256"]},
        "token_budget_repair": {
            "issue": "PER-61",
            "direction": "option_a_cumulative_schema_cap",
            "schema_maximum": CUMULATIVE_MAX_TOTAL_TOKENS,
            "derivation": TOKEN_BUDGET_DERIVATION,
            "prompt_oracle_threshold_reason_case_material_unchanged": True,
        },
        "authorization": {
            "paid_calls_authorized": False,
            "execution_state": "offline_validation_only",
            "separate_plan_bound_authorization_required": True,
            "passing_identity_preflight_required": True,
        },
        "continuation_run_cap": CONTINUATION_RUN_CAP,
        "registered_total_run_cap": CONTINUATION_RUN_CAP,
        "replication_design": {
            "master_seed": MASTER_SEED,
            "benchmark_id": BENCHMARK_ID,
            "kind": "continuation",
            "seed_derivation": (
                "seed = int(sha256(canonical_json({benchmark_id, case_id, master_seed, repeat, requested_model_id}))[:16], 16) mod 2^32; "
                "canonical_json sorts keys, uses compact separators, and preserves non-ASCII; the derivation is order-independent; "
                "the formula continues v3.5-v3.10 unchanged with the v3.11 benchmark id"
            ),
            "coverage_repeat1_units": COVERAGE_RUN_COUNT,
            "extension_repeats": EXTENSION_REPEATS,
            "blocking": (
                "sequences 1-10 cover the 10 invalidated v3.10 repeat-1 (case, model) units ordered by their v3.10 sequence; "
                "sequences 11-550 are the repeat 2-3 extension, repeat-major, then case_id, then the fixed model order"
            ),
            "no_post_hoc_selection": True,
            "invalidation_policy": (
                "invalidated units are reported against their frozen identities; replacements require a new plan version "
                "and are never silently reselected"
            ),
            "v3_10_invalidation_forensics": {
                "preserved": True,
                "invalidated_runs_path": "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json",
                "invalidated_runs_file_sha256": V310_INVALIDATED_RUNS_FILE_SHA256,
                "invalidation_report_sha256": V310_INVALIDATED_REPORT_SHA256,
                "entry_count": COVERAGE_RUN_COUNT,
                "grading_failures_dir": "runs/stage3/acceptance-20260813-v3.10/grading-failures/",
                "coverage_replaces_or_reexecutes_invalidation": False,
            },
        },
        "coverage_map": coverage_map,
        "plan_core_sha256": core_hash,
        "fairness": {"same_prompt_tools_budget_retry_grader": True, "models": MODELS},
        "tasks": tasks,
        "runs": rows,
    }
    plan["plan_sha256"] = content_sha256(plan)
    if write:
        write_json(PLAN_PATH, plan)
    return plan


# ---------------------------------------------------------------------------
# Bundle + freeze.
# ---------------------------------------------------------------------------


def _artifact_paths() -> list[pathlib.Path]:
    return [
        OUTPUT_PATH, WIRE_PATH, REASON_PATH, CONFIG_PATH, TRACE_SCHEMA_PATH, GRADER_SCHEMA_PATH,
        ROOT / "contracts/run_trace_validator_v3_11.py",
        ROOT / "src/financial_agent_reliability/harness/acceptance_v3_11.py",
        ROOT / "src/financial_agent_reliability/harness/live_acceptance_v3_11.mjs",
        PLAN_PATH,
        *sorted(PROJECTION_DIR.glob("*.json")),
        ROOT / "tests/test_financial_acceptance_v3_11.py",
        ROOT / "tests/integration/financial_acceptance_v3_11.test.mjs",
        *sorted(FIXTURE_DIR.glob("*.json")),
    ]


def build_contract_manifest() -> dict[str, Any]:
    artifacts = [{"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha256(path)} for path in _artifact_paths()]
    return {
        "contract_type": "stage3_financial_acceptance_execution_bundle",
        "contract_version": CONTRACT_VERSION,
        "status": "frozen_offline_validated",
        "supersedes": {"path": V310_BUNDLE.relative_to(ROOT).as_posix(), "sha256": file_sha256(V310_BUNDLE), "v3_10_bundle_sha256": PRIOR_BUNDLE_SHA256["3.10"]},
        "preserved": {f"v{version.replace('.', '_')}_bundle_sha256": digest for version, digest in PRIOR_BUNDLE_SHA256.items()} | {"retroactive_regrading": False},
        "token_budget_repair": {"issue": "PER-61", "direction": "option_a_cumulative_schema_cap", "schema_maximum": CUMULATIVE_MAX_TOTAL_TOKENS},
        "comparability": {
            "v3_10_frozen_units_remain_valid_and_comparable": True,
            "only_change": "cumulative usage.total_tokens ceiling (32768 -> 262144); prompts, oracle expectations, scoring thresholds, reason semantics, and case materials unchanged",
        },
        "paid_calls_authorized": False,
        "artifacts": artifacts,
        "bundle_sha256": content_sha256(artifacts),
    }


def validate_contract_bundle(manifest: Mapping[str, Any] | None = None, *, run_gate: bool = True) -> list[str]:
    result = dict(manifest or read_json(BUNDLE_PATH))
    errors: list[str] = []
    for version, wanted in PRIOR_BUNDLE_SHA256.items():
        bundle = read_json(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        if bundle.get("bundle_sha256") != wanted:
            errors.append(f"v{version} bundle drift")
        for item in bundle.get("artifacts", []):
            path = ROOT / item["path"]
            if not path.is_file() or file_sha256(path) != item["sha256"]:
                errors.append(f"v{version} artifact drift:{item['path']}")
    for item in result.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or file_sha256(path) != item["sha256"]:
            errors.append(f"v3.11 artifact drift:{item['path']}")
    if content_sha256(result.get("artifacts", [])) != result.get("bundle_sha256"):
        errors.append("v3.11 bundle mismatch")
    errors.extend(material_completeness_errors())
    errors.extend(gold_cross_check_errors())
    if run_gate:
        errors.extend(visibility_gate_errors(read_json(PLAN_PATH)))
    return errors


def visibility_gate_errors(plan: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks = plan.get("tasks", [])
    if not tasks:
        errors.append("visibility gate expects at least one task")
    for task in tasks:
        projection = read_json(ROOT / task["projection_path"])
        snapshot = read_json(ROOT / task["snapshot_path"])
        if file_sha256(ROOT / task["projection_path"]) != task.get("projection_sha256") or file_sha256(ROOT / task["snapshot_path"]) != task.get("snapshot_sha256"):
            errors.append(f"visibility gate input drift:{task['case_id']}")
            continue
        report = oracle_visibility_report_v310(projection, snapshot)
        errors.extend(f"oracle visibility violation:{task['case_id']}:{item}" for item in report["violations"])
    return errors


# ---------------------------------------------------------------------------
# Offline fixtures.
# ---------------------------------------------------------------------------


def _tool_event(sequence: int, tool_name: str, input_value: Any, output: Any, unit_hash: str | None = None, operation: str | None = None, record_id: str | None = None, implementation: str | None = None, before: str | None = None, after: str | None = None, ledger_transition: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"sequence": sequence, "tool_name": tool_name, "success": True, "input_sha256": content_sha256(input_value), "output_sha256": content_sha256(output), "unit_basis_sha256": unit_hash, "operation": operation, "record_id": record_id, "implementation": implementation, "state_before_sha256": before, "state_after_sha256": after, "ledger_transition": dict(ledger_transition) if ledger_transition else None}


def _fixture_trace(plan: Mapping[str, Any], case_id: str, model_id: str, repeat: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    task = next(item for item in plan["tasks"] if item["case_id"] == case_id)
    row = next(item for item in plan["runs"] if item["run_id"] in task["run_ids"] and item["model_id"] == model_id and item["repeat"] == repeat)
    projection, snapshot = read_json(ROOT / task["projection_path"]), read_json(ROOT / task["snapshot_path"])
    expected = independent_expected_v310(projection, snapshot)
    config = read_json(CONFIG_PATH)
    calculation = expected_calculation_v310(projection, snapshot)
    records = {item["record_id"]: item for item in snapshot.get("records", [])}
    tools: list[dict[str, Any]] = []
    material = list(projection["evidence_contract"]["material_record_ids"])
    for record_id in material:
        record = records[record_id]
        unit_hash = content_sha256({"answer_schema": projection["answer_value_schema"], "record_id": record["record_id"], "source_unit": str(record["payload"].get("unit", "not_applicable"))})
        tools.append(_tool_event(len(tools) + 1, "read_frozen_evidence", {"record_id": record_id}, record, unit_hash, "read", record_id))
    if calculation is not None:
        tools.append(_tool_event(len(tools) + 1, "calculate", calculation["inputs"], calculation["output"], None, calculation["operation"], implementation=CALCULATION_IMPLEMENTATION))
    candidate = {**expected, "evidence_record_ids": material, "uncertainty": "low" if expected["status"] == "answer" else "high", "permission_boundary_claimed": True}
    attempt = {"attempt_index": 0, "model_id": row["model_id"], "response_model_id": row["model_id"], "http_status": 200, "assistant_action_valid": True, "classification": "success", "payload_sha256": "a" * 64, "seed": row["seed"], "started_at": "2026-08-13T00:00:00Z", "finished_at": "2026-08-13T00:00:01Z", "duration_ms": 1000, "input_tokens": 10, "output_tokens": 10, "provider_error_code": None}
    request = {"request_index": 1, "phase": "initial", "model_id": row["model_id"], "seed": row["seed"], "payload_sha256": "a" * 64, "tool_schema_sha256": task["tool_schema_sha256"], "parameters_sha256": config["request_commitments"]["parameters_sha256_by_model"][row["model_id"]], "retries_used": 0, "classification": "success", "attempts": [attempt]}
    empty_root = content_sha256({})
    trace = {
        "contract_type": "run_trace", "contract_version": CONTRACT_VERSION, "run_id": row["run_id"], "run_identity": row["run_identity"],
        "status": "succeeded",
        "provider": {"name": "bailian", "requested_model_id": row["model_id"], "response_model_id": row["model_id"], "endpoint_id": "bailian_000000000000"},
        "logical_requests": [request],
        "usage": {"model_requests": 1, "provider_attempts": 1, "tool_calls": len(tools), "total_tokens": 20},
        "failure": {"class": None, "code": None},
        "result": {"candidate_scored": True, "structured_output_valid": True, "candidate_output_sha256": content_sha256(candidate), "raw_provider_response_stored": False},
        "evidence_observations": [
            {"record_id": record_id, "snapshot_id": snapshot["snapshot_id"], "source_locator": records[record_id]["source_locator"], "available_at": snapshot["temporal"]["available_at"], "event_time": snapshot["temporal"]["event_time"], "read_succeeded": True}
            for record_id in material
        ],
        "tool_events": tools,
        "reason_facts": {},
        "permission": {"trace_complete": True, "declared_permissions": projection["task"]["permissions"], "observed_operations": [item["tool_name"] for item in tools], "violations": []},
        "environment": {"dataset_access": "frozen_read_only", "ledger_mode": "simulated", "initial_ledger_sha256": empty_root, "final_ledger_sha256": empty_root, "final_state_matches_initial": True, "real_side_effects": False, "network_scope": "none_offline_fixture"},
        "redaction": {"applied": True, "raw_provider_response_stored": False, "raw_submission_arguments_persisted": False, "secret_leakage_detected": False},
        "checkpoint": {"event_count": len(tools) + 2, "final_event_sha256": "b" * 64},
    }
    return trace, candidate, projection, snapshot


def _long_context_trace(plan: Mapping[str, Any], case_id: str, model_id: str, repeat: int) -> dict[str, Any]:
    """A valid 8-request (6 initial + 2 repair) trace whose cumulative
    total_tokens (40000) exceeds the old v3.10 single-request ceiling (32768)
    but sits inside the v3.11 budget-design ceiling (262144). It proves the
    repair makes legitimately long sessions freezable."""
    trace, _, _, _ = _fixture_trace(plan, case_id, model_id, repeat)
    config = read_json(CONFIG_PATH)
    base = trace["logical_requests"][0]
    requests = []
    for index in range(MAX_MODEL_REQUESTS):
        request = copy.deepcopy(base)
        request["request_index"] = index + 1
        request["phase"] = "initial" if index < config["resource_budget"]["initial_model_requests"] else "repair"
        request["payload_sha256"] = f"{index + 1:0>64x}"[-64:]
        for attempt in request["attempts"]:
            attempt["payload_sha256"] = request["payload_sha256"]
            # Uniform synthetic per-request usage: 8 x (4500 + 500) = 40000,
            # comfortably above the old 32768 single-request ceiling and inside
            # the 262144 budget-design ceiling; deliberately round, not fitted.
            attempt["input_tokens"] = 4500
            attempt["output_tokens"] = 500
        requests.append(request)
    trace["logical_requests"] = requests
    trace["usage"]["model_requests"] = len(requests)
    trace["usage"]["provider_attempts"] = sum(len(item["attempts"]) for item in requests)
    trace["usage"]["total_tokens"] = sum(attempt["input_tokens"] + attempt["output_tokens"] for item in requests for attempt in item["attempts"])
    return trace


def freeze_contracts() -> pathlib.Path:
    PROJECTION_DIR.mkdir(parents=True, exist_ok=True)
    for entry in case_card_index():
        projection = build_projection_v311(entry["card"], source_case_path=entry["card_path"].relative_to(ROOT).as_posix())
        write_json(PROJECTION_DIR / f"{projection['case_id']}.json", projection)
    write_json(CONFIG_PATH, _config())
    write_json(REASON_PATH, _reason_doc())
    write_json(WIRE_PATH, _wire())
    write_json(OUTPUT_PATH, _output_contract())
    write_json(TRACE_SCHEMA_PATH, _trace_schema())
    write_json(GRADER_SCHEMA_PATH, _grader_schema())
    plan = build_offline_plan(write=True)

    fixture_answers: dict[str, Any] = {}
    for task in plan["tasks"]:
        projection_item = read_json(ROOT / task["projection_path"])
        snapshot_item = read_json(ROOT / task["snapshot_path"])
        expected_item = independent_expected_v310(projection_item, snapshot_item)
        fixture_answers[task["case_id"]] = {
            **expected_item,
            "evidence_record_ids": projection_item["evidence_contract"]["material_record_ids"],
            "uncertainty": "low" if expected_item["status"] == "answer" else "high",
            "permission_boundary_claimed": True,
        }
    write_json(FIXTURE_DIR / "candidate_answers.synthetic.json", fixture_answers)

    # Grader fixtures reuse the exact v3.10 case choices; every cell is a
    # repeat-2 extension identity so it is an in-plan v3.11 run.
    _persist_grader_fixture(plan, "grader.baseline.json", "case-public-fkw-01-normal-v3")
    _persist_grader_fixture(plan, "grader.average_contract.json", "case-public-fkw-02-normal-v3")
    _persist_grader_fixture(plan, "grader.ftw_workflow.json", "case-synthetic-ftw-05-normal-v3")
    _persist_grader_fixture(plan, "grader.bounded_retry.json", "case-synthetic-ftw-10-single-factor-perturbation-v3")

    # Long-context fixture: a repeat-1 COVERAGE identity (v3.10 sequence 146)
    # executed as a valid 8-request session whose cumulative tokens exceed the
    # old v3.10 ceiling — proves the repair makes coverage units freezable.
    write_json(FIXTURE_DIR / "trace.long_context_cumulative_tokens.json", _long_context_trace(plan, COVERAGE_UNITS[0]["case_id"], COVERAGE_UNITS[0]["model_id"], 1))

    trace, candidate, projection, snapshot = _fixture_trace(plan, "case-public-fkw-01-normal-v3", MODELS[0], 2)
    ledger = copy.deepcopy(trace)
    empty, held = content_sha256({}), content_sha256({"SYN": "2.5"})
    ledger_events = [
        _tool_event(len(ledger["tool_events"]) + 1, "simulated_ledger", {"operation": "buy", "instrument": "SYN", "quantity": "2.5"}, {"resulting_quantity": "2.5"}, operation="buy", implementation=LEDGER_IMPLEMENTATION, before=empty, after=held, ledger_transition={"instrument": "SYN", "quantity": "2.5", "resulting_quantity": "2.5"}),
        _tool_event(len(ledger["tool_events"]) + 2, "simulated_ledger", {"operation": "sell", "instrument": "SYN", "quantity": "2.5"}, {"resulting_quantity": "0"}, operation="sell", implementation=LEDGER_IMPLEMENTATION, before=held, after=empty, ledger_transition={"instrument": "SYN", "quantity": "2.5", "resulting_quantity": "0"}),
    ]
    ledger["tool_events"] += ledger_events
    ledger["usage"]["tool_calls"] += 2
    ledger["permission"]["observed_operations"] += ["simulated_ledger", "simulated_ledger"]
    ledger["permission"]["declared_permissions"] += ["simulated_state_read"]
    write_json(FIXTURE_DIR / "trace.ledger_restored.json", ledger)

    gate_report = {
        "gate": "oracle_expectations_subset_of_candidate_visible_contract",
        "contract_version": CONTRACT_VERSION,
        "plan_sha256": plan["plan_sha256"],
        "cases": [oracle_visibility_report_v310(read_json(ROOT / task["projection_path"]), read_json(ROOT / task["snapshot_path"])) for task in plan["tasks"]],
    }
    gate_report["all_visible"] = all(case["visible"] for case in gate_report["cases"])
    write_json(FIXTURE_DIR / "oracle_visibility.report.json", gate_report)
    negative_results = run_gate_negative_scenarios_v310()
    write_json(FIXTURE_DIR / "oracle_visibility.negative.json", {"gate": "oracle_expectations_subset_of_candidate_visible_contract", "contract_version": CONTRACT_VERSION, "scenarios": negative_results, "all_caught": all(item["caught"] for item in negative_results)})
    write_json(BUNDLE_PATH, build_contract_manifest())
    return BUNDLE_PATH


def _persist_grader_fixture(plan: Mapping[str, Any], name: str, case_id: str, repeat: int = 2) -> None:
    trace, candidate, projection, snapshot = _fixture_trace(plan, case_id, MODELS[0], repeat)
    task = next(item for item in plan["tasks"] if item["case_id"] == case_id)
    write_json(FIXTURE_DIR / name, {"projection_path": task["projection_path"], "snapshot_path": task["snapshot_path"], "candidate": candidate, "trace": trace})


def scan_fixtures() -> list[str]:
    return [f"{path.relative_to(ROOT)}:{finding}" for path in FIXTURE_DIR.glob("*.json") for finding in scan_persisted_value_for_secrets(read_json(path))]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze-contracts", "verify-contracts", "verify-plan", "scan-fixtures", "validate-trace", "gate-report", "gold-report"])
    parser.add_argument("--trace")
    args = parser.parse_args()
    if args.command == "freeze-contracts":
        path = freeze_contracts(); print(json.dumps({"path": str(path.relative_to(ROOT)), "bundle_sha256": read_json(path)["bundle_sha256"]}))
    elif args.command == "verify-contracts":
        errors = validate_contract_bundle(); print(json.dumps({"valid": not errors, "errors": errors, "bundle_sha256": read_json(BUNDLE_PATH).get("bundle_sha256")})); raise SystemExit(0 if not errors else 2)
    elif args.command == "verify-plan":
        actual, expected = read_json(PLAN_PATH), build_offline_plan(write=False); errors = [] if actual == expected else ["plan not reproducible"]; print(json.dumps({"valid": not errors, "errors": errors, "plan_sha256": actual.get("plan_sha256")})); raise SystemExit(0 if not errors else 2)
    elif args.command == "scan-fixtures":
        findings = scan_fixtures(); print(json.dumps({"valid": not findings, "findings": findings, "files_scanned": len(list(FIXTURE_DIR.glob('*.json')))})); raise SystemExit(0 if not findings else 2)
    elif args.command == "gate-report":
        report = {"cases": [oracle_visibility_report_v310(read_json(ROOT / task["projection_path"]), read_json(ROOT / task["snapshot_path"])) for task in read_json(PLAN_PATH)["tasks"]]}
        print(json.dumps(report, ensure_ascii=False, indent=1))
    elif args.command == "gold-report":
        errors = gold_cross_check_errors()
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=1)); raise SystemExit(0 if not errors else 2)
    else:
        document = read_json(pathlib.Path(args.trace)); print(json.dumps(validate_run_trace_v311(document.get("trace", document))))
