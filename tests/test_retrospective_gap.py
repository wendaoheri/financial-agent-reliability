"""fareli-retro baseline-gap gate (PER-323 Stage 2, cleanup list M2).

Regression guard: with the baseline-v1 lineage roots removed, ``fareli-retro``
must reach the explicit ``baseline_gap`` gate for every subcommand instead of
crashing at import time (the retrospective modules still bind to the removed
baseline. Baseline v3 intentionally rebuilds evaluation inputs and contracts,
not the deleted historical run evidence, so the gate remains active.
"""

import io
import json
import unittest
from contextlib import redirect_stdout

from financial_agent_reliability.retrospective.cli import BASELINE_V2_PENDING, main


class RetrospectiveGapTests(unittest.TestCase):
    def test_subcommands_report_baseline_gap_without_import_crash(self):
        for argv in (["list"], ["run", "--all"], ["lineage"], ["archive-map"]):
            with self.subTest(argv=argv):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(argv)
                self.assertEqual(exit_code, 2)
                payload = json.loads(buffer.getvalue())
                self.assertEqual(payload["status"], "baseline_gap")
                self.assertIn("PER-323", payload["reason"])
                self.assertIn("baseline v3", payload["reason"])
                self.assertNotIn("rebuilt on baseline v2", payload["reason"])

    def test_gate_remains_active_without_rebuilt_historical_run_evidence(self):
        self.assertTrue(BASELINE_V2_PENDING)


if __name__ == "__main__":
    unittest.main()
