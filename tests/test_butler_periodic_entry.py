"""The periodic Butler route reads its own procedure and reuses shared return rules."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "skills/project-steward/SKILL.md"
ENTRY = ROOT / "skills/review-butler-projects/SKILL.md"
PERIODIC = ROOT / "skills/project-steward/references/periodic_review.md"
MODEL = ROOT / "skills/project-steward/references/timing_and_model_policy.md"
RETURN = ROOT / "skills/project-steward/references/result_return.md"
RECEIPT = ROOT / "skills/project-steward/references/result_receipt.md"
STARTUP = ROOT / "skills/project-steward/templates/butler/AGENTS.md"
BOUNDED = ROOT / "skills/receive-butler-result/SKILL.md"
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]+)?\)")


def read(path):
    return path.read_text(encoding="utf-8")


def targets(path):
    return {(path.parent / ref).resolve() for ref in LINK.findall(read(path))}


class ButlerPeriodicEntryTests(unittest.TestCase):
    def test_periodic_route_resolves_without_common_prerequisite(self):
        for path in (ENTRY, PERIODIC, MODEL, STARTUP, BOUNDED, COMMON):
            self.assertTrue(all(target.is_file() for target in targets(path)), path)
        self.assertIn(PERIODIC.resolve(), targets(ENTRY))
        self.assertIn(RETURN.resolve(), targets(ENTRY))
        self.assertIn(RETURN.resolve(), targets(PERIODIC))
        self.assertIn(RECEIPT.resolve(), targets(PERIODIC))
        self.assertIn(ENTRY.resolve(), targets(STARTUP))
        self.assertIn(ENTRY.resolve(), targets(COMMON))
        self.assertIn(ENTRY.resolve(), targets(BOUNDED))
        self.assertLess(len(read(ENTRY)), len(read(COMMON)) // 5)
        self.assertIn("共通運用Skill全文を先に読む必要はありません", read(ENTRY))
        self.assertIn("新しい担当への送信に進む時は", read(ENTRY))
        self.assertIn("相談・引き渡しと連携完了ゲートの該当箇所", read(ENTRY))

    def test_periodic_rules_have_one_home_and_model_details_stay_conditional(self):
        common = read(COMMON)
        periodic = read(PERIODIC)
        model = read(MODEL)
        for rule in (
            "連絡がなくても実態を確認する期限",
            "機械候補0件でも未完了や未回収結果を飛ばさない",
            "送信操作の戻り値だけで依頼済みとしない",
            "同じ基準日で再選別",
            "前回と同じ根拠、同じ未決事項、同じ質問",
            "横断事項は、導入済みの各プロジェクトについて",
            "複数の未完了へ優先順位を付ける前に",
            "1位が実行可能なら、1位を次の行動にする",
            "1位の扱いを決めず、直前に話していた2位以下だけを次の行動として提示しない",
        ):
            self.assertIn(rule, periodic)
            self.assertNotIn(rule, common)
            self.assertNotIn(rule, model)
        self.assertIn("モデル・推論量を選ぶ時だけ", periodic)
        self.assertIn("モデル・推論量を選ぶ時だけ", model)
        self.assertNotIn("連絡がなくても拾う", read(ENTRY))
        self.assertIn("[結果返却の共通規則]", read(ENTRY))
        self.assertIn("[結果返却の共通規則]", periodic)


if __name__ == "__main__":
    unittest.main()
