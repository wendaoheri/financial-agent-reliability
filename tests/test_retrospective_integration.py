"""复盘工具链集成测试(PER-319):对真实历史批次只读复盘。

依赖本机 ``runs/`` 与 ``evidence/`` 历史产物;产物缺失时跳过(如全新
浅检出)。全部只读、离线,不写任何目录。
"""

from __future__ import annotations

import json
import unittest

from financial_agent_reliability.retrospective.registry import (
    EVIDENCE_STAGE3,
    RUNS_STAGE3,
    batch_by_id,
)
from financial_agent_reliability.retrospective.engine import retrospect_batch
from financial_agent_reliability.retrospective.manifest_check import (
    check_bundle_manifest,
)
from financial_agent_reliability.retrospective.model import (
    PARTIALLY_TRACEABLE,
    TRACEABLE,
)


def _real_batches_available() -> bool:
    return (
        (EVIDENCE_STAGE3 / "acceptance-20260812-v3.8" / "bundle.manifest.json").is_file()
        and (RUNS_STAGE3 / "acceptance-20260813-v3.11" / "summary.json").is_file()
    )


@unittest.skipUnless(_real_batches_available(), "需要本机 runs//evidence/ 历史产物")
class RealBundleManifestTest(unittest.TestCase):
    def test_v38_evidence_bundle_integrity(self) -> None:
        batch = batch_by_id("acceptance-v3.8")
        result = check_bundle_manifest(batch.directory)
        self.assertEqual(result.status, "pass", result.details)
        self.assertEqual(result.metrics["artifacts"], 152)

    def test_v311_bundle_integrity(self) -> None:
        batch = batch_by_id("acceptance-v3.11")
        result = check_bundle_manifest(batch.directory)
        self.assertEqual(result.status, "pass", result.details)
        self.assertEqual(result.metrics["artifacts"], 2208)


@unittest.skipUnless(_real_batches_available(), "需要本机 runs//evidence/ 历史产物")
class RealBatchRetrospectiveTest(unittest.TestCase):
    """整批复盘:v3.5 部分可追溯(M1),v3.8/v3.11/coverage 可追溯。"""

    def test_v35_partial_with_m1(self) -> None:
        result = retrospect_batch(batch_by_id("acceptance-v3.5"))
        self.assertEqual(result.verdict, PARTIALLY_TRACEABLE)
        self.assertIn("M1", result.labels)
        self.assertEqual(result.run_statistics.get("runs"), 36)
        self.assertEqual(result.run_statistics.get("checkpoint_events"), 162)

    def test_v38_traceable_with_l7_annotation(self) -> None:
        result = retrospect_batch(batch_by_id("acceptance-v3.8"))
        self.assertEqual(result.verdict, TRACEABLE, result.verdict_basis)
        self.assertIn("L7", result.labels)
        self.assertNotIn("M1", result.labels)

    def test_v311_traceable(self) -> None:
        result = retrospect_batch(batch_by_id("acceptance-v3.11"))
        self.assertEqual(result.verdict, TRACEABLE, result.verdict_basis)
        self.assertEqual(result.run_statistics.get("runs"), 549)
        self.assertEqual(result.run_statistics.get("invalidated"), 1)

    def test_coverage_traceable(self) -> None:
        result = retrospect_batch(batch_by_id("coverage-v3.11.1"))
        self.assertEqual(result.verdict, TRACEABLE, result.verdict_basis)
        self.assertEqual(result.run_statistics.get("runs"), 1)

    def test_protocol_gate_scope(self) -> None:
        result = retrospect_batch(batch_by_id("acceptance-v3.4"))
        self.assertEqual(result.verdict, TRACEABLE)
        self.assertIn("H1", result.labels)
        self.assertIn("协议门", result.scope_note)


@unittest.skipUnless(_real_batches_available(), "需要本机 runs//evidence/ 历史产物")
class DerivedIndexTest(unittest.TestCase):
    def test_invalidation_recon_v310(self) -> None:
        from financial_agent_reliability.retrospective.invalidation_check import (
            reconcile_invalidations,
        )

        result = reconcile_invalidations(batch_by_id("acceptance-v3.10"))
        self.assertTrue(result["ok"], result.get("problems"))
        self.assertEqual(result["progress_events_total"], 55)
        self.assertEqual(result["progress_events_deduped"], 10)

    def test_archive_map_consistent(self) -> None:
        from financial_agent_reliability.retrospective.archive_map import (
            build_archive_map,
        )

        result = build_archive_map()
        self.assertTrue(result["all_ok"], result)

    def test_lineage_index_covers_all_batches(self) -> None:
        from financial_agent_reliability.retrospective.lineage import (
            build_lineage_index,
        )
        from financial_agent_reliability.retrospective.registry import BATCHES

        index = build_lineage_index()
        self.assertEqual(len(index["batches"]), len(BATCHES))

    def test_ranking_export_structure(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            export_ranking,
        )

        ranking = export_ranking()
        self.assertEqual(len(ranking["entries"]), 3)
        self.assertEqual(
            [entry["gold_csr_rank"] for entry in ranking["entries"]], [1, 2, 3]
        )
        for entry in ranking["entries"]:
            estimate = entry["gold_csr_estimate"]
            self.assertIsNotNone(estimate)
            self.assertTrue(0.0 <= estimate <= 1.0)

    def test_report_level_consistency(self) -> None:
        from financial_agent_reliability.retrospective.report_level import (
            check_grader_bundle_freeze,
            check_report_bundle_freeze,
            recompute_report_level,
        )

        self.assertTrue(check_grader_bundle_freeze()["ok"])
        self.assertTrue(check_report_bundle_freeze()["ok"])
        consistency = recompute_report_level()
        self.assertTrue(consistency["ok"], consistency.get("problems"))
        self.assertEqual(consistency["sealed_rows"], 810)


@unittest.skipUnless(_real_batches_available(), "需要本机 runs//evidence/ 历史产物")
class DeterminismTest(unittest.TestCase):
    """复盘工具可重复运行且结果稳定(验收口径)。"""

    def test_full_retrospective_is_deterministic(self) -> None:
        from financial_agent_reliability.retrospective.report import (
            run_full_retrospective,
        )

        first = json.dumps(run_full_retrospective(), sort_keys=True)
        second = json.dumps(run_full_retrospective(), sort_keys=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
