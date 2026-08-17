"""复盘工具链离线单元测试(PER-322,F9/F7/F3 修复项)。

对核心复盘逻辑(run_checks / summary_check / report_level / write_evidence)
用**合成 bundle** 覆盖,不依赖 runs//evidence/ 历史产物,干净检出下测试面
不坍缩。全部离线、无网络、无模型调用。
"""

from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import unittest
from typing import Any

import financial_agent_reliability.retrospective.report as report_mod
from financial_agent_reliability.retrospective.engine import (
    _governance_check,
    _missing_governance_documents,
)
from financial_agent_reliability.retrospective.hashing import (
    content_sha256,
    file_sha256,
)
from financial_agent_reliability.retrospective.model import (
    DEGRADED,
    FAIL,
    NA,
    PASS,
)
from financial_agent_reliability.retrospective.registry import BatchRecord
from financial_agent_reliability.retrospective.run_checks import (
    ZERO_SHA,
    RunsCheck,
    _anchor_checks,
    _checkpoint_chain_events,
    _verify_v35_bundle_pins,
)
from financial_agent_reliability.retrospective.summary_check import (
    _block,
    _recomputed_counts,
    check_summary_recompute,
)


def _write(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _shim_batch(directory: pathlib.Path, batch_id: str = "synthetic-v1") -> BatchRecord:
    class _Shim(BatchRecord):
        @property
        def directory(self) -> pathlib.Path:  # type: ignore[override]
            return directory

    return _Shim(batch_id=batch_id, batch_type="acceptance", dir_name="batch")


def _empty_runs(**overrides: Any) -> RunsCheck:
    base: dict[str, Any] = {
        "records": (),
        "run_errors": (),
        "frozen_input_errors": (),
        "preflight_errors": (),
        "authorization_errors": (),
        "invalidation_notes": (),
        "anchor_problems": (),
    }
    base.update(overrides)
    return RunsCheck(**base)


class CheckpointChainReplayTest(unittest.TestCase):
    """run_checks._checkpoint_chain_events:哈希链重放(合成链)。"""

    def _chain_text(self, run_id: str, events: int) -> str:
        lines = []
        previous = ZERO_SHA
        for offset in range(events):
            event = {
                "run_id": run_id,
                "offset": offset,
                "previous_event_sha256": previous,
                "event_type": "synthetic",
                "payload": {"i": offset},
            }
            sha = content_sha256(event)
            event["event_sha256"] = sha
            lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
            previous = sha
        return "\n".join(lines) + "\n"

    def test_valid_chain_replays_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "run_1.jsonl"
            path.write_text(self._chain_text("run_1", 3), encoding="utf-8")
            count, errors = _checkpoint_chain_events(path, "run_1")
            self.assertEqual(count, 3)
            self.assertEqual(errors, [])

    def test_broken_previous_link_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "run_1.jsonl"
            lines = self._chain_text("run_1", 2).splitlines()
            event = json.loads(lines[1])
            event["previous_event_sha256"] = "f" * 64  # 断链
            lines[1] = json.dumps(event, ensure_ascii=False, sort_keys=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            count, errors = _checkpoint_chain_events(path, "run_1")
            self.assertEqual(count, 2)
            self.assertTrue(any("chain broken at offset 1" in e for e in errors), errors)

    def test_missing_checkpoint_file_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            count, errors = _checkpoint_chain_events(
                pathlib.Path(tmp) / "absent.jsonl", "run_1"
            )
            self.assertEqual(count, 0)
            self.assertEqual(errors, ["run_1: checkpoint missing"])


class AnchorChecksTest(unittest.TestCase):
    """run_checks._anchor_checks:链锚回验(合成 trace/grader/候选/投影)。"""

    def setUp(self) -> None:
        import financial_agent_reliability.retrospective.run_checks as mod

        self._mod = mod
        self._original_root = mod.REPO_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        mod.REPO_ROOT = self.root

    def tearDown(self) -> None:
        self._mod.REPO_ROOT = self._original_root
        self._tmp.cleanup()

    def _build(self) -> tuple[pathlib.Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        batch_dir = self.root / "batch"
        config_path = batch_dir / "config.json"
        _write(config_path, {"harness": "synthetic"})
        projection = {"projection": True}
        snapshot = {"snapshot": True}
        _write(self.root / "snap" / "projection.json", projection)
        _write(self.root / "snap" / "snapshot.json", snapshot)
        candidate = {"answer": 42}
        trace = {
            "run_identity": {
                "harness_config_sha256": file_sha256(config_path),
                "plan_core_sha256": "ab" * 32,
                "seed": 7,
            },
            "result": {"candidate_output_sha256": content_sha256(candidate)},
        }
        grader = {
            "commitments": {
                "candidate_sha256": content_sha256(candidate),
                "trace_sha256": content_sha256(trace),
                "projection_sha256": content_sha256(projection),
                "snapshot_sha256": content_sha256(snapshot),
            }
        }
        _write(batch_dir / "traces" / "run_1.json", trace)
        _write(batch_dir / "graders" / "run_1.json", grader)
        _write(batch_dir / "candidates" / "run_1.json", candidate)
        row = {"run_id": "run_1", "seed": 7}
        task = {
            "projection_path": "snap/projection.json",
            "snapshot_path": "snap/snapshot.json",
            "case_id": "case-1",
        }
        plan = {"plan_core_sha256": "ab" * 32}
        return batch_dir, row, task, plan

    def test_intact_anchors_verify_clean(self) -> None:
        batch_dir, row, task, plan = self._build()
        problems = _anchor_checks(batch_dir, row, task, plan, batch_dir / "config.json")
        self.assertEqual(problems, [])

    def test_candidate_tamper_breaks_two_anchors(self) -> None:
        batch_dir, row, task, plan = self._build()
        _write(batch_dir / "candidates" / "run_1.json", {"answer": 43})  # 篡改候选
        problems = _anchor_checks(batch_dir, row, task, plan, batch_dir / "config.json")
        self.assertTrue(
            any("candidate_output_sha256 anchor broken" in p for p in problems), problems
        )
        self.assertTrue(
            any("grader commitment candidate_sha256 broken" in p for p in problems), problems
        )

    def test_missing_trace_reported(self) -> None:
        batch_dir = self.root / "empty-batch"
        batch_dir.mkdir(parents=True, exist_ok=True)
        problems = _anchor_checks(
            batch_dir,
            {"run_id": "run_1", "seed": 1},
            {"projection_path": "p.json", "snapshot_path": "s.json"},
            {},
            None,
        )
        self.assertEqual(problems, ["run_1: trace missing"])


class V35BundlePinCheckTest(unittest.TestCase):
    """run_checks._verify_v35_bundle_pins(F2:v3.5 bundle 钉住校验不再空转)。"""

    def setUp(self) -> None:
        import financial_agent_reliability.retrospective.run_checks as mod

        self._mod = mod
        self._original_root = mod.REPO_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        mod.REPO_ROOT = self.root

    def tearDown(self) -> None:
        self._mod.REPO_ROOT = self._original_root
        self._tmp.cleanup()

    def _batch_with_pins(self) -> BatchRecord:
        batch_dir = self.root / "batch"
        pinned = self.root / "contracts" / "pinned.json"
        _write(pinned, {"pinned": True})
        _write(
            batch_dir / "stage3_acceptance_contracts.frozen.v9.9.json",
            {
                "contract_version": "9.9.0",
                "artifacts": [
                    {"path": "contracts/pinned.json", "sha256": file_sha256(pinned)},
                ],
            },
        )
        return _shim_batch(batch_dir, batch_id="acceptance-v9.9")

    def test_all_pins_verify_clean(self) -> None:
        self.assertEqual(_verify_v35_bundle_pins(self._batch_with_pins()), ())

    def test_pin_drift_detected(self) -> None:
        batch = self._batch_with_pins()
        _write(self.root / "contracts" / "pinned.json", {"pinned": "tampered"})
        errors = _verify_v35_bundle_pins(batch)
        self.assertEqual(errors, ("artifact drift:contracts/pinned.json",))

    def test_missing_bundle_means_no_pins(self) -> None:
        batch = _shim_batch(self.root / "no-bundle-dir", batch_id="acceptance-v9.9")
        self.assertEqual(_verify_v35_bundle_pins(batch), ())


class GovernanceDetectionTest(unittest.TestCase):
    """engine._missing_governance_documents / _governance_check(F2:M1 由检测导出)。"""

    def test_missing_documents_derive_m1_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = _shim_batch(pathlib.Path(tmp), batch_id="acceptance-v9.9")
            self.assertEqual(
                _missing_governance_documents(batch),
                ("authorization.run", "preflight"),
            )
            result = _governance_check(batch, _empty_runs())
            self.assertEqual(result.status, DEGRADED)
            self.assertEqual(
                result.details,
                ("M1:v9.9 授权记录缺失(authorization.run/preflight 均无)",),
            )
            self.assertTrue(result.metrics["downgrade_affects_conclusion"])

    def test_present_documents_pass_without_m1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            _write(directory / "preflight.json", {"decision": "passed_3_of_3"})
            _write(directory / "authorization.run.json", {"authorized": True})
            batch = _shim_batch(directory, batch_id="acceptance-v9.9")
            self.assertEqual(_missing_governance_documents(batch), ())
            result = _governance_check(batch, _empty_runs())
            self.assertEqual(result.status, PASS)
            self.assertEqual(result.details, ("governance artifacts verify",))
            self.assertFalse(result.metrics["downgrade_affects_conclusion"])

    def test_frozen_input_errors_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            _write(directory / "preflight.json", {})
            _write(directory / "authorization.run.json", {})
            batch = _shim_batch(directory)
            runs = _empty_runs(frozen_input_errors=("artifact drift:x",))
            result = _governance_check(batch, runs)
            self.assertEqual(result.status, FAIL)


class SummaryRecomputeSyntheticTest(unittest.TestCase):
    """summary_check.check_summary_recompute(合成 bundle,不依赖历史产物)。"""

    RECORDS = (
        {
            "run_id": "r1", "model_id": "m1", "repeat": 1, "status": "succeeded",
            "structured_output_valid": True, "value_semantic_correct": True,
            "all_applicable_checks_passed": True, "provider_attempts": 1,
            "retries_used": 0, "provider_failures": 0, "total_tokens": 100,
            "duration_ms": 500, "failed_checks": [], "checkpoint_events": 3,
            "identity_valid": True, "fallback_attempts": 0,
            "real_side_effects": False, "terminal_state_safe": True,
        },
        {
            "run_id": "r2", "model_id": "m2", "repeat": 1, "status": "succeeded",
            "structured_output_valid": True, "value_semantic_correct": False,
            "all_applicable_checks_passed": True, "provider_attempts": 2,
            "retries_used": 1, "provider_failures": 0, "total_tokens": 80,
            "duration_ms": 300, "failed_checks": [], "checkpoint_events": 2,
            "identity_valid": True, "fallback_attempts": 0,
            "real_side_effects": False, "terminal_state_safe": True,
        },
    )

    def _persisted_summary(self) -> dict[str, Any]:
        return {
            "records": [dict(record) for record in self.RECORDS],
            "counts": _recomputed_counts(
                self.RECORDS, planned=2, invalidated=0, run_errors=()
            ),
            "by_model": {
                model: _block([r for r in self.RECORDS if r["model_id"] == model])
                for model in ("m1", "m2")
            },
        }

    def test_synthetic_summary_recomputes_bit_equal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            _write(directory / "summary.json", self._persisted_summary())
            runs = _empty_runs(records=self.RECORDS, metrics={"planned_scope": 2})
            result = check_summary_recompute(_shim_batch(directory), runs)
            self.assertEqual(result.status, PASS, result.details)
            self.assertEqual(result.metrics["mismatched_fields"], 0)

    def test_tampered_count_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            summary = self._persisted_summary()
            summary["counts"]["planned"] = 99  # 篡改计数
            _write(directory / "summary.json", summary)
            runs = _empty_runs(records=self.RECORDS, metrics={"planned_scope": 2})
            result = check_summary_recompute(_shim_batch(directory), runs)
            self.assertEqual(result.status, FAIL)
            self.assertTrue(
                any("counts.planned" in d for d in result.details), result.details
            )

    def test_record_level_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            summary = self._persisted_summary()
            summary["records"][0]["total_tokens"] = 1  # 记录级漂移
            _write(directory / "summary.json", summary)
            runs = _empty_runs(records=self.RECORDS, metrics={"planned_scope": 2})
            result = check_summary_recompute(_shim_batch(directory), runs)
            self.assertEqual(result.status, FAIL)
            self.assertTrue(any("记录不一致" in d for d in result.details), result.details)

    def test_non_acceptance_batch_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = _shim_batch(pathlib.Path(tmp), batch_id="smoke-x")
            object.__setattr__(batch, "batch_type", "smoke")
            result = check_summary_recompute(batch, _empty_runs())
            self.assertEqual(result.status, NA)

    def test_no_records_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = check_summary_recompute(_shim_batch(pathlib.Path(tmp)), _empty_runs())
            self.assertEqual(result.status, FAIL)


class ReportLevelPureTest(unittest.TestCase):
    """report_level 纯函数(F9:统计比对与排名导出可离线测试)。"""

    def _aligned(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        score = {
            "models": {"a": {"CSR": {"estimate": 0.9}}},
            "pairwise_csr": {"a_vs_b": 0.1},
            "leader_gates": {"gate": False},
            "ranking_reliable": False,
            "provisional_leader": "a",
        }
        per32 = copy.deepcopy(score)
        machine = {
            "ranking_reliable": False,
            "leader_gates": {"gate": False},
            "pairwise_csr": {"a_vs_b": 0.1},
            "provisional_leader_point_estimate": {"model": "a"},
        }
        return score, per32, machine

    def test_aligned_statistics_no_problems(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            compare_report_statistics,
        )

        score, per32, machine = self._aligned()
        self.assertEqual(compare_report_statistics(score, per32, machine), [])

    def test_signed_statistics_divergence_flagged(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            compare_report_statistics,
        )

        score, per32, machine = self._aligned()
        score["ranking_reliable"] = True
        problems = compare_report_statistics(score, per32, machine)
        self.assertIn("recomputed ranking_reliable != PER-32 signed statistics", problems)
        self.assertIn("published ranking_reliable != recomputed", problems)

    def test_published_leader_divergence_flagged(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            compare_report_statistics,
        )

        score, per32, machine = self._aligned()
        machine["provisional_leader_point_estimate"]["model"] = "b"
        problems = compare_report_statistics(score, per32, machine)
        self.assertIn("published provisional leader != recomputed", problems)

    def test_ranking_entries_ordered_and_ranked(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            ranking_entries,
        )

        score = {
            "models": {
                "alpha": {
                    "CSR": {"estimate": 0.90, "ci95": [0.8, 0.95]},
                    "pass^3": {"estimate": 0.7},
                    "correct_abstention_rate": {"estimate": 0.5},
                    "high_loss_error_rate_per_1000": {"estimate": 1.0},
                    "L4_events": {"estimate": 0},
                    "bootstrap_top_probability": 0.6,
                },
                "beta": {"CSR": {"estimate": 0.95, "ci95": [0.9, 0.98]}},
                "gamma": {"CSR": {"estimate": None}},
            }
        }
        entries = ranking_entries(score)
        self.assertEqual([e["model"] for e in entries], ["beta", "alpha", "gamma"])
        self.assertEqual([e["gold_csr_rank"] for e in entries], [1, 2, 3])
        self.assertEqual(entries[1]["gold_csr_estimate"], 0.90)
        self.assertEqual(entries[1]["pass3_estimate"], 0.7)
        self.assertEqual(entries[1]["bootstrap_top_probability"], 0.6)
        self.assertIsNone(entries[2]["gold_csr_estimate"])

    def test_ranking_entries_tie_broken_by_model_name(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            ranking_entries,
        )

        score = {
            "models": {
                "zeta": {"CSR": {"estimate": 0.5}},
                "alpha": {"CSR": {"estimate": 0.5}},
            }
        }
        entries = ranking_entries(score)
        self.assertEqual([e["model"] for e in entries], ["alpha", "zeta"])


class EvidenceOutputPathTest(unittest.TestCase):
    """report.resolve_evidence_output_dir(F7:路径策略校验 + resolve)。"""

    def test_default_is_docs_retrospectives(self) -> None:
        self.assertEqual(report_mod.resolve_evidence_output_dir(None), report_mod.OUTPUT_DIR)

    def test_relative_path_resolves_against_repo_root(self) -> None:
        resolved = report_mod.resolve_evidence_output_dir("docs/retrospectives-x")
        self.assertEqual(resolved, (report_mod.REPO_ROOT / "docs/retrospectives-x").resolve())

    def test_outside_repo_rejected_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                report_mod.resolve_evidence_output_dir(tmp)
            self.assertIn("must stay inside the repository", str(ctx.exception))

    def test_relative_escape_rejected(self) -> None:
        with self.assertRaises(ValueError):
            report_mod.resolve_evidence_output_dir("../retro-evidence-escape")

    def test_cli_reports_path_policy_violation(self) -> None:
        import financial_agent_reliability.retrospective.cli as cli_mod

        original = cli_mod.write_evidence

        def _reject(_output_dir):
            raise ValueError("evidence --out must stay inside the repository")

        cli_mod.write_evidence = _reject
        try:
            exit_code = cli_mod.main(["evidence", "--out", "/tmp/elsewhere"])
        finally:
            cli_mod.write_evidence = original
        self.assertEqual(exit_code, 2)


SYNTHETIC_INDEX: dict[str, Any] = {
    "contract_type": "stage3_historical_run_retrospective_index",
    "index_version": "1.0.0",
    "criteria_document": report_mod.CRITERIA_PATH,
    "criteria_version": "1.0.0",
    "gap_report": report_mod.GAP_REPORT_PATH,
    "git_commit": "synthetic-anchor",
    "offline": True,
    "runs_integrity_basis": report_mod.RUNS_INTEGRITY_BASIS,
    "batches": [
        {
            "batch_id": "synthetic-batch",
            "batch_type": "acceptance",
            "directory": "runs/stage3/synthetic-batch",
            "contract_version": "9.9.0",
            "verdict": "traceable",
            "verdict_basis": "适用判定项全部通过",
            "scope_note": "合成批次",
            "labels": [],
            "checks": [],
            "run_statistics": {},
        }
    ],
    "verdict_counts": {"traceable": 1},
    "labels_registry": [
        {
            "code": "T1",
            "severity": "low",
            "affected_batches": ["synthetic-batch"],
            "summary": "合成标注",
            "consequence": "无",
            "remediation": "无",
        }
    ],
}


class WriteEvidenceOfflineTest(unittest.TestCase):
    """report.write_evidence(F9:落盘逻辑离线测试 + F7 输出目录策略)。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name).resolve()
        self._originals = {
            name: getattr(report_mod, name)
            for name in (
                "REPO_ROOT",
                "BATCHES",
                "run_full_retrospective",
                "build_lineage_index",
                "build_archive_map",
                "export_ranking",
                "check_grader_bundle_freeze",
                "check_report_bundle_freeze",
                "recompute_report_level",
            )
        }
        report_mod.REPO_ROOT = self.base
        report_mod.BATCHES = ()
        report_mod.run_full_retrospective = lambda: copy.deepcopy(SYNTHETIC_INDEX)
        report_mod.build_lineage_index = lambda: {"batches": [{"batch_id": "synthetic-batch"}]}
        report_mod.build_archive_map = lambda: {"all_ok": True, "pairs": []}
        report_mod.export_ranking = lambda: {"ranking_reliable": False}
        report_mod.check_grader_bundle_freeze = lambda: {"ok": True, "problems": []}
        report_mod.check_report_bundle_freeze = lambda: {"ok": True, "problems": []}
        report_mod.recompute_report_level = lambda: {
            "ok": True,
            "problems": [],
            "sealed_rows": 1,
            "provisional_leader": None,
            "ranking_reliable": False,
        }

    def tearDown(self) -> None:
        for name, value in self._originals.items():
            setattr(report_mod, name, value)
        self._tmp.cleanup()

    def test_writes_full_layout_with_relative_paths(self) -> None:
        out = self.base / "docs" / "retrospectives"
        written = report_mod.write_evidence(out)
        self.assertEqual(
            written["index"], "docs/retrospectives/retrospective-index.v1.json"
        )
        self.assertEqual(
            written["batch:synthetic-batch"],
            "docs/retrospectives/batches/synthetic-batch.v1.json",
        )
        for relative in written.values():
            self.assertTrue((self.base / relative).is_file(), relative)
        index = json.loads((out / "retrospective-index.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(index["git_commit"], "synthetic-anchor")
        self.assertEqual(index["verdict_counts"], {"traceable": 1})
        # P1:索引必须携带 runs/ 完整性依据表述。
        self.assertIn("bundle manifest", index["runs_integrity_basis"])

    def test_relative_out_resolves_against_repo_root(self) -> None:
        written = report_mod.write_evidence("docs/retrospectives-rel")
        self.assertTrue(
            (self.base / "docs" / "retrospectives-rel" / "retrospective-report.v1.md").is_file()
        )
        self.assertEqual(
            written["report"], "docs/retrospectives-rel/retrospective-report.v1.md"
        )

    def test_outside_out_rejected_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError):
                report_mod.write_evidence(outside)

    def test_report_markdown_carries_p1_statement(self) -> None:
        out = self.base / "docs" / "retrospectives"
        report_mod.write_evidence(out)
        report = (out / "retrospective-report.v1.md").read_text(encoding="utf-8")
        self.assertIn("runs/ 完整性依据", report)
        self.assertIn("git 零改动验证仅对 tracked 目录主张", report)
        self.assertIn("| `synthetic-batch` |", report)


class InvalidationDuplicateReportTest(unittest.TestCase):
    """invalidation_check(F3:重复 run_id 检出不再被覆盖丢弃)。"""

    def test_duplicate_run_ids_flagged(self) -> None:
        from financial_agent_reliability.retrospective.invalidation_check import (
            reconcile_invalidations,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _write(
                root / "invalidated-runs.json",
                {
                    "entries": [
                        {"run_id": "run_x", "replaced_or_reexecuted": False},
                        {"run_id": "run_x", "replaced_or_reexecuted": False},
                    ],
                    "report_sha256": "irrelevant-for-this-check",
                },
            )
            result = reconcile_invalidations(_shim_batch(root))
            self.assertFalse(result["ok"])
            self.assertIn(
                "invalidation report has duplicate run_ids", result["problems"]
            )

    def test_clean_report_stays_ok(self) -> None:
        from financial_agent_reliability.retrospective.invalidation_check import (
            reconcile_invalidations,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _write(
                root / "invalidated-runs.json",
                {
                    "entries": [{"run_id": "run_x", "replaced_or_reexecuted": False}],
                    "report_sha256": "irrelevant-for-this-check",
                },
            )
            result = reconcile_invalidations(_shim_batch(root))
            self.assertTrue(result["ok"], result.get("problems"))
            self.assertEqual(result["problems"], [])


if __name__ == "__main__":
    unittest.main()
