"""Portable evidence checks, not a semantic grader or production permission gate."""

import copy
import hashlib
import json
import posixpath
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/caddie_context_recovery"
RECEIPT_EVIDENCE = FIXTURE / "receipt_record_offer_20260919.json"
LINK = re.compile(r"\]\(([^)]+)\)")
MUTABLE = {"CURRENT.md", "docs/history/change-0514.md"}
SOURCES = {
    "reply.md": "docs/history/evidence/2026-05-20/reply.md",
    "memo-0513.md": "docs/history/evidence/2026-05-20/memo-0513.md",
}


def local_target(source, reference):
    """Resolve without opening any external path (including encoded traversal)."""
    ref = unquote(reference.strip("<>"))
    url = urlsplit(ref)
    if url.scheme or url.netloc or ref.startswith("/") or "\\" in ref:
        raise ValueError("external reference")
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source), url.path))
    if target == ".." or target.startswith("../"):
        raise ValueError("reference escapes project")
    return target if url.path else source


def preservation_errors(before, received, after):
    errors = []
    permitted = set(before) | set(SOURCES.values())
    if set(after) != permitted:
        errors.append("files outside record scope or missing")
    for name, original in before.items():
        if name not in MUTABLE and after.get(name) != original:
            errors.append("original changed: " + name)
    original = before["docs/history/change-0514.md"].rstrip()
    if not after.get("docs/history/change-0514.md", "").startswith(original):
        errors.append("historical text overwritten")
    for name, target in SOURCES.items():
        if after.get(target) != received[name]:
            errors.append("source changed: " + name)
    return errors


def reachable(files, start="README.md"):
    seen, pending = set(), [start]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        if current not in files:
            raise ValueError("missing file: " + current)
        seen.add(current)
        for ref in LINK.findall(files[current]):
            pending.append(local_target(current, ref))
        # Existing projects may identify evidence by a root-relative code path,
        # not a Markdown hyperlink. It must name a real file in this same case.
        for ref in re.findall(r"`([^`\n]+\.md)`", files[current]):
            if "/" in ref and ref in files:
                pending.append(ref)
    return seen


class CaddieContextRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.input = json.loads((FIXTURE / "input.json").read_text(encoding="utf-8"))
        cls.record = json.loads((FIXTURE / "recorded.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads(RECEIPT_EVIDENCE.read_text(encoding="utf-8"))

    def test_entry_has_resolvable_conditional_reference(self):
        entry = ROOT / "skills/project-steward/SKILL.md"
        refs = LINK.findall(entry.read_text(encoding="utf-8"))
        path = "references/caddie_context_recovery.md"
        self.assertEqual(refs.count(path), 1)
        self.assertTrue((entry.parent / path).is_file())

    def test_record_only_changes_authorized_files_and_preserves_originals(self):
        self.assertEqual(preservation_errors(
            self.input["initial"], self.input["received"], self.record["case"]), [])

    def test_detects_overwritten_history(self):
        damaged = copy.deepcopy(self.record["case"])
        damaged["docs/history/change-0514.md"] = "後日判明した理由だけ"
        self.assertIn("historical text overwritten", preservation_errors(
            self.input["initial"], self.input["received"], damaged))

    def test_detects_changed_source_even_if_summary_is_plausible(self):
        damaged = copy.deepcopy(self.record["case"])
        damaged[SOURCES["reply.md"]] += "\n確認済みとする\n"
        self.assertIn("source changed: reply.md", preservation_errors(
            self.input["initial"], self.input["received"], damaged))

    def test_detects_unapproved_requirement_edit(self):
        damaged = copy.deepcopy(self.record["case"])
        damaged["docs/requirements.md"] = "記録を引き継ぐ。"
        self.assertIn("original changed: docs/requirements.md", preservation_errors(
            self.input["initial"], self.input["received"], damaged))

    def test_detects_deleted_record_or_added_ledger(self):
        for name, remove in (("README.md", True), ("new-ledger.md", False)):
            damaged = copy.deepcopy(self.record["case"])
            if remove:
                del damaged[name]
            else:
                damaged[name] = "duplicate ledger"
            self.assertIn("files outside record scope or missing", preservation_errors(
                self.input["initial"], self.input["received"], damaged))

    def test_entry_reaches_both_original_sources_after_relocation(self):
        self.assertTrue(set(SOURCES.values()) <= reachable(self.record["case"]))

    def test_detects_broken_source_link(self):
        damaged = copy.deepcopy(self.record["case"])
        del damaged[SOURCES["memo-0513.md"]]
        with self.assertRaises(ValueError):
            reachable(damaged)

    def test_local_resolution_refuses_escape_and_external_locations(self):
        for ref in ("../../secret.md", "%2e%2e/%2e%2e/secret.md",
                    "C:/private.md", "https://example.test/doc", "//host/doc", "..\\doc"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                local_target("docs/record.md", ref)

    def test_reader_received_identical_case_without_inbox(self):
        hashes = {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                  for name, text in self.record["case"].items()}
        self.assertEqual(hashes, self.record["reader_case_sha256"])
        self.assertFalse(any(name.startswith("inbox/") for name in hashes))

    def test_reader_response_links_resolve_from_actual_output_location(self):
        files = {"case/" + name: text for name, text in self.record["case"].items()}
        refs = LINK.findall(self.record["reader_reply"])
        self.assertTrue(refs, "Evidence location requested but no file links returned")
        for ref in refs:
            self.assertIn(local_target("outputs/reply.md", ref), files)

    def test_current_state_does_not_duplicate_source_correspondence(self):
        current = self.record["case"]["CURRENT.md"]
        for original in self.input["received"].values():
            self.assertNotIn(original.strip(), current)

    def test_record_identifies_evaluated_runtime_without_pinning_future_versions(self):
        for path, expected in self.record["runtime_sha256"].items():
            self.assertTrue((ROOT / path).is_file())
            self.assertRegex(expected, r"^[0-9a-f]{64}$")

    def test_receipt_result_contract_connects_record_gap_and_no_duplicate_branch(self):
        procedure = (ROOT / "skills/project-steward/references/caddie_context_recovery.md").read_text(
            encoding="utf-8")
        bridge = self.receipt["candidate_bridge"]
        self.assertEqual(procedure.count(bridge), 1)
        self.assertIn("既存記録へつなぐ最小案、対象、必要な許可を一件", bridge)
        self.assertIn("重複記録や不要な許可確認を増やしません", bridge)
        self.assertEqual(
            hashlib.sha256(procedure.encode("utf-8")).hexdigest(),
            self.receipt["runtime_sha256"]["candidate_procedure"])

    def test_receipt_record_offer_evidence_preserves_both_branches(self):
        expected = {
            ("A", "reason-new"): "×",
            ("A", "reason-recorded"): "○",
            ("B", "reason-new"): "○",
            ("B", "reason-recorded"): "○",
        }
        actual = {(case["variant"], case["scenario"]): case["overall"]
                  for case in self.receipt["conditions"]}
        self.assertEqual(actual, expected)
        self.assertEqual(self.receipt["phase"], "E2")
        self.assertFalse(self.receipt["normal_operation_verified"])
        for output in self.receipt["outputs"]:
            path = FIXTURE / output["file"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), output["sha256"])


if __name__ == "__main__":
    unittest.main()
