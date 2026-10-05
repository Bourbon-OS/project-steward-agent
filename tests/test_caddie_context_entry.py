"""Entry and recorded-evidence integrity checks, not a semantic model grader."""
import hashlib
import json
import unittest
from pathlib import Path

from tests.test_caddie_context_recovery import LINK, local_target

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "skills/check-caddie-context/SKILL.md"
PROCEDURE = "skills/project-steward/references/caddie_context_recovery.md"
COMMON = "skills/project-steward/SKILL.md"


class CaddieContextEntryTests(unittest.TestCase):
    def test_direct_entry_reuses_the_canonical_procedure(self):
        text = (ROOT / ENTRY).read_text(encoding="utf-8")
        refs = [local_target(ENTRY, ref) for ref in LINK.findall(text)]
        self.assertIn(PROCEDURE, refs)
        self.assertIn(COMMON, refs)
        for ref in refs:
            self.assertTrue((ROOT / ref).is_file(), ref)
        # The entry is a router, not another copy of the detailed procedure.
        procedure = (ROOT / PROCEDURE).read_text(encoding="utf-8")
        for paragraph in procedure.split("\n\n"):
            if len(paragraph) > 120:
                self.assertNotIn(paragraph, text)

    def test_descriptions_separate_bounded_context_from_broader_operations(self):
        entry = (ROOT / ENTRY).read_text(encoding="utf-8").split("---")[1]
        common = (ROOT / COMMON).read_text(encoding="utf-8").split("---")[1]
        self.assertIn("change notice", entry)
        self.assertIn("Not for project setup", entry)
        self.assertIn("use check-caddie-context instead", common)
        self.assertIn("not a prerequisite", common)

    def test_connection_is_not_permission_or_a_claim_to_have_read_everything(self):
        text = (ROOT / ENTRY).read_text(encoding="utf-8")
        for phrase in ("許可外を探索せず", "手順名や版だけで確認済みにしません",
                       "その行動の許可を別に確認", "共通手順まで参照済みとは報告しません"):
            self.assertIn(phrase, text)

    def test_setup_links_the_same_entry_without_copying_the_procedure(self):
        path = "skills/project-steward/templates/caddie_setup.md"
        text = (ROOT / path).read_text(encoding="utf-8")
        self.assertIn(ENTRY, [local_target(path, ref) for ref in LINK.findall(text)])
        self.assertIn("同じ配布一式", text)
        self.assertIn("実行許可を増やしません", text)

    def test_record_keeps_distinct_cases_and_frozen_inputs(self):
        record = json.loads((ROOT / "tests/fixtures/caddie_context_recovery/change_notice_verified.json").read_text(encoding="utf-8"))
        trial = record["direct_entry_trial"]
        for variant in ("a", "b"):
            case = record["cases"][variant]
            for name, text in case.items():
                actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
                self.assertEqual(actual, trial["case_text_sha256"][variant][name])
        self.assertNotEqual(record["cases"]["a"]["docs/history/change-0514.md"],
                            record["cases"]["b"]["docs/history/change-0514.md"])
        self.assertEqual(trial["protected_before"], trial["protected_after"])

    def test_saved_responses_have_resolvable_evidence_locations(self):
        record = json.loads((ROOT / "tests/fixtures/caddie_context_recovery/change_notice_verified.json").read_text(encoding="utf-8"))
        trial = record["direct_entry_trial"]
        for variant in ("a", "b"):
            response = trial["responses"][variant]["saved"]
            files = {"case/" + name for name in record["cases"][variant]}
            refs = LINK.findall(response)
            # A response may use concrete project paths rather than Markdown.
            paths = [local_target("response.md", ref) for ref in refs]
            for path in files:
                if "`" + path + "`" in response:
                    paths.append(path)
            self.assertTrue(paths, variant + ": no evidence locations")
            for path in paths:
                self.assertIn(path, files)

    def test_evidence_is_not_self_grading_or_claiming_normal_operation(self):
        record = json.loads((ROOT / "tests/fixtures/caddie_context_recovery/change_notice_verified.json").read_text(encoding="utf-8"))
        trial = record["direct_entry_trial"]
        self.assertEqual(trial["target_runs"], 2)
        self.assertEqual(trial["evaluator_runs"], 1)
        self.assertTrue(trial["simulation_only"])
        self.assertEqual(trial["evidence_level"], "E2")
        self.assertFalse(trial["normal_operation_verified"])
        self.assertTrue(trial["independent_evaluation"]["text"].strip())
        # Do not score model quality by matching a preferred phrase or stored verdict.


if __name__ == "__main__":
    unittest.main()
