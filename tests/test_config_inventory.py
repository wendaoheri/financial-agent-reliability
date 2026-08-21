from __future__ import annotations

import pathlib
import re
import unittest

from financial_agent_reliability.models import load_candidates

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
CANONICAL_CONFIGS = {
    "framework-qualification.json",
    "mock.json",
    "pi-bailian-live.json",
    "pi-offline-negative-control.json",
    "pi-offline.json",
    "plain-bailian-live.json",
}
DELETED_CONFIGS = {
    "bailian-token-plan.json",
    "framework-qualification.v1.json",
    "per424-mock.json",
    "pi-bailian-calibration-v2.json",
    "pi-bailian-calibration-v3.json",
    "pi-bailian-pilot.json",
}


class ConfigInventoryTests(unittest.TestCase):
    def test_only_canonical_role_configs_are_shipped(self):
        actual = {path.name for path in CONFIGS.glob("*.json")}
        self.assertEqual(actual, CANONICAL_CONFIGS)
        for name in actual:
            load_candidates(CONFIGS / name)

    def test_every_canonical_config_is_documented_and_old_names_are_absent(self):
        documentation = [
            ROOT / "AGENTS.md",
            ROOT / "README.md",
            *sorted((ROOT / "docs").glob("*.md")),
        ]
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in documentation)
        mentioned = set(re.findall(r"configs/([A-Za-z0-9.-]+\.json)", rendered))
        self.assertLessEqual(CANONICAL_CONFIGS, mentioned)
        self.assertTrue(DELETED_CONFIGS.isdisjoint(mentioned))


if __name__ == "__main__":
    unittest.main()
