from __future__ import annotations

import copy
import hashlib
import itertools
import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tasks" / "per424"


class Per424AssetPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = [
            json.loads(line)
            for line in (ROOT / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        cls.coverage = json.loads((ROOT / "coverage.json").read_text(encoding="utf-8"))
        cls.contract = json.loads((ROOT / "candidate-contract.json").read_text(encoding="utf-8"))
        cls.sources = [
            json.loads(line)
            for line in (ROOT / "sources.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]

    def test_exact_case_variant_and_gate_distribution(self) -> None:
        self.assertEqual(len(self.tasks), 100)
        self.assertEqual(len({task["id"] for task in self.tasks}), 100)
        self.assertEqual(
            Counter(task["variant"] for task in self.tasks), {"normal": 60, "challenge": 40}
        )
        expected = {"D1": 12, "D2": 13, "D3": 12, "D4": 13, "D5": 12, "D6": 12, "D7": 13, "D8": 13}
        self.assertEqual(Counter(task["primary_gate"] for task in self.tasks), expected)
        self.assertEqual(self.coverage["pair_family_count"], 40)
        self.assertEqual(len(self.coverage["extra_normal_families"]), 20)

    def test_prompts_are_independent_long_chinese_tasks(self) -> None:
        prompt_counts = Counter(task["prompt"] for task in self.tasks)
        self.assertEqual(Counter(prompt_counts.values()), {2: 40, 1: 20})
        for task in self.tasks:
            prompt = task["prompt"].strip()
            self.assertGreaterEqual(len(prompt), 5000, task["id"])
            self.assertGreaterEqual(len(re.findall(r"[\u4e00-\u9fff]", prompt)), 3000, task["id"])
            self.assertNotIn("evaluator-only Gold 的内容如下", prompt)
            self.assertIn("冻结公开来源", prompt)

        family_prompts = {task["family_id"]: task["prompt"] for task in self.tasks}.values()
        grams = [
            {prompt[index : index + 5] for index in range(len(prompt) - 4)}
            for prompt in family_prompts
        ]
        maximum = max(
            len(left & right) / len(left | right)
            for left, right in itertools.combinations(grams, 2)
        )
        self.assertLessEqual(
            maximum,
            self.manifest["composition"]["cross_family_prompt_5gram_jaccard_max"],
        )

    def test_source_mix_and_provenance_are_frozen(self) -> None:
        self.assertEqual(len(self.sources), 60)
        self.assertEqual(len({source["source_id"] for source in self.sources}), 60)
        self.assertEqual(
            Counter(source["source_class"] for source in self.sources),
            {"licensed_dataset": 24, "official_record": 24, "final_enforcement": 12},
        )
        self.assertEqual(
            self.coverage["source_mix"],
            {"licensed_dataset": 24, "official_record": 24, "final_enforcement": 12},
        )
        by_source = {source["source_id"]: source for source in self.sources}
        for task in self.tasks:
            source = by_source[task["notes"]["source_id"]]
            fixture = json.loads(
                (ROOT / task["candidate_payload"]["resources"][0]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(fixture["provenance"]["source_id"], source["source_id"])
            evidence = next(
                record["value"]["evidence"]
                for record in fixture["records"]
                if record["kind"] == "source_evidence"
            )
            canonical = json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            self.assertEqual(
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                fixture["provenance"]["evidence_digest"],
            )
            self.assertEqual(task["tags"]["data_class"], "public_source_frozen")

        self.assertFalse(self.manifest["scope"]["synthetic_only"])
        self.assertEqual(
            self.manifest["scope"]["source_boundary"],
            "frozen_public_source_plus_controlled_synthetic_challenge",
        )

    def test_pair_fixtures_change_only_one_control_value(self) -> None:
        families: dict[str, list[dict]] = defaultdict(list)
        for task in self.tasks:
            families[task["family_id"]].append(task)
        paired = 0
        for family_tasks in families.values():
            if len(family_tasks) == 1:
                self.assertEqual(family_tasks[0]["notes"]["pair_role"], "extra_normal")
                continue
            paired += 1
            self.assertEqual({task["variant"] for task in family_tasks}, {"normal", "challenge"})
            normal = next(task for task in family_tasks if task["variant"] == "normal")
            challenge = next(task for task in family_tasks if task["variant"] == "challenge")
            self.assertEqual(normal["prompt"], challenge["prompt"])
            normal_fixture = json.loads(
                (ROOT / normal["candidate_payload"]["resources"][0]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            challenge_fixture = json.loads(
                (ROOT / challenge["candidate_payload"]["resources"][0]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            normal_control = normal_fixture["records"][2]["value"]
            challenge_control = challenge_fixture["records"][2]["value"]
            self.assertNotEqual(normal_control, challenge_control)
            normalized = copy.deepcopy(normal_fixture)
            normalized["records"][2]["value"] = challenge_control
            self.assertEqual(normalized, challenge_fixture)
        self.assertEqual(paired, 40)

    def test_candidate_and_evaluator_boundaries_are_explicit(self) -> None:
        self.assertIn("gold", self.contract["evaluator_only"])
        self.assertIn("gold", self.contract["strip_before_candidate"])
        self.assertIn("candidate_payload.resources[].path", self.contract["strip_before_candidate"])
        for task in self.tasks:
            self.assertNotIn("gold", task["candidate_payload"])
            self.assertNotIn("variant", task["candidate_payload"])
            self.assertNotIn("primary_gate", task["candidate_payload"])
            self.assertRegex(task["candidate_payload"]["task_id"], r"^PER424-T\d{3}$")
            self.assertNotRegex(task["candidate_payload"]["task_id"], r"D[1-8]|normal|challenge")
            self.assertNotRegex(
                task["candidate_payload"]["input"]["fixture_id"],
                r"D[1-8]|normal|challenge",
            )
            self.assertNotRegex(
                task["prompt"],
                r"编号 D[1-8]|主可靠性门是 D[1-8]|报告中的“[^”]+”失效机制",
            )
            allowed = set(task["candidate_payload"]["output_contract"]["allowed_reason_codes"])
            self.assertTrue(set(task["gold"]["expected_output"]["reason_codes"]).issubset(allowed))
            self.assertTrue(task["gold"]["safety_policy"]["read_only"])
            self.assertTrue(task["gold"]["safety_policy"]["safety_hard_gate"])
            self.assertEqual(task["candidate_payload"]["budget"]["cost_usd_cap"], "0.000000")

    def test_report_taxonomy_and_failure_mechanisms_are_covered(self) -> None:
        expected_roots = {
            "R1": "目标与评价激励错配",
            "R2": "数据、知识与证据基础失真",
            "R3": "推理与金融方法能力边界",
            "R4": "工具、权限和长链状态失控",
            "R5": "组织治理与责任供应链约束失效",
        }
        self.assertEqual(self.manifest["root_causes"], expected_roots)
        self.assertTrue(any(len(task["root_causes"]) > 1 for task in self.tasks))
        mechanisms = {item for task in self.tasks for item in task["tags"]["failure_mechanisms"]}
        required = {
            "goal_substitution",
            "incentive_mismatch",
            "potemkin_understanding",
            "evidence_hallucination",
            "point_in_time_pollution",
            "false_precision",
            "unfaithful_reasoning",
            "compliance_story",
            "method_mismatch",
            "regime_counterfactual",
            "backtest_leakage_overfit",
            "wrong_business_object",
            "long_chain_drift",
            "self_correction_illusion",
            "correlated_multi_agent_consensus",
            "prompt_injection_permissions",
            "suitability",
            "compliance_explanation",
            "responsibility_mismatch",
        }
        self.assertTrue(required.issubset(mechanisms), sorted(required - mechanisms))
        cross_cutting = {item for task in self.tasks for item in task["tags"]["cross_cutting"]}
        self.assertTrue(
            {
                "nonstationarity",
                "time_basis",
                "tail_loss",
                "correlated_common_mode",
                "audit_appearance",
            }.issubset(cross_cutting)
        )

    def test_manifest_asset_hashes_match(self) -> None:
        excluded_terms = {
            "git_commit",
            "dependency_lock",
            "operating_system",
            "worktree_state",
            "runner_source_hash",
        }
        self.assertTrue(excluded_terms.isdisjoint(self.manifest))
        for relative, metadata in self.manifest["asset_files"].items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"], relative
            )
            self.assertEqual(path.stat().st_size, metadata["bytes"], relative)


if __name__ == "__main__":
    unittest.main()
