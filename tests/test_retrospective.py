"""复盘工具链单元测试(PER-319):合成 bundle、判定规则、推导件。"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from financial_agent_reliability.retrospective.hashing import (
    aggregate_sorted_pairs,
    case_content_sha256,
    content_sha256,
    detect_bundle_aggregate,
    file_sha256,
)
from financial_agent_reliability.retrospective.labels import (
    LABEL_BY_CODE,
    labels_for_batch,
)
from financial_agent_reliability.retrospective.manifest_check import (
    check_bundle_manifest,
    unregistered_files,
)
from financial_agent_reliability.retrospective.model import (
    DEGRADED,
    FAIL,
    PARTIALLY_TRACEABLE,
    PASS,
    TRACEABLE,
    UNTRACEABLE,
    CheckResult,
)
from financial_agent_reliability.retrospective.engine import _verdict_from_checks
from financial_agent_reliability.retrospective.summary_check import (
    _block,
    _recomputed_counts,
)


def _write(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_bundle(root: pathlib.Path, convention: str) -> pathlib.Path:
    """合成一个两种聚合口径之一的最小自证 bundle。"""
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "traces" / "run_a.json", {"run_id": "run_a", "value": 1})
    _write(root / "graders" / "run_a.json", {"run_id": "run_a", "checks": {}})
    artifacts = [
        {"path": "graders/run_a.json", "sha256": file_sha256(root / "graders" / "run_a.json")},
        {"path": "traces/run_a.json", "sha256": file_sha256(root / "traces" / "run_a.json")},
    ]
    if convention == "content_sha256":
        bundle_sha = content_sha256(artifacts)
    else:
        bundle_sha = aggregate_sorted_pairs(artifacts)
    _write(
        root / "bundle.manifest.json",
        {
            "contract_type": "test_evidence_bundle",
            "contract_version": "1.0.0",
            "status": "frozen",
            "bundle_sha256": bundle_sha,
            "artifacts": artifacts,
        },
    )
    return root


class HashingConventionTest(unittest.TestCase):
    def test_detect_content_sha256_convention(self) -> None:
        artifacts = [{"path": "a.json", "sha256": "0" * 64}]
        claimed = content_sha256(artifacts)
        self.assertEqual(detect_bundle_aggregate(artifacts, claimed), "content_sha256")

    def test_detect_sorted_pair_convention(self) -> None:
        artifacts = [
            {"path": "b.json", "sha256": "1" * 64},
            {"path": "a.json", "sha256": "0" * 64},
        ]
        claimed = aggregate_sorted_pairs(artifacts)
        self.assertEqual(
            detect_bundle_aggregate(artifacts, claimed), "sorted_pair_aggregate"
        )

    def test_detect_unknown_convention(self) -> None:
        artifacts = [{"path": "a.json", "sha256": "0" * 64}]
        self.assertIsNone(detect_bundle_aggregate(artifacts, "f" * 64))

    def test_case_content_hash_matches_frozen_validator(self) -> None:
        from contracts.validate_case_data import content_sha256 as frozen_c14n

        document = {
            "case_id": "case-x",
            "temporal": {"event_time": "2026-01-01T00:00:00Z"},
            "integrity": {"content_sha256": "placeholder", "algorithm": "financial-agent-c14n-json-v1"},
        }
        self.assertEqual(case_content_sha256(document), frozen_c14n(document))


class ManifestCheckTest(unittest.TestCase):
    def test_manifest_pass_both_conventions(self) -> None:
        for convention in ("content_sha256", "sorted_pair_aggregate"):
            with tempfile.TemporaryDirectory() as tmp:
                root = _build_bundle(pathlib.Path(tmp) / "bundle", convention)
                result = check_bundle_manifest(root)
                self.assertEqual(result.status, PASS, result.details)
                self.assertEqual(
                    result.metrics["bundle_sha256_convention"], convention
                )

    def test_hash_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_bundle(pathlib.Path(tmp) / "bundle", "content_sha256")
            tampered = root / "traces" / "run_a.json"
            tampered.write_text('{"run_id": "run_a", "value": 2}\n', encoding="utf-8")
            result = check_bundle_manifest(root)
            self.assertEqual(result.status, FAIL)
            self.assertTrue(any("hash drift" in d for d in result.details))

    def test_unregistered_file_is_pollution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_bundle(pathlib.Path(tmp) / "bundle", "content_sha256")
            (root / "stray.txt").write_text("pollution\n", encoding="utf-8")
            self.assertIn("stray.txt", unregistered_files(root, json.loads(
                (root / "bundle.manifest.json").read_text(encoding="utf-8")
            )))
            result = check_bundle_manifest(root)
            self.assertEqual(result.status, FAIL)
            self.assertTrue(any("pollution" in d for d in result.details))

    def test_missing_artifact_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_bundle(pathlib.Path(tmp) / "bundle", "content_sha256")
            (root / "graders" / "run_a.json").unlink()
            result = check_bundle_manifest(root)
            self.assertEqual(result.status, FAIL)
            self.assertEqual(result.metrics["missing"], 1)

    def test_absent_manifest_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = check_bundle_manifest(pathlib.Path(tmp))
            self.assertEqual(result.status, "not_applicable")


class VerdictRuleTest(unittest.TestCase):
    def _check(self, name: str, status: str, affects: bool = False) -> CheckResult:
        return CheckResult(
            name=name,
            status=status,
            metrics={"downgrade_affects_conclusion": affects},
        )

    def test_fail_is_untraceable(self) -> None:
        verdict, _ = _verdict_from_checks(
            (self._check("A1", PASS), self._check("B1", FAIL)), scope_acceptance=True
        )
        self.assertEqual(verdict, UNTRACEABLE)

    def test_affecting_degradation_is_partial(self) -> None:
        verdict, _ = _verdict_from_checks(
            (self._check("A1", PASS), self._check("A5", DEGRADED, affects=True)),
            scope_acceptance=True,
        )
        self.assertEqual(verdict, PARTIALLY_TRACEABLE)

    def test_annotation_only_degradation_stays_traceable(self) -> None:
        verdict, _ = _verdict_from_checks(
            (self._check("A1", PASS), self._check("A2", DEGRADED, affects=False)),
            scope_acceptance=True,
        )
        self.assertEqual(verdict, TRACEABLE)

    def test_all_pass_traceable(self) -> None:
        verdict, _ = _verdict_from_checks(
            (self._check("A1", PASS), self._check("B1", PASS)), scope_acceptance=True
        )
        self.assertEqual(verdict, TRACEABLE)


class LabelRegistryTest(unittest.TestCase):
    def test_v35_carries_m1(self) -> None:
        codes = {label.code for label in labels_for_batch("acceptance-v3.5")}
        self.assertIn("M1", codes)

    def test_protocol_batches_carry_h1(self) -> None:
        for batch_id in ("acceptance-v3", "acceptance-v3.4"):
            codes = {label.code for label in labels_for_batch(batch_id)}
            self.assertIn("H1", codes)

    def test_registry_complete_for_gap_report(self) -> None:
        expected = {"H1", "M1", "M3"} | {f"L{i}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14)}
        self.assertTrue(expected <= set(LABEL_BY_CODE))


class AggregationTest(unittest.TestCase):
    RECORDS = (
        {
            "run_id": "r1", "model_id": "m1", "repeat": 1, "status": "succeeded",
            "structured_output_valid": True, "value_semantic_correct": True,
            "all_applicable_checks_passed": True, "provider_attempts": 2,
            "retries_used": 0, "provider_failures": 0, "total_tokens": 100,
            "duration_ms": 500, "failed_checks": [], "checkpoint_events": 3,
            "identity_valid": True, "fallback_attempts": 0,
            "real_side_effects": False, "terminal_state_safe": True,
        },
        {
            "run_id": "r2", "model_id": "m1", "repeat": 1, "status": "candidate_failed",
            "structured_output_valid": False, "value_semantic_correct": None,
            "all_applicable_checks_passed": False, "provider_attempts": 1,
            "retries_used": 1, "provider_failures": 1, "total_tokens": 50,
            "duration_ms": 250, "failed_checks": ["structure_parsed"],
            "checkpoint_events": 2, "identity_valid": True, "fallback_attempts": 0,
            "real_side_effects": False, "terminal_state_safe": True,
        },
    )

    def test_block_counts(self) -> None:
        block = _block(self.RECORDS)
        self.assertEqual(block["runs"], 2)
        self.assertEqual(block["succeeded"], 1)
        self.assertEqual(block["candidate_failed"], 1)
        self.assertEqual(block["structured_results"], 1)
        self.assertEqual(block["value_semantic_correct"], 1)
        self.assertEqual(block["all_applicable_checks_passed"], 1)
        self.assertEqual(block["total_tokens"], 150)
        self.assertEqual(block["duration_ms"], 750)
        self.assertEqual(block["failed_check_frequency"], {"structure_parsed": 1})

    def test_recomputed_counts(self) -> None:
        counts = _recomputed_counts(
            self.RECORDS, planned=3, invalidated=1, run_errors=()
        )
        self.assertEqual(counts["planned"], 3)
        self.assertEqual(counts["frozen"], 2)
        self.assertEqual(counts["invalidated"], 1)
        self.assertEqual(counts["checkpoints"], 2)
        self.assertEqual(counts["checkpoint_events"], 5)
        self.assertEqual(counts["secret_leakage"], 0)
        self.assertEqual(counts["unsafe_or_real_side_effect"], 0)


class InvalidationReconTest(unittest.TestCase):
    def _batch_dir(self, tmp: pathlib.Path) -> pathlib.Path:
        root = tmp / "batch"
        root.mkdir(parents=True, exist_ok=True)
        events = [
            {"event": "run_invalidated", "run_id": "run_x"},
            {"event": "run_invalidated", "run_id": "run_x"},  # 断点续跑重复
            {"event": "run_invalidated", "run_id": "run_y"},
            {"event": "other", "run_id": "run_z"},
        ]
        (root / "driver-progress.jsonl").write_text(
            "\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8"
        )
        _write(
            root / "invalidated-runs.json",
            {
                "entries": [
                    {"run_id": "run_x", "replaced_or_reexecuted": False},
                    {"run_id": "run_y", "replaced_or_reexecuted": False},
                ],
                "report_sha256": "irrelevant-for-this-check",
            },
        )
        _write(
            root / "summary.json",
            {
                "counts": {"invalidated": 2},
                "invalidated_runs": [{"run_id": "run_x"}, {"run_id": "run_y"}],
            },
        )
        _write(
            root / "bundle.manifest.json",
            {
                "invalidated_run_ids": ["run_x", "run_y"],
                "invalidated_count": 2,
                "artifacts": [],
            },
        )
        return root

    def _shim(self, root: pathlib.Path):
        from financial_agent_reliability.retrospective.registry import BatchRecord

        class _Shim(BatchRecord):
            @property
            def directory(self) -> pathlib.Path:  # type: ignore[override]
                return root

        return _Shim(batch_id="test-batch", batch_type="acceptance", dir_name="batch")

    def test_dedup_and_reconcile_ok(self) -> None:
        from financial_agent_reliability.retrospective.invalidation_check import (
            reconcile_invalidations,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = self._batch_dir(pathlib.Path(tmp))
            result = reconcile_invalidations(self._shim(root))
            self.assertTrue(result["ok"], result.get("problems"))
            self.assertEqual(result["progress_events_total"], 3)
            self.assertEqual(result["progress_events_deduped"], 2)

    def test_report_only_violation_detected(self) -> None:
        from financial_agent_reliability.retrospective.invalidation_check import (
            reconcile_invalidations,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = self._batch_dir(pathlib.Path(tmp))
            (root / "traces").mkdir(parents=True, exist_ok=True)
            _write(root / "traces" / "run_x.json", {"run_id": "run_x"})
            result = reconcile_invalidations(self._shim(root))
            self.assertFalse(result["ok"])
            self.assertTrue(any("report-only" in p for p in result["problems"]))


class ArchiveMapTest(unittest.TestCase):
    def test_byte_equal_and_tamper_detection(self) -> None:
        from financial_agent_reliability.retrospective.archive_map import map_archive_pair

        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            canonical = base / "evidence" / "b1"
            archive = base / "archive" / "b1"
            _write(canonical / "summary.json", {"v": 1})
            _write(archive / "summary.json", {"v": 1})

            import financial_agent_reliability.retrospective.archive_map as mod
            original_root = mod.REPO_ROOT
            try:
                mod.REPO_ROOT = base
                result = map_archive_pair("archive/b1", "evidence/b1")
                self.assertTrue(result["ok"], result.get("problems"))
                self.assertEqual(result["byte_equal_with_canonical"], 1)

                _write(archive / "summary.json", {"v": 2})
                result = map_archive_pair("archive/b1", "evidence/b1")
                self.assertFalse(result["ok"])
            finally:
                mod.REPO_ROOT = original_root


if __name__ == "__main__":
    unittest.main()
