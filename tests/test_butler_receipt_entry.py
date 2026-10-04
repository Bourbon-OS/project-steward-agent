"""Product-side routing and resource integrity; not an AI behavior evaluation."""
from pathlib import Path
import hashlib
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "skills/project-steward/SKILL.md"
ENTRY = ROOT / "skills/receive-butler-result/SKILL.md"
RECEIPT = COMMON.parent / "references/result_receipt.md"
RETURN = COMMON.parent / "references/result_return.md"
TEMPLATE = COMMON.parent / "templates/butler/AGENTS.md"
PERIODIC_ENTRY = ROOT / "skills/review-butler-projects/SKILL.md"
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MD_FILE = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.md(?![A-Za-z0-9_.-])")


def text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def resolve_files(source, names):
    result = set()
    for name in names:
        path = (source.parent / name).resolve()
        path.relative_to((ROOT / "skills").resolve())
        if not path.is_file():
            raise AssertionError(f"Missing procedure target: {name}")
        result.add(path)
    return result


def step_targets(body):
    # Scope is numbered procedure steps, not the document's provenance text.
    steps = "\n".join(re.findall(r"^\d+\.\s+(.+)$", body, re.MULTILINE))
    return resolve_files(RECEIPT, MD_FILE.findall(steps))


class ButlerReceiptEntryTests(unittest.TestCase):
    def test_dedicated_and_startup_links_resolve(self):
        self.assertEqual(resolve_files(ENTRY, LINK.findall(text(ENTRY))),
                         {COMMON.resolve(), PERIODIC_ENTRY.resolve(), RECEIPT.resolve(), RETURN.resolve()})
        self.assertEqual(resolve_files(TEMPLATE, LINK.findall(text(TEMPLATE))),
                         {ENTRY.resolve(), PERIODIC_ENTRY.resolve(), COMMON.resolve()})
        self.assertIn("references/result_return.md", LINK.findall(text(COMMON)))
        self.assertIn("../receive-butler-result/SKILL.md", LINK.findall(text(COMMON)))

    def test_receipt_step_reuses_the_shared_return_file(self):
        self.assertEqual(step_targets(text(RECEIPT)), {RETURN.resolve()})
        self.assertEqual(resolve_files(RECEIPT, LINK.findall(text(RECEIPT))), {RETURN.resolve()})

    def test_stale_bare_filename_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Missing procedure target: RETURN_RULES.md"):
            step_targets("4. その状態を踏まえ、RETURN_RULES.mdに従って返す。")

    def test_nonexistent_markdown_link_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Missing procedure target: missing_result.md"):
            step_targets("4. 保存後は[結果返却](missing_result.md)を読む。")

    def test_moved_gate_preserves_every_pre_extraction_rule(self):
        # Frozen rule-line digests from be4c947's support gate, not local outputs.
        expected = json.loads(text(ROOT / "tests/fixtures/butler_support_gate_lines.json"))
        common_gate = text(COMMON).split("## 利用者支援ゲート\n", 1)[1].split("\n## 手順", 1)[0]
        combined = common_gate + "\n" + text(RETURN)
        actual = {hashlib.sha256(line.strip().encode("utf-8")).hexdigest()
                  for line in combined.splitlines() if line.strip()}
        self.assertTrue(set(expected["sha256_lines"]).issubset(actual))

    def test_long_rules_are_not_duplicated_into_entrypoints(self):
        rules = [line for line in text(RETURN).splitlines()
                 if line.startswith(("- ", "  ")) and len(line) > 40]
        self.assertTrue(rules)
        for entry in (COMMON, ENTRY, TEMPLATE):
            for rule in rules:
                self.assertNotIn(rule, text(entry))

    def test_bounded_entry_does_not_require_common_fulltext_first(self):
        entry = text(ENTRY)
        self.assertIn("既存の一件の依頼", entry)
        self.assertIn("元のOwner許可", entry)
        self.assertIn("一覧全体の未完了を内部で再選別", entry)
        self.assertIn("専用入口を使ったことも共通全文を参照済みの意味ではありません", entry)
        self.assertIn("本文はここへ複製しません", entry)
        self.assertIn("共通Skill全文を前提にしない", text(TEMPLATE))

    def test_broader_actions_return_to_common_without_granting_permission(self):
        boundary = text(ENTRY).split("## 範囲外へ広がる時", 1)[1]
        for action in ("日次・週次確認全体", "新しい送信", "対象projectの変更", "公開・Git操作", "Work Mapの更新"):
            self.assertIn(action, boundary)
        self.assertIn("共通を読むこと自体は追加操作の許可ではなく", boundary)
        self.assertIn("接続不足", boundary)
        self.assertIn("未完了・結果・次の確認先・戻る条件", boundary)


if __name__ == "__main__":
    unittest.main()
