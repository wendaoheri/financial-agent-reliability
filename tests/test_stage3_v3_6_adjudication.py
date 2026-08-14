import unittest

from audit.build_stage3_v3_6_adjudication import (
    CASE_REASON_CODE_SETS,
    REASON_CODE_DEFINITIONS,
    build,
    verify_written,
)


class Stage3V36AdjudicationTests(unittest.TestCase):
    def test_frozen_inputs_and_all_grader_fields_are_covered(self):
        spec, ledger, _ = build(write=False)
        self.assertEqual(spec["source_integrity"]["runs"], 36)
        self.assertEqual(ledger["coverage"]["grader_fields"], 396)
        self.assertEqual(ledger["coverage"]["observed_fail"], 47)
        self.assertEqual(
            ledger["failure_check_attribution"],
            {
                "contract_defect": 13,
                "provider_or_runtime_failure": 31,
                "candidate_failure": 3,
                "indeterminate": 0,
            },
        )

    def test_reason_code_contract_is_complete_and_exact_for_12_cases(self):
        self.assertEqual(len(REASON_CODE_DEFINITIONS), 18)
        self.assertEqual(len(CASE_REASON_CODE_SETS), 12)
        for policy in CASE_REASON_CODE_SETS.values():
            self.assertEqual(set(policy["required"]), set(policy["allowed"]))
            self.assertLessEqual(set(policy["required"]), set(REASON_CODE_DEFINITIONS))
        for definition in REASON_CODE_DEFINITIONS.values():
            self.assertIn("required_when_triggered", definition)
            self.assertIn("suppresses", definition)
            self.assertIn("mutually_exclusive_with", definition)

    def test_written_artifacts_are_reproducible(self):
        result = verify_written()
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
