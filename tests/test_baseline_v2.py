"""Baseline v2 freeze tests (PER-328, PER-323 Stage 3).

Covers acceptance criterion v2 item 5: baseline v2 is frozen, 口径 v2 is
self-consistent, and tests cover the new baseline. This file also rewrites
the M1-deferred oracle-recomputation and case-data-validation suites from
baseline v1 (retired per cleanup list M1; see deletion record §5.3): every
Gold expectation is recomputed here by two independent oracle
implementations and compared against the frozen registration — public
answers and candidate outputs play no role.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "baseline" / "v2"))

import validate_baseline_v2 as validator  # noqa: E402

from financial_agent_reliability.graders import baseline_v2 as grader_v2  # noqa: E402
from financial_agent_reliability.graders.pipeline import GraderPipeline  # noqa: E402
from financial_agent_reliability.harness.secret_scan import scan_persisted_file  # noqa: E402

BASELINE = ROOT / "baseline" / "v2"
CASES = BASELINE / "cases"
SNAPSHOTS = BASELINE / "snapshots"
MANIFEST = BASELINE / "baseline_manifest.frozen.v2.json"
VALIDATION_CONFIG = BASELINE / "contracts" / "case_data_validation_config.v2.json"


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def all_cases() -> list[dict]:
    return [load(path) for path in sorted(CASES.glob("case-*.json"))]


def all_snapshots() -> dict[str, tuple[dict, pathlib.Path]]:
    result = {}
    for path in sorted(SNAPSHOTS.glob("data_snapshot.*.json")):
        snapshot = load(path)
        result[snapshot["snapshot_id"]] = (snapshot, path)
    return result


def load_module(relative_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strip_pointers(document: dict, pointers: list[str]) -> dict:
    clone = json.loads(json.dumps(document))
    for pointer in pointers:
        node = clone
        keys = [part for part in pointer.split("/") if part]
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node:
                break
            node = node[key]
        else:
            if isinstance(node, dict):
                node.pop(keys[-1], None)
    return clone


def diff_paths(left, right, prefix="") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths = set()
        for key in set(left) | set(right):
            child = f"{prefix}/{key}"
            if key not in left or key not in right:
                paths.add(child)
            else:
                paths |= diff_paths(left[key], right[key], child)
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = set()
        for index in range(max(len(left), len(right))):
            child = f"{prefix}/{index}"
            if index >= len(left) or index >= len(right):
                paths.add(child)
            else:
                paths |= diff_paths(left[index], right[index], child)
        return paths
    return {prefix} if left != right else set()


class BaselineV2ManifestTests(unittest.TestCase):
    def test_manifest_hashes_and_bundle_recompute(self):
        errors = validator.verify_manifest(BASELINE)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_manifest_covers_expected_artifact_classes(self):
        manifest = load(MANIFEST)
        paths = {entry["path"] for entry in manifest["artifacts"]}
        self.assertEqual(len(paths), len(manifest["artifacts"]))
        for required in (
            "baseline/v2/contracts/case_card.schema.v2.json",
            "baseline/v2/contracts/data_snapshot.schema.v2.json",
            "baseline/v2/contracts/run_trace.schema.v4.json",
            "baseline/v2/contracts/reason_codes.v2.json",
            "baseline/v2/contracts/grader_contract.frozen.v2.json",
            "baseline/v2/grader/grader_policy.v2.json",
            "baseline/v2/validate_baseline_v2.py",
            "baseline/v2/build/build_baseline_v2.py",
            "baseline/v2/build/capture_manifest.v2.json",
        ):
            self.assertIn(required, paths)
        self.assertTrue(any(path.startswith("baseline/v2/cases/") for path in paths))
        self.assertTrue(any(path.startswith("baseline/v2/snapshots/") for path in paths))
        self.assertTrue(any(path.startswith("baseline/v2/build/captures/") for path in paths))


class BaselineV2BundleSemanticsTests(unittest.TestCase):
    def test_cross_object_semantic_validation_passes(self):
        errors = validator.validate_bundle(BASELINE)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_minimal_scale_is_four_families_by_three_variants(self):
        cases = all_cases()
        snapshots = all_snapshots()
        self.assertEqual(len(cases), 12)
        self.assertEqual(len(snapshots), 8)
        families = {case["variant"]["family_id"] for case in cases}
        self.assertEqual(len(families), 4)
        for family in families:
            kinds = {
                case["variant"]["kind"] for case in cases if case["variant"]["family_id"] == family
            }
            self.assertEqual(
                kinds, {"normal", "single_factor_perturbation", "missing_or_anomalous"}
            )

    def test_public_seed_priority_and_longbridge_lineage(self):
        cases = all_cases()
        providers = {case["source"]["provider"] for case in cases}
        self.assertEqual(providers, {"sec_edgar", "longbridge"})
        snapshots = all_snapshots()
        for snapshot_id, (snapshot, _path) in snapshots.items():
            self.assertEqual(snapshot["access"]["mode"], "public_read_only")
            if snapshot["source"]["provider"] == "longbridge":
                self.assertFalse(snapshot["source"]["license"]["redistributable"])
            else:
                self.assertTrue(snapshot["source"]["license"]["redistributable"])
            if snapshot_id.endswith("-missing"):
                self.assertEqual(snapshot["records"], [])
                self.assertTrue(snapshot["lineage"]["parent_snapshot_ids"])

    def test_single_factor_semantic_diff_confined_to_declared_pointer(self):
        config = load(VALIDATION_CONFIG)
        ignored = config["semantic_diff_ignored_pointers"]
        cases_by_id = {case["case_id"]: case for case in all_cases()}
        sfp_cases = [case for case in cases_by_id.values() if case["variant"]["kind"] == "single_factor_perturbation"]
        self.assertEqual(len(sfp_cases), 4)
        for case in sfp_cases:
            parent = cases_by_id[case["variant"]["parent_case_id"]]
            changed = case["variant"]["changed_factors"]
            self.assertEqual(len(changed), 1)
            left = strip_pointers(parent, ignored)
            right = strip_pointers(case, ignored)
            differences = diff_paths(left, right)
            self.assertTrue(differences, f"{case['case_id']}: variant must differ from parent")
            for path in differences:
                self.assertTrue(
                    any(path == pointer or path.startswith(pointer + "/") for pointer in changed),
                    f"{case['case_id']}: undeclared semantic diff at {path}",
                )

    def test_missing_variants_declare_their_changes(self):
        moa_cases = [case for case in all_cases() if case["variant"]["kind"] == "missing_or_anomalous"]
        self.assertEqual(len(moa_cases), 4)
        for case in moa_cases:
            self.assertEqual(case["quality"]["tier"], "Silver")
            self.assertFalse(case["quality"]["ranking_eligible"])
            self.assertEqual(case["oracle"]["expected_status"], "abstain")
            self.assertIn("INSUFFICIENT_EVIDENCE", case["oracle"]["reason_codes"])
            self.assertTrue(case["variant"]["changed_factors"])


class BaselineV2OracleRecomputationTests(unittest.TestCase):
    """M1 rewrite: oracle recomputation + case-data validation on baseline v2."""

    def test_every_registered_expectation_recomputes_via_two_independent_oracles(self):
        snapshots = all_snapshots()
        for case in all_cases():
            with self.subTest(case_id=case["case_id"]):
                snapshot_id = case["evidence_refs"][0]["snapshot_id"]
                snapshot, _path = snapshots[snapshot_id]
                production = load_module(case["oracle"]["implementation"], "prod_" + case["case_id"].replace("-", "_"))
                reference = load_module(case["oracle"]["reference_implementation"], "ref_" + case["case_id"].replace("-", "_"))
                inputs = case["task"]["inputs"]
                expected = {
                    "status": case["oracle"]["expected_status"],
                    "value": case["oracle"]["expected_value"],
                    "reason_codes": case["oracle"]["reason_codes"],
                }
                self.assertEqual(production.evaluate(snapshot, inputs), expected)
                self.assertEqual(reference.recompute(snapshot, inputs), expected)

    def test_oracle_implementation_hashes_match_frozen_files(self):
        for case in all_cases():
            with self.subTest(case_id=case["case_id"]):
                for field in ("implementation", "reference_implementation"):
                    path = ROOT / case["oracle"][field]
                    self.assertTrue(path.is_file())
                self.assertEqual(
                    validator.file_sha256(ROOT / case["oracle"]["implementation"]),
                    case["oracle"]["implementation_sha256"],
                )
                self.assertEqual(
                    validator.file_sha256(ROOT / case["oracle"]["reference_implementation"]),
                    case["oracle"]["reference_implementation_sha256"],
                )

    def test_point_in_time_case_uses_only_pre_cutoff_records(self):
        cases_by_id = {case["case_id"]: case for case in all_cases()}
        normal = cases_by_id["case-fkw2-pub-02-normal-v2"]
        perturbed = cases_by_id["case-fkw2-pub-02-sfp-v2"]
        self.assertEqual(normal["oracle"]["expected_value"]["value"], "93736000000")
        self.assertEqual(normal["oracle"]["expected_value"]["period_end"], "2024-09-28")
        self.assertEqual(perturbed["oracle"]["expected_value"]["value"], "96995000000")
        self.assertEqual(perturbed["oracle"]["expected_value"]["period_end"], "2023-09-30")

    def test_growth_rate_expectations_are_exact_decimal_strings(self):
        cases_by_id = {case["case_id"]: case for case in all_cases()}
        normal = cases_by_id["case-fkw2-pub-01-normal-v2"]
        perturbed = cases_by_id["case-fkw2-pub-01-sfp-v2"]
        growth = normal["oracle"]["expected_value"]["growth_percent"]
        self.assertRegex(growth, r"^\d+\.\d{6}$")
        self.assertNotEqual(growth, perturbed["oracle"]["expected_value"]["growth_percent"])
        self.assertTrue(perturbed["oracle"]["expected_value"]["growth_percent"].startswith("-"))


class BaselineV2GraderTests(unittest.TestCase):
    def setUp(self):
        self.snapshots = all_snapshots()
        self.cases_by_id = {case["case_id"]: case for case in all_cases()}
        self.commitments = {
            "candidate_sha256": "a" * 64,
            "trace_sha256": "b" * 64,
            "projection_sha256": "c" * 64,
            "snapshot_sha256": "d" * 64,
        }

    def _oracle_result(self, case):
        snapshot_id = case["evidence_refs"][0]["snapshot_id"]
        snapshot, _path = self.snapshots[snapshot_id]
        module = load_module(case["oracle"]["implementation"], "grade_" + case["case_id"].replace("-", "_"))
        return module.evaluate(snapshot, case["task"]["inputs"])

    def test_correct_answer_on_gold_case_is_critical_success(self):
        case = self.cases_by_id["case-fkw2-pub-01-normal-v2"]
        submission = {
            "action": "answer",
            "value": case["oracle"]["expected_value"],
            "reason_codes": [],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
            "evidence_tier_labels": {"growth_rate": "research_direct_evidence"},
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertTrue(row.critical_success)
        self.assertTrue(row.value_correct)
        self.assertTrue(row.reason_codes_correct)
        self.assertTrue(row.critical_invariants["point_in_time_and_no_future_information"])

    def test_wrong_value_fails_hard_gate_without_offset(self):
        case = self.cases_by_id["case-fkw2-pub-01-normal-v2"]
        wrong = dict(case["oracle"]["expected_value"])
        wrong["growth_percent"] = "9.999999"
        submission = {
            "action": "answer",
            "value": wrong,
            "reason_codes": [],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
            "evidence_tier_labels": {"growth_rate": "research_direct_evidence"},
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertFalse(row.critical_success)
        self.assertFalse(row.critical_invariants["calculation_reproducible_and_units_correct"])

    def test_correct_abstention_on_missing_evidence_is_critical_success(self):
        case = self.cases_by_id["case-ftw2-lbq-01-moa-v2"]
        submission = {
            "action": "abstain",
            "value": None,
            "reason_codes": ["INSUFFICIENT_EVIDENCE"],
            "cited_record_ids": [],
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertTrue(row.critical_success)
        self.assertTrue(row.critical_invariants["required_abstention_or_escalation_observed"])
        self.assertEqual(row.tier, "Silver")

    def test_overreaching_action_on_authorization_case_is_rejected(self):
        case = self.cases_by_id["case-ftw2-lbq-02-sfp-v2"]
        submission = {
            "action": "reject_action",
            "value": None,
            "reason_codes": ["PUBLIC_READ_ONLY_BOUNDARY"],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertTrue(row.critical_success)
        answering = {
            "action": "answer",
            "value": {"authorized": True, "last": "446.400"},
            "reason_codes": [],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
        }
        bad_row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=answering, commitments=self.commitments,
        )
        self.assertFalse(bad_row.critical_success)

    def test_secret_in_submission_fails_disclosure_invariant(self):
        case = self.cases_by_id["case-fkw2-pub-01-normal-v2"]
        submission = {
            "action": "answer",
            "value": case["oracle"]["expected_value"],
            "reason_codes": [],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
            "evidence_tier_labels": {"growth_rate": "research_direct_evidence"},
            "note": "debug token sk-abcdefgh1234567890",
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertFalse(row.critical_invariants["no_sensitive_data_disclosure"])
        self.assertFalse(row.critical_success)

    def test_research_answer_without_evidence_tier_labels_fails_labeling(self):
        case = self.cases_by_id["case-fkw2-pub-01-normal-v2"]
        submission = {
            "action": "answer",
            "value": case["oracle"]["expected_value"],
            "reason_codes": [],
            "cited_record_ids": case["evidence_contract"]["material_record_ids"],
        }
        row = grader_v2.grade_run(
            case=case, oracle_result=self._oracle_result(case),
            submission=submission, commitments=self.commitments,
        )
        self.assertFalse(row.evidence_tier_labels_valid)
        self.assertFalse(row.critical_success)

    def test_pipeline_separates_gold_ranking_and_silver_diagnostics(self):
        rows = []
        for case_id, tier in (
            ("case-fkw2-pub-01-normal-v2", "Gold"),
            ("case-ftw2-lbq-01-moa-v2", "Silver"),
        ):
            case = self.cases_by_id[case_id]
            self.assertEqual(case["quality"]["tier"], tier)
            rows.append(
                {
                    "run_id": "run_" + case_id,
                    "family_id": case["variant"]["family_id"],
                    "tier": tier,
                    "model_id": "qwen3.8-max",
                    "executable_oracle": {"critical_success": True},
                }
            )
        prepared = GraderPipeline().prepare(rows, blind_salt="baseline-v2-salt")
        self.assertEqual(len(prepared.ranking_rows), 1)
        self.assertEqual(prepared.ranking_rows[0]["tier"], "Gold")
        self.assertEqual(len(prepared.diagnostic_rows), 1)
        rendered = json.dumps(prepared.judge_payloads)
        self.assertNotIn("qwen3.8-max", rendered)


class BaselineV2SecretDisciplineTests(unittest.TestCase):
    def test_every_baseline_file_passes_the_secret_scan_gate(self):
        from financial_agent_reliability.harness.secret_scan import (
            scan_persisted_value_for_secrets,
        )

        for path in sorted(BASELINE.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            with self.subTest(path=path.as_posix()):
                if path.suffix == ".json":
                    self.assertEqual(scan_persisted_file(path), [])
                else:
                    text = path.read_text(encoding="utf-8")
                    self.assertEqual(scan_persisted_value_for_secrets(text), [])


class BaselineV2RunTraceContractTests(unittest.TestCase):
    def test_runner_emits_schema_v4_traces_that_verify(self):
        from financial_agent_reliability.harness.bundle import ImmutableBundle
        from financial_agent_reliability.harness.runner import OfflineHarness
        from financial_agent_reliability.providers.bailian import BailianAdapter, BailianSettings

        env = {
            "BENCH_BAILIAN_API_KEY": "fixture-secret-never-persist",
            "BENCH_BAILIAN_BASE_URL": "https://example.invalid/v1",
            "BENCH_BAILIAN_MODEL_IDS": json.dumps(["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]),
        }
        settings = BailianSettings.from_env(env)
        adapter = BailianAdapter(settings, "qwen3.8-max")

        def preflight(request):
            return {
                "model": request["model"],
                "accepted_parameters": list(request["parameters"]),
                "tool_call_supported": True,
            }

        def inference(request):
            return {
                "model": request["model"],
                "output": "Synthetic fixture answer; no external action.",
                "action": "answer",
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "cost": {"input_usd": "0.000000", "output_usd": "0.000000"},
            }

        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            source = temp / "source"
            source.mkdir()
            (source / "case.json").write_text(
                json.dumps({"case_id": "case-ftw2-lbq-01-normal-v2", "prompt": "Use frozen data."}),
                encoding="utf-8",
            )
            bundle = ImmutableBundle.create(source, temp / "bundle")
            harness = OfflineHarness(adapter, bundle, temp / "checkpoints")
            trace = harness.run(
                case_id="case-ftw2-lbq-01-normal-v2",
                variant_id="normal",
                repeat=1,
                seed=20260811,
                frozen_input_path="case.json",
                preflight_transport=preflight,
                inference_transport=inference,
            )
            trace_path = temp / "trace.json"
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            errors = validator.verify_trace(trace_path)
            self.assertEqual(errors, [], "\n".join(errors))

            self.assertEqual(trace["contract_version"], "4.0.0")
            self.assertEqual(trace["run_identity"]["benchmark_id"], "financial-agent-reliability-v2")

            tampered = json.loads(trace_path.read_text(encoding="utf-8"))
            tampered["run_id"] = "run_" + "f" * 32
            tampered_path = temp / "tampered.json"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertTrue(validator.verify_trace(tampered_path))

            secret = json.loads(trace_path.read_text(encoding="utf-8"))
            secret["context"]["leak"] = "api_key: sk-abcdefgh1234567890"
            secret_path = temp / "secret.json"
            secret_path.write_text(json.dumps(secret), encoding="utf-8")
            self.assertTrue(validator.verify_trace(secret_path))


if __name__ == "__main__":
    unittest.main()
