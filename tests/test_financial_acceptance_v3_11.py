import copy
import json
import pathlib
import unittest

from contracts.run_trace_validator_v3_10 import HarnessContractV310Error, validate_run_trace_v310
from contracts.run_trace_validator_v3_11 import HarnessContractV311Error, validate_run_trace_v311
from financial_agent_reliability.harness.acceptance_v3_10 import (
    independent_expected_v310,
    grade_candidate_v310,
)
from financial_agent_reliability.harness.acceptance_v3_11 import (
    BENCHMARK_ID,
    CONTINUATION_RUN_CAP,
    COVERAGE_UNITS,
    CUMULATIVE_MAX_TOTAL_TOKENS,
    MASTER_SEED,
    MAX_MODEL_REQUESTS,
    SINGLE_REQUEST_CONTEXT_WINDOW,
    TOKEN_BUDGET_DERIVATION,
    build_contract_manifest,
    build_offline_plan,
    case_card_index,
    content_sha256,
    derive_seed,
    gold_cross_check_errors,
    grade_candidate_v311,
    material_completeness_errors,
    oracle_visibility_report_v310,
    read_json,
    reason_definitions_v310,
    validate_contract_bundle,
    ROOT,
)


FIXTURES = ROOT / "tests" / "fixtures" / "acceptance_v3_11"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FinancialAcceptanceV311Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = load(FIXTURES / "grader.baseline.json")
        self.projection = load(ROOT / self.fixture["projection_path"])
        self.snapshot = load(ROOT / self.fixture["snapshot_path"])
        self.candidate = self.fixture["candidate"]
        self.trace = self.fixture["trace"]

    def assertTraceRejected(self, mutate, pattern):
        trace = copy.deepcopy(self.trace)
        mutate(trace)
        with self.assertRaisesRegex(HarnessContractV311Error, pattern):
            validate_run_trace_v311(trace)

    # -- Token-budget consistency repair (PER-61) -----------------------------

    def test_token_budget_ceiling_is_budget_design_derived_not_back_derived(self):
        self.assertEqual(SINGLE_REQUEST_CONTEXT_WINDOW, 32768)
        self.assertEqual(MAX_MODEL_REQUESTS, 8)
        self.assertEqual(CUMULATIVE_MAX_TOTAL_TOKENS, MAX_MODEL_REQUESTS * SINGLE_REQUEST_CONTEXT_WINDOW)
        self.assertEqual(CUMULATIVE_MAX_TOTAL_TOKENS, 262144)
        self.assertEqual(TOKEN_BUDGET_DERIVATION["result"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertFalse(TOKEN_BUDGET_DERIVATION["back_derived_from_observed_usage"])
        # The ceiling is a design product, comfortably above the observed v3.10
        # usage band (35,484-39,795) and not fitted to it.
        self.assertGreater(CUMULATIVE_MAX_TOTAL_TOKENS, 40000)

    def test_config_and_schema_total_tokens_ceiling_are_consistent(self):
        config = load(ROOT / "contracts" / "run_trace_harness_config.v3.11.json")
        schema = load(ROOT / "contracts" / "run_trace.schema.v3.11.json")
        budget = config["resource_budget"]
        self.assertEqual(budget["max_total_tokens"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertEqual(budget["single_request_context_window"], SINGLE_REQUEST_CONTEXT_WINDOW)
        self.assertEqual(budget["max_total_tokens_derivation"]["result"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertFalse(budget["max_total_tokens_derivation"]["back_derived_from_observed_usage"])
        self.assertEqual(schema["properties"]["usage"]["properties"]["total_tokens"]["maximum"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertEqual(config["token_budget_repair"]["schema_maximum"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertTrue(config["token_budget_repair"]["three_model_symmetric"])
        self.assertTrue(config["token_budget_repair"]["prompt_oracle_threshold_reason_case_material_unchanged"])

    def test_long_context_multi_request_trace_is_now_freezable(self):
        trace = load(FIXTURES / "trace.long_context_cumulative_tokens.json")
        # Cumulative tokens exceed the old v3.10 single-request ceiling ...
        self.assertGreater(trace["usage"]["total_tokens"], 32768)
        # ... and sit inside the v3.11 budget-design ceiling.
        self.assertLessEqual(trace["usage"]["total_tokens"], CUMULATIVE_MAX_TOTAL_TOKENS)
        self.assertEqual(trace["usage"]["model_requests"], MAX_MODEL_REQUESTS)
        self.assertEqual(validate_run_trace_v311(trace)["status"], "succeeded")
        # The identical trace shape is rejected by the v3.10 schema, proving the
        # v3.10 defect and that the v3.11 change is what makes it freezable.
        v310_copy = copy.deepcopy(trace)
        v310_copy["contract_version"] = "3.10.0"
        v310_copy["run_identity"]["benchmark_id"] = "financial-agent-reliability-v3.10"
        with self.assertRaises(HarnessContractV310Error):
            validate_run_trace_v310(v310_copy)

    def test_schema_rejects_usage_above_the_budget_design_ceiling(self):
        trace = copy.deepcopy(load(FIXTURES / "trace.long_context_cumulative_tokens.json"))
        trace["usage"]["total_tokens"] = CUMULATIVE_MAX_TOTAL_TOKENS + 1
        with self.assertRaisesRegex(HarnessContractV311Error, "total_tokens"):
            validate_run_trace_v311(trace)

    # -- Minimal-change comparability with v3.10 ------------------------------

    def test_projections_are_content_identical_to_v310_except_version_metadata(self):
        plan = build_offline_plan(write=False)
        ignored = {"contract_version", "supersedes"}
        for task in plan["tasks"]:
            v310 = load(ROOT / "cases" / "candidate_v3_10" / f"{task['case_id']}.json")
            v311 = load(ROOT / task["projection_path"])
            for key in set(v310) | set(v311):
                if key in ignored:
                    continue
                self.assertEqual(
                    json.dumps(v310.get(key), sort_keys=True),
                    json.dumps(v311.get(key), sort_keys=True),
                    f"{task['case_id']}:{key}",
                )

    def test_oracle_and_grader_outputs_are_identical_to_v310_for_all_90_cases(self):
        plan = build_offline_plan(write=False)
        for task in plan["tasks"]:
            snapshot = load(ROOT / task["snapshot_path"])
            v310_projection = load(ROOT / "cases" / "candidate_v3_10" / f"{task['case_id']}.json")
            v311_projection = load(ROOT / task["projection_path"])
            self.assertEqual(
                independent_expected_v310(v310_projection, snapshot),
                independent_expected_v310(v311_projection, snapshot),
                task["case_id"],
            )

    def test_tool_schema_commitments_are_identical_to_v310(self):
        plan_v310 = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.10.json")
        plan_v311 = build_offline_plan(write=False)
        v310_by_case = {task["case_id"]: task for task in plan_v310["tasks"]}
        for task in plan_v311["tasks"]:
            self.assertEqual(task["tool_schema_sha256"], v310_by_case[task["case_id"]]["tool_schema_sha256"], task["case_id"])
            self.assertEqual(task["snapshot_sha256"], v310_by_case[task["case_id"]]["snapshot_sha256"], task["case_id"])
            self.assertEqual(task["source_case_sha256"], v310_by_case[task["case_id"]]["source_case_sha256"], task["case_id"])

    def test_config_changes_only_the_token_budget_block(self):
        v310_config = load(ROOT / "contracts" / "run_trace_harness_config.v3.10.json")
        v311_config = load(ROOT / "contracts" / "run_trace_harness_config.v3.11.json")
        # Unchanged grading-relevant surfaces.
        for key in ["system_prompt", "tool_names", "provider_retry_policy", "security", "fairness"]:
            self.assertEqual(v311_config[key], v310_config[key], key)
        self.assertEqual(v311_config["request_commitments"], v310_config["request_commitments"])
        # Resource budget: only the token ceiling and its derivation change.
        old_budget = dict(v310_config["resource_budget"])
        new_budget = dict(v311_config["resource_budget"])
        self.assertEqual(old_budget.pop("max_total_tokens"), 32768)
        self.assertEqual(new_budget.pop("max_total_tokens"), CUMULATIVE_MAX_TOTAL_TOKENS)
        new_budget.pop("single_request_context_window")
        new_budget.pop("max_total_tokens_derivation")
        self.assertEqual(new_budget, old_budget)

    # -- Continuation plan: 550 identities ------------------------------------

    def test_continuation_plan_registers_550_identities(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["tasks"]), 90)
        self.assertEqual(len(plan["runs"]), CONTINUATION_RUN_CAP)
        self.assertEqual(CONTINUATION_RUN_CAP, 550)
        self.assertEqual(plan["continuation_run_cap"], 550)
        self.assertEqual(plan["registered_total_run_cap"], 550)
        self.assertFalse(plan["authorization"]["paid_calls_authorized"])
        coverage = [row for row in plan["runs"] if row["repeat"] == 1]
        extension = [row for row in plan["runs"] if row["repeat"] in (2, 3)]
        self.assertEqual(len(coverage), 10)
        self.assertEqual(len(extension), 540)
        self.assertEqual([row["sequence"] for row in coverage], list(range(1, 11)))
        self.assertEqual(len({row["run_id"] for row in plan["runs"]}), 550)

    def test_coverage_units_match_the_v310_invalidated_forensics(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(COVERAGE_UNITS), 10)
        self.assertEqual(len(plan["coverage_map"]), 10)
        forensics = load(ROOT / "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json")
        forensics_by_run = {entry["run_id"]: entry for entry in forensics["entries"]}
        coverage_rows = [row for row in plan["runs"] if row["repeat"] == 1]
        covered_v310 = set()
        for row in coverage_rows:
            mapping = plan["coverage_map"][row["run_id"]]
            self.assertEqual(mapping["case_id"], row["run_identity"]["case_id"])
            self.assertEqual(mapping["model_id"], row["model_id"])
            self.assertEqual(mapping["repeat"], 1)
            self.assertIn(mapping["v3_10_run_id"], forensics_by_run)
            source = forensics_by_run[mapping["v3_10_run_id"]]
            self.assertEqual(source["case_id"], mapping["case_id"])
            self.assertEqual(source["model_id"], mapping["model_id"])
            self.assertEqual(source["sequence"], mapping["v3_10_sequence"])
            self.assertFalse(source["replaced_or_reexecuted"])
            covered_v310.add(mapping["v3_10_run_id"])
        self.assertEqual(covered_v310, set(forensics_by_run))
        design = plan["replication_design"]["v3_10_invalidation_forensics"]
        self.assertTrue(design["preserved"])
        self.assertFalse(design["coverage_replaces_or_reexecutes_invalidation"])
        self.assertEqual(design["entry_count"], 10)

    def test_run_identities_are_disjoint_from_all_prior_versions(self):
        plan = build_offline_plan(write=False)
        ids = {row["run_id"] for row in plan["runs"]}
        for version in ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]:
            old = load(ROOT / "contracts" / f"stage3_acceptance_plan.v{version}.json")
            self.assertFalse(ids & {row["run_id"] for row in old["runs"]}, version)

    def test_seeds_derive_from_the_frozen_master_seed_independent_of_order(self):
        plan = build_offline_plan(write=False)
        for row in plan["runs"]:
            identity = {"benchmark_id": BENCHMARK_ID, "case_id": row["run_identity"]["case_id"], "master_seed": MASTER_SEED, "repeat": row["repeat"], "requested_model_id": row["model_id"]}
            self.assertEqual(row["seed"], int(content_sha256(identity)[:16], 16) % 2**32)
            self.assertEqual(row["seed"], derive_seed(row["run_identity"]["case_id"], row["model_id"], row["repeat"]))
            self.assertEqual(row["run_identity"]["seed"], row["seed"])

    def test_verify_plan_reproduces_the_frozen_plan_exactly(self):
        actual = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.11.json")
        expected = build_offline_plan(write=False)
        self.assertEqual(actual, expected)

    # -- Bundle, gates, zero-drift -------------------------------------------

    def test_v311_preserves_all_prior_bundles_and_passes_every_freeze_gate(self):
        manifest = build_contract_manifest()
        self.assertEqual(validate_contract_bundle(manifest), [])
        self.assertEqual(manifest["supersedes"]["v3_10_bundle_sha256"], "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180")
        self.assertEqual(manifest["preserved"]["v3_10_bundle_sha256"], "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180")
        self.assertFalse(manifest["preserved"]["retroactive_regrading"])
        self.assertFalse(manifest["paid_calls_authorized"])
        self.assertTrue(manifest["comparability"]["v3_10_frozen_units_remain_valid_and_comparable"])
        self.assertEqual(len(manifest["artifacts"]), len({item["path"] for item in manifest["artifacts"]}))

    def test_stage2_materials_are_complete_and_gold_parity_holds(self):
        self.assertEqual(len(case_card_index()), 90)
        self.assertEqual(material_completeness_errors(), [])
        self.assertEqual(gold_cross_check_errors(), [])

    def test_visibility_gate_passes_for_all_90_v311_cases(self):
        plan = build_offline_plan(write=False)
        for task in plan["tasks"]:
            report = oracle_visibility_report_v310(load(ROOT / task["projection_path"]), load(ROOT / task["snapshot_path"]))
            self.assertTrue(report["visible"], f"{task['case_id']}: {report['violations']}")
        persisted = load(FIXTURES / "oracle_visibility.report.json")
        self.assertTrue(persisted["all_visible"])
        self.assertEqual(len(persisted["cases"]), 90)

    def test_reason_vocabulary_is_unchanged_from_v310(self):
        definitions = reason_definitions_v310()
        self.assertEqual(len(definitions), 21)
        reason_doc = load(ROOT / "contracts" / "reason_codes.v3.11.json")
        self.assertEqual(reason_doc["contract_version"], "3.11.0")
        self.assertEqual(len(reason_doc["case_sets"]), 90)
        v310_doc = load(ROOT / "contracts" / "reason_codes.v3.10.json")
        self.assertEqual(reason_doc["definitions"], v310_doc["definitions"])
        self.assertEqual(reason_doc["case_sets"], v310_doc["case_sets"])

    # -- Grader fixtures ------------------------------------------------------

    def test_baseline_case_grades_through_v311_grader_identically_to_v310(self):
        result = grade_candidate_v311(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertTrue(result["checks"]["candidate_trace_bound"])
        self.assertEqual(result["contract_version"], "3.11.0")
        self.assertEqual(result["grader_sha256"], content_sha256({key: value for key, value in result.items() if key != "grader_sha256"}))
        # The graded checks (everything except the version tag and hash) are
        # identical to what the v3.10 grader produces for the same inputs.
        v310_projection = load(ROOT / "cases" / "candidate_v3_10" / f"{self.trace['run_identity']['case_id']}.json")
        v310_result = grade_candidate_v310(self.candidate, v310_projection, self.snapshot, self.trace)
        self.assertEqual(result["checks"], v310_result["checks"])
        self.assertEqual(result["failed_checks"], v310_result["failed_checks"])
        self.assertEqual(result["derived_reason_codes"], v310_result["derived_reason_codes"])

    def test_average_case_enforces_the_disclosed_six_decimal_contract(self):
        fixture = load(FIXTURES / "grader.average_contract.json")
        projection = load(ROOT / fixture["projection_path"])
        snapshot = load(ROOT / fixture["snapshot_path"])
        result = grade_candidate_v311(fixture["candidate"], projection, snapshot, fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertTrue(result["checks"]["decimal_lexical_correct"])
        self.assertTrue(result["checks"]["calculation_correct"])

    def test_bounded_retry_answer_requires_the_informational_success_code(self):
        fixture = load(FIXTURES / "grader.bounded_retry.json")
        projection = load(ROOT / fixture["projection_path"])
        snapshot = load(ROOT / fixture["snapshot_path"])
        self.assertEqual(fixture["candidate"]["reason_codes"], ["BOUNDED_RETRY_SUCCEEDED"])
        result = grade_candidate_v311(fixture["candidate"], projection, snapshot, fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])

    # -- Trace validation -----------------------------------------------------

    def test_attempt_response_identity_http_and_phase_are_derived_not_self_reported(self):
        self.assertEqual(validate_run_trace_v311(self.trace)["status"], "succeeded")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(response_model_id="deepseek-v4-pro"), "attempt response model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(http_status=429), "HTTP classification")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(phase="repair"), "first request must be initial")

    def test_ledger_terminal_state_is_recomputed_from_state_roots(self):
        trace = load(FIXTURES / "trace.ledger_restored.json")
        self.assertEqual(validate_run_trace_v311(trace)["status"], "succeeded")
        changed = copy.deepcopy(trace)
        changed["environment"]["final_ledger_sha256"] = "f" * 64
        with self.assertRaisesRegex(HarnessContractV311Error, "ledger terminal state"):
            validate_run_trace_v311(changed)

    def test_sensitive_scanner_is_a_validator_gate_for_trace_and_companions(self):
        changed = copy.deepcopy(self.trace)
        changed["failure"]["code"] = "Bearer SYNTHETIC_TOKEN_123"
        with self.assertRaisesRegex(HarnessContractV311Error, "secret-like persisted value"):
            validate_run_trace_v311(changed)

    def test_fixture_secret_scan_is_clean(self):
        from financial_agent_reliability.harness.acceptance_v3_11 import scan_fixtures
        self.assertEqual(scan_fixtures(), [])
        self.assertGreaterEqual(len(list(FIXTURES.glob("*.json"))), 8)


if __name__ == "__main__":
    unittest.main()
