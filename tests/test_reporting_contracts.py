import copy
import pathlib
import unittest

from financial_agent_reliability.reporting.report import (
    ReportContractError,
    load_json,
    render_html,
    render_markdown,
    validate_report,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reporting" / "report.partial.valid.json"
EXPECTED = ROOT / "tests" / "expected" / "reporting"


class ReportingContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_json(FIXTURE)

    def assert_contract_error(self, callable_, fragment):
        with self.assertRaises(ReportContractError) as caught:
            callable_()
        self.assertIn(fragment, str(caught.exception))

    def test_partial_example_is_valid_and_withholds_ranking(self):
        result = validate_report(self.bundle)
        self.assertEqual(result["runs"], 6)
        self.assertEqual(result["demonstrations"], 6)
        self.assertFalse(result["ranking_published"])

    def test_rejects_demonstration_reweighting(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["demonstrations"]["selection_weight_override"] = True
        self.assert_contract_error(lambda: validate_report(invalid), "demonstration reweighting is forbidden")

    def test_rejects_main_ranking_weight_mutation(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["ranking"]["track_weights"] = {
            "financial_knowledge_work": "0.700000",
            "financial_tool_workflow": "0.300000",
        }
        self.assert_contract_error(lambda: validate_report(invalid), "exactly 50/50")

    def test_rejects_omitted_failed_run(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["run_records"] = [row for row in invalid["run_records"] if row["run_id"] != "run-003"]
        invalid["run_coverage"]["observed_rows"] = 5
        invalid["run_coverage"]["state_counts"]["missing"] = 805
        self.assert_contract_error(lambda: validate_report(invalid), "failures may have been omitted")

    def test_rejects_gold_silver_mixed_ranking(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["run_coverage"] = {
            "state": "complete",
            "expected_rows": 6,
            "observed_rows": 6,
            "state_counts": {"succeeded": 4, "failed": 1, "blocked": 0, "excluded": 1, "missing": 0},
        }
        invalid["run_records"][-1]["state"] = "excluded"
        del invalid["run_records"][-1]["failure_evidence"]
        invalid["failures"] = [invalid["failures"][0]]
        invalid["ranking"]["published"] = True
        invalid["ranking"]["withheld_reason"] = None
        invalid["ranking"]["entries"] = [{
            "rank": 1,
            "immutable_model_id": "vendor/model-a@2026-08",
            "financial_agentic_index": "0.900000",
            "source_tier": "Silver",
            "track_weights": invalid["ranking"]["track_weights"],
        }]
        self.assert_contract_error(lambda: validate_report(invalid), "Silver may appear only")

    def test_rejects_silent_missing_or_blocked_as_zero_error(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["limitations"] = [item for item in invalid["limitations"] if item["code"] != "INCOMPLETE_MATRIX"]
        self.assert_contract_error(lambda: validate_report(invalid), "missing/blocked cannot be treated as zero error")

    def test_rejects_case_selection_after_unblinding(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["demonstrations"]["selection"]["decided_before_identity_unblinding"] = False
        self.assert_contract_error(lambda: validate_report(invalid), "selection must precede")

    def test_rendering_is_stable_and_html_is_accessible(self):
        markdown = render_markdown(self.bundle)
        html = render_html(self.bundle)
        self.assertEqual(markdown, (EXPECTED / "report.partial.valid.md").read_text(encoding="utf-8"))
        self.assertEqual(html, (EXPECTED / "report.partial.valid.html").read_text(encoding="utf-8"))
        for fragment in ('<html lang="zh-CN">', 'href="#main"', '<main id="main">', '<caption>', '<th scope="col">'):
            self.assertIn(fragment, html)
        self.assertIn("不影响综合分", markdown)

    def test_spec_schema_is_present_and_well_formed(self):
        # PER-323 Stage 2 migration: ``verify_freeze`` retired together with
        # the baseline-v1 frozen report contract
        # (``contracts/report_contract.frozen.v1.json``, cleanup list A1).
        # The live spec remains the authoritative reporting contract.
        spec_path = (
            ROOT / "src" / "financial_agent_reliability" / "reporting" / "spec.report.v1.json"
        )
        spec = load_json(spec_path)
        self.assertEqual(spec.get("contract_type"), "financial_agent_reporting_spec")
        self.assertRegex(spec.get("contract_version", ""), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
