import copy
import json
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from cases.public.oracle import evaluate
from cases.public.oracle_reference import recompute
from cases.public.v2.build_public_cases_v2 import (
    OLD_BUNDLE_SHA256,
    validate_collection_clock,
    validate_source_license,
)
from contracts.validate_case_data import (
    file_sha256,
    load_json,
    validate_case_card,
    validate_data_snapshot,
    verify_manifest,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "public" / "v2"
CASES = ROOT / "cases" / "public" / "v2"
SNAPSHOTS = ROOT / "snapshots" / "public" / "v2"
RAW = SNAPSHOTS / "raw"


class PublicCaseCatalogV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG / "seed_catalog.v2.json")
        cls.session = load_json(RAW / "collection_session.v2.json")
        cls.envelopes = {
            f"FKW-{number:02d}": load_json(RAW / f"FKW-{number:02d}.json")
            for number in range(1, 16)
        }
        cls.snapshots = {
            snapshot["snapshot_id"]: snapshot
            for snapshot in (load_json(path) for path in sorted(SNAPSHOTS.glob("data_snapshot.FKW-*.json")))
        }
        cls.cases = {
            case["case_id"]: case
            for case in (load_json(path) for path in sorted(CASES.glob("case_card.FKW-*.json")))
        }

    def test_v1_is_revoked_without_hash_replacement(self):
        self.assertEqual(self.catalog["supersedes"]["bundle_sha256"], OLD_BUNDLE_SHA256)
        self.assertEqual(self.catalog["supersedes"]["status"], "revoked")
        self.assertEqual(
            set(self.catalog["supersedes"]["reason_codes"]),
            {"FUTURE_RETRIEVAL_TIMESTAMP", "UNSUPPORTED_FINQA_DATASET_LICENSE_CLAIM"},
        )
        old_manifest = load_json(ROOT / "catalog" / "public" / "frozen_manifest.v1.json")
        self.assertEqual(old_manifest["contract_bundle_sha256"], OLD_BUNDLE_SHA256)
        verify_manifest(ROOT / "catalog" / "public" / "frozen_manifest.v1.json")

    def test_real_collection_clock_is_consistent_and_not_future_dated(self):
        validate_collection_clock(self.session, self.envelopes)
        completed = datetime.fromisoformat(self.session["completed_at"].replace("Z", "+00:00"))
        generated = datetime.fromisoformat(self.catalog["generated_at"].replace("Z", "+00:00"))
        self.assertLessEqual(completed, generated)
        self.assertLessEqual(generated, datetime.now(timezone.utc))
        for family_id, envelope in self.envelopes.items():
            retrieved = datetime.fromisoformat(envelope["retrieved_at"].replace("Z", "+00:00"))
            file_time = datetime.fromtimestamp((RAW / f"{family_id}.json").stat().st_mtime, timezone.utc)
            self.assertLessEqual(retrieved, file_time + timedelta(seconds=1))

    def test_rejects_future_or_inverted_collection_timestamps(self):
        bad = copy.deepcopy(self.envelopes)
        bad["FKW-01"]["retrieved_at"] = "2999-01-01T00:00:00.000000Z"
        with self.assertRaisesRegex(ValueError, "inverted or future-dated"):
            validate_collection_clock(self.session, bad)
        bad_session = copy.deepcopy(self.session)
        bad_session["completed_at"] = "2999-01-01T00:00:00.000000Z"
        with self.assertRaisesRegex(ValueError, "inverted or future-dated"):
            validate_collection_clock(bad_session, self.envelopes)

    def test_finqa_license_is_repository_scoped_and_conservative(self):
        records = [family["source_license"] for family in self.catalog["families"] if family["source_id"] == "finqa"]
        self.assertEqual(len(records), 4)
        for record in records:
            validate_source_license("finqa", record)
            self.assertIn("MIT repository license", record["name"])
            self.assertNotIn("CC-BY", json.dumps(record))
            self.assertFalse(record["redistributable"])

    def test_rejects_unsupported_finqa_license_claims(self):
        valid = next(family["source_license"] for family in self.catalog["families"] if family["source_id"] == "finqa")
        bad_cc = copy.deepcopy(valid)
        bad_cc["name"] = "CC-BY-4.0 dataset; MIT code"
        with self.assertRaisesRegex(ValueError, "unsupported dataset Creative Commons claim"):
            validate_source_license("finqa", bad_cc)
        bad_scope = copy.deepcopy(valid)
        bad_scope["applicability_limit"] = "Repository is MIT."
        with self.assertRaisesRegex(ValueError, "dataset-license uncertainty"):
            validate_source_license("finqa", bad_scope)
        bad_redistribution = copy.deepcopy(valid)
        bad_redistribution["redistributable"] = True
        with self.assertRaisesRegex(ValueError, "redistribution must stay disabled"):
            validate_source_license("finqa", bad_redistribution)

    def test_allocation_contracts_lineage_and_oracles(self):
        self.assertEqual(len(self.catalog["families"]), 15)
        self.assertEqual(len(self.snapshots), 15)
        self.assertEqual(len(self.cases), 45)
        self.assertEqual(sum(case["quality"]["tier"] == "Gold" for case in self.cases.values()), 22)
        self.assertEqual(sum(case["quality"]["tier"] == "Silver" for case in self.cases.values()), 23)
        for snapshot in self.snapshots.values():
            validate_data_snapshot(snapshot)
        for case in self.cases.values():
            parent = self.cases.get(case["variant"]["parent_case_id"])
            validate_case_card(case, snapshots=self.snapshots, parent_case=parent)
            refs = case["evidence_refs"]
            snapshot = self.snapshots[refs[0]["snapshot_id"]] if refs else None
            production = evaluate(snapshot, case["task"]["inputs"])
            self.assertEqual(production["status"], case["oracle"]["expected_status"])
            self.assertEqual(production["value"], case["oracle"]["expected_value"])
            if case["quality"]["tier"] == "Gold":
                self.assertEqual(production, recompute(snapshot, case["task"]["inputs"]))
        for capture in self.session["captures"]:
            path = RAW / f"{capture['family_id']}.json"
            self.assertEqual(file_sha256(path), capture["raw_response_sha256"])

    def test_v2_manifest_is_frozen_and_release_remains_closed(self):
        verify_manifest(CATALOG / "frozen_manifest.v2.json")
        self.assertFalse(self.catalog["release"]["candidate_runs_allowed"])


if __name__ == "__main__":
    unittest.main()
