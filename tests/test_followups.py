from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pma.cli import main
from pma.followups import (
    Followup,
    FollowupInputError,
    build_followups_report,
    select_followups,
)


TARGET_HEADERS = ["プロジェクト", "導入状態", "浅い状態", "次回確認"]
EVENT_HEADERS = [
    "プロジェクト",
    "オーナー付きStewardの受領",
    "正本への反映",
    "判断待ち / 確認先",
    "次回確認",
    "緊急性",
    "緊急性の理由",
    "次の行動 / 戻る条件",
    "横断事項",
    "横断対応",
]


class FollowupSelectionTests(unittest.TestCase):
    def test_selects_due_unknown_and_open_event_signals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["alpha", "active", "2026-08-01"],
                    ["beta", "unknown", "2026-08-02"],
                ],
                event_rows=[
                    ["alpha", "未受領", "反映待ち", "不明", "2026-07-31"],
                    ["alpha", "受領済み", "反映確認済み", "なし", "2026-07-01"],
                ],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertEqual(
                [(item.project, item.reason, item.due) for item in items],
                [
                    ("alpha", "next_review_due", date(2026, 8, 1)),
                    ("beta", "shallow_state_unknown", None),
                    ("alpha", "parent_receipt_unreceived", None),
                    ("alpha", "local_reflection_pending", None),
                    ("alpha", "confirmation_target_unknown", None),
                    ("alpha", "next_check_due", date(2026, 7, 31)),
                ],
            )

    def test_closed_event_does_not_repeat_old_next_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_rows=[
                    ["alpha", "受領済み", "反映確認済み", "なし", "2026-07-01"]
                ],
            )

            self.assertEqual(select_followups(path, date(2026, 8, 1)), [])

    def test_known_pending_owner_keeps_dated_event_open(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_rows=[
                    ["alpha", "受領済み", "反映確認済み", "owner", "2026-08-01"]
                ],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertEqual(
                [(item.reason, item.due) for item in items],
                [("next_check_due", date(2026, 8, 1))],
            )

    def test_due_boundary_and_plain_conditions_are_deterministic(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["today", "active", "2026-08-01"],
                    ["future", "active", "2026-08-02"],
                    ["condition", "active", "再開が明示された時"],
                ],
                event_rows=[],
            )

            first = select_followups(path, date(2026, 8, 1))
            second = select_followups(path, date(2026, 8, 1))

            self.assertEqual(first, second)
            self.assertEqual(
                [(item.project, item.reason) for item in first],
                [("today", "next_review_due"), ("condition", "review_deadline_missing")],
            )

    def test_silent_introduced_projects_need_dates_but_candidates_keep_conditions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["quiet", "導入済み", "active", "連絡が来たら"],
                    ["resting", "導入済み", "paused", "再開時"],
                    ["candidate", "候補", "active", "継続が明示された時"],
                    ["ended", "見送り", "paused", "再申請時"],
                ],
                event_rows=[],
            )
            before = path.read_bytes()
            items = select_followups(path, date(2026, 9, 7))
            self.assertEqual(
                items,
                [Followup("quiet", "review_deadline_missing"),
                 Followup("resting", "review_deadline_missing")],
            )
            # Reading a missing deadline never manufactures a date or writes the list.
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("オーナー", build_followups_report(items, date(2026, 9, 7)))

    def test_unresolved_due_projects_stay_visible_beyond_top_three(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[[f"project-{i}", "active", "2026-09-01"] for i in range(5)],
                event_rows=[],
            )
            for day in (7, 8):
                items = select_followups(path, date(2026, 9, day))
                self.assertEqual(len(items), 5)
                report = build_followups_report(items, date(2026, 9, day))
                for i in range(5):
                    self.assertIn(f"project-{i}", report)
                self.assertIn("回収できなければ", report)
                self.assertIn("先送りしません", report)

    def test_next_run_recovers_missed_due_date_and_closes_after_update(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = _write_list(
                root,
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_rows=[],
            )

            self.assertEqual(select_followups(path, date(2026, 8, 1)), [])

            # No execution history is needed for the later run to recover the
            # overdue date after one or more scheduled runs were missed.
            recovered = select_followups(path, date(2026, 8, 5))
            self.assertEqual(
                [(item.project, item.reason, item.due) for item in recovered],
                [("alpha", "next_review_due", date(2026, 8, 2))],
            )

            _write_list(
                root,
                target_rows=[["alpha", "active", "2026-08-12"]],
                event_rows=[],
            )

            self.assertEqual(select_followups(path, date(2026, 8, 5)), [])

    def test_unknown_match_is_exact_after_trimming(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["exact", " 不明 ", "2026-08-02"],
                    ["sentence", "原因不明のエラー", "2026-08-02"],
                ],
                event_rows=[],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertEqual([item.project for item in items], ["exact"])

    def test_additional_columns_and_reordered_columns_are_allowed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_headers=["Extra", "次回確認", "プロジェクト", "導入状態", "浅い状態"],
                target_rows=[["ignored", "2026-08-01", "alpha", "導入済み", "active"]],
                event_headers=[
                    "次回確認",
                    "プロジェクト",
                    "Extra",
                    "正本への反映",
                    "判断待ち / 確認先",
                    "オーナー付きStewardの受領",
                    "緊急性",
                    "緊急性の理由",
                    "次の行動 / 戻る条件",
                    "横断事項",
                    "横断対応",
                ],
                event_rows=[
                    [
                        "次回日次確認", "alpha", "ignored", "反映不要", "なし", "受領済み",
                        "通常", "定期確認", "なし", "-", "該当なし",
                    ]
                ],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertEqual([item.reason for item in items], ["next_review_due"])

    def test_empty_tables_do_not_claim_that_owner_has_no_action(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(Path(temp_dir), target_rows=[], event_rows=[])

            items = select_followups(path, date(2026, 8, 1))
            report = build_followups_report(items, date(2026, 8, 1))

            self.assertEqual(items, [])
            self.assertIn("指定された対象一覧全体", report)
            self.assertIn("機械的な再確認候補はありません", report)
            self.assertIn("オーナーが今することがないことを意味しません", report)
            self.assertIn("個別の定期確認の未回収結果", report)
            self.assertIn("無回答と断定しません", report)
            self.assertIn("- 件数: `0`", report)

    def test_report_proposes_prioritized_actions_in_natural_japanese(self) -> None:
        items = [
            Followup("same", "next_review_due", date(2026, 8, 1)),
            Followup("same", "local_reflection_pending"),
            Followup("unknown", "shallow_state_unknown"),
            Followup("receipt", "parent_receipt_unreceived"),
            Followup("check", "next_check_due", date(2026, 8, 1)),
            Followup("due", "next_review_due", date(2026, 8, 1)),
        ]

        report = build_followups_report(items, date(2026, 8, 1))
        proposals = report.split("## Stewardからのご提案", maxsplit=1)[1]

        self.assertIn("正本への反映待ち", report)
        self.assertIn("`local_reflection_pending`", report)
        self.assertEqual(proposals.count("`same`:"), 1)
        self.assertLess(proposals.index("`same`:"), proposals.index("`receipt`:"))
        self.assertLess(proposals.index("`receipt`:"), proposals.index("`check`:"))
        self.assertNotIn("`unknown`:", proposals)
        self.assertNotIn("`due`:", proposals)
        self.assertIn("機械的な確認順", proposals)
        self.assertIn("プロジェクトの実状態を読んだ判定ではありません", proposals)
        self.assertIn("残る 2 プロジェクトも候補として保持", proposals)

    def test_owner_urgent_item_survives_future_date_and_whole_list_selection(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["current", "active", "2026-09-01"],
                    ["urgent", "active", "2026-09-01"],
                ],
                event_rows=[
                    [
                        "urgent",
                        "受領済み",
                        "反映待ち",
                        "担当確認中",
                        "2026-08-29",
                        "緊急",
                        "クレジット消費が増え続ける",
                        "担当が正規の保存先を確認したら直ちに保存する",
                        "-",
                        "該当なし",
                    ]
                ],
            )

            items = select_followups(path, date(2026, 8, 23))
            report = build_followups_report(items, date(2026, 8, 23))

            self.assertIn(
                Followup("urgent", "owner_urgency_urgent"),
                items,
            )
            self.assertNotIn(
                Followup("urgent", "next_check_due", date(2026, 8, 29)),
                items,
            )
            self.assertIn("指定された対象一覧全体", report)
            self.assertNotIn("オーナーが今することがない", report)

    def test_cross_project_rollout_selects_missing_and_unconfirmed_projects(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[
                    ["alpha", "active", "2026-09-01"],
                    ["beta", "active", "2026-09-01"],
                    ["gamma", "active", "2026-09-01"],
                ],
                event_rows=[
                    [
                        "alpha",
                        "受領済み",
                        "反映確認済み",
                        "なし",
                        "再発時",
                        "通常",
                        "横断的な読み取り削減",
                        "なし",
                        "live-state-budget",
                        "対応済み",
                    ],
                    [
                        "beta",
                        "受領済み",
                        "反映確認済み",
                        "なし",
                        "確認完了時",
                        "通常",
                        "横断的な読み取り削減",
                        "対象か根拠から確認する",
                        "live-state-budget",
                        "未確認",
                    ],
                ],
            )

            items = select_followups(path, date(2026, 8, 23))

            self.assertIn(
                Followup("beta", "cross_project_coverage_unconfirmed"),
                items,
            )
            self.assertIn(
                Followup("gamma", "cross_project_coverage_missing"),
                items,
            )

    def test_open_item_without_next_action_remains_a_candidate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[["alpha", "active", "2026-09-01"]],
                event_rows=[[
                    "alpha", "受領済み", "反映待ち", "担当確認中", "再開時",
                    "通常", "保存先の確認待ち", "なし", "-", "該当なし",
                ]],
            )

            items = select_followups(path, date(2026, 8, 23))

            self.assertIn(Followup("alpha", "next_action_missing"), items)

    def test_report_requires_closure_instead_of_recording_only(self) -> None:
        report = build_followups_report(
            [Followup("alpha", "next_review_due", date(2026, 8, 1))],
            date(2026, 8, 1),
        )

        self.assertIn("現在の状態宣言を続けるか見直す案", report)
        self.assertIn("記録または通知しただけでは完了にしません", report)
        self.assertIn("推奨を添えた質問を1件だけ", report)
        self.assertIn("同じ基準日で再選別", report)
        self.assertIn("候補を消すためだけの日付変更はしません", report)
        self.assertIn("項目自体は未完了のまま", report)

    def test_unconfirmed_reflection_proposal_does_not_assume_receipt(self) -> None:
        report = build_followups_report(
            [
                Followup("alpha", "parent_receipt_unreceived"),
                Followup("alpha", "local_reflection_unconfirmed"),
            ],
            date(2026, 8, 1),
        )

        proposals = report.split("## Stewardからのご提案", maxsplit=1)[1]
        self.assertEqual(proposals.count("`alpha`:"), 1)
        self.assertIn("変更連絡が正本へ影響するか", proposals)
        self.assertIn("受領状態は別に確認します", proposals)
        self.assertNotIn("受領済みの内容", proposals)

    def test_every_reason_has_guidance_and_unknown_reason_fails_closed(self) -> None:
        reasons = [
            "owner_urgency_urgent",
            "owner_urgency_priority",
            "cross_project_coverage_missing",
            "cross_project_coverage_unconfirmed",
            "urgency_unknown",
            "next_action_missing",
            "local_reflection_pending",
            "local_reflection_unconfirmed",
            "parent_receipt_unreceived",
            "parent_receipt_unknown",
            "confirmation_target_unknown",
            "next_check_due",
            "shallow_state_unknown",
            "next_review_due",
            "review_deadline_missing",
        ]

        report = build_followups_report(
            [Followup(f"project-{index}", reason) for index, reason in enumerate(reasons)],
            date(2026, 8, 1),
        )
        for reason in reasons:
            self.assertIn(f"`{reason}`", report)

        with self.assertRaisesRegex(ValueError, "提案が定義されていません"):
            build_followups_report(
                [Followup("alpha", "PRIVATE_UNKNOWN_REASON")],
                date(2026, 8, 1),
            )

    def test_legacy_english_headers_remain_readable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_headers=["Project", "導入状態", "浅い状態", "Next review"],
                target_rows=[["alpha", "導入済み", "active", "2026-08-01"]],
                event_headers=[
                    "Project",
                    "Parent receipt",
                    "Local reflection",
                    "Pending / Owner",
                    "Next check",
                    "緊急性",
                    "緊急性の理由",
                    "次の行動 / 戻る条件",
                    "横断事項",
                    "横断対応",
                ],
                event_rows=[[
                    "alpha", "未受領", "反映待ち", "なし", "2026-08-01",
                    "通常", "定期確認", "受領確認", "-", "該当なし",
                ]],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertIn("next_review_due", [item.reason for item in items])
            self.assertIn("parent_receipt_unreceived", [item.reason for item in items])
            self.assertIn("local_reflection_pending", [item.reason for item in items])

    def test_japanese_and_legacy_headers_can_be_mixed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_headers=["Project", "導入状態", "浅い状態", "次回確認"],
                target_rows=[["alpha", "導入済み", "active", "2026-08-01"]],
                event_headers=[
                    "プロジェクト",
                    "Parent receipt",
                    "正本への反映",
                    "Pending / Owner",
                    "次回確認",
                    "緊急性",
                    "緊急性の理由",
                    "次の行動 / 戻る条件",
                    "横断事項",
                    "横断対応",
                ],
                event_rows=[[
                    "alpha", "未受領", "反映待ち", "なし", "2026-08-01",
                    "通常", "定期確認", "受領確認", "-", "該当なし",
                ]],
            )

            items = select_followups(path, date(2026, 8, 1))

            self.assertIn("next_review_due", [item.reason for item in items])
            self.assertIn("parent_receipt_unreceived", [item.reason for item in items])
            self.assertIn("local_reflection_pending", [item.reason for item in items])

    def test_legacy_date_headers_are_not_accepted_in_the_wrong_table(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrong_target = _write_list(
                root,
                target_headers=["Project", "浅い状態", "Next check"],
                target_rows=[["alpha", "active", "2026-08-01"]],
                event_rows=[],
            )
            wrong_event = _write_list(
                root,
                filename="wrong-event.md",
                target_rows=[["alpha", "active", "2026-08-01"]],
                event_headers=[
                    "Project",
                    "Parent receipt",
                    "Local reflection",
                    "Pending / Owner",
                    "Next review",
                ],
                event_rows=[["alpha", "未受領", "反映待ち", "なし", "2026-08-01"]],
            )

            with self.assertRaises(FollowupInputError):
                select_followups(wrong_target, date(2026, 8, 1))
            with self.assertRaises(FollowupInputError):
                select_followups(wrong_event, date(2026, 8, 1))

    def test_list_without_urgency_and_cross_project_columns_fails_closed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_headers=["プロジェクト", "導入状態", "浅い状態", "次回確認"],
                target_rows=[["alpha", "導入済み", "active", "2026-09-01"]],
                event_headers=[
                    "プロジェクト",
                    "オーナー付きStewardの受領",
                    "正本への反映",
                    "判断待ち / 確認先",
                    "次回確認",
                ],
                event_rows=[],
            )

            with self.assertRaises(FollowupInputError):
                select_followups(path, date(2026, 8, 23))

    def test_target_project_must_be_unique_but_event_history_may_repeat(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate_target = _write_list(
                root,
                target_rows=[
                    ["alpha", "active", "2026-08-02"],
                    ["alpha", "active", "2026-08-03"],
                ],
                event_rows=[],
            )
            with self.assertRaises(FollowupInputError):
                select_followups(duplicate_target, date(2026, 8, 1))

            repeated_event = _write_list(
                root,
                filename="events.md",
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_rows=[
                    ["alpha", "未受領", "未確認", "なし", "次回日次確認"],
                    ["alpha", "未受領", "未確認", "なし", "次回日次確認"],
                    ["alpha", "不明", "反映待ち", "なし", "次回日次確認"],
                ],
            )
            items = select_followups(repeated_event, date(2026, 8, 1))

            self.assertEqual(len(items), 4)

    def test_missing_duplicate_and_malformed_structure_fail_closed(self) -> None:
        cases = {
            "missing-event": "\n".join(
                [
                    "## 対象",
                    "",
                    _row(TARGET_HEADERS),
                    _separator(TARGET_HEADERS),
                    "",
                ]
            ),
            "duplicate-column": "\n".join(
                [
                    "## 対象",
                    "",
                    _row([*TARGET_HEADERS, "Project"]),
                    _separator([*TARGET_HEADERS, "Project"]),
                    "",
                    "## event受領記録",
                    "",
                    _row(EVENT_HEADERS),
                    _separator(EVENT_HEADERS),
                    "",
                ]
            ),
            "malformed-row": "\n".join(
                [
                    "## 対象",
                    "",
                    _row(TARGET_HEADERS),
                    _separator(TARGET_HEADERS),
                    "| alpha | active |",
                    "",
                    "## event受領記録",
                    "",
                    _row(EVENT_HEADERS),
                    _separator(EVENT_HEADERS),
                    "",
                ]
            ),
            "missing-leading-pipe": "\n".join(
                [
                    "## 対象",
                    "",
                    _row(TARGET_HEADERS),
                    _separator(TARGET_HEADERS),
                    "alpha | 導入済み | active | 2026-07-01 |",
                    "",
                    "## event受領記録",
                    "",
                    _row(EVENT_HEADERS),
                    _separator(EVENT_HEADERS),
                    "",
                ]
            ),
        }
        with TemporaryDirectory() as temp_dir:
            for name, text in cases.items():
                with self.subTest(name=name):
                    path = Path(temp_dir) / f"{name}.md"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(FollowupInputError):
                        select_followups(path, date(2026, 8, 1))

            prose_path = _write_list(
                Path(temp_dir),
                filename="prose-with-pipe.md",
                target_rows=[["alpha", "active", "2026-08-01"]],
                event_rows=[],
            )
            prose_text = prose_path.read_text(encoding="utf-8").replace(
                "| alpha | active | 2026-08-01 |\n\n## event受領記録",
                "| alpha | active | 2026-08-01 |\nNote A | B\n## event受領記録",
            )
            prose_path.write_text(prose_text, encoding="utf-8")
            items = select_followups(prose_path, date(2026, 8, 1))
            self.assertEqual([item.reason for item in items], ["next_review_due"])

    def test_unknown_enum_and_empty_trigger_fail_closed(self) -> None:
        cases = [
            [["alpha", "TBD", "反映待ち", "なし", "再開時"]],
            [["alpha", "受領済み", "TBD", "なし", "再開時"]],
            [["alpha", "受領済み", "反映不要", "なし", ""]],
            [["alpha", "受領済み", "反映不要", "", "再開時"]],
        ]
        with TemporaryDirectory() as temp_dir:
            for index, event_rows in enumerate(cases):
                with self.subTest(index=index):
                    path = _write_list(
                        Path(temp_dir),
                        filename=f"case-{index}.md",
                        target_rows=[["alpha", "active", "2026-08-02"]],
                        event_rows=event_rows,
                    )
                    with self.assertRaises(FollowupInputError):
                        select_followups(path, date(2026, 8, 1))

            blank_shallow = _write_list(
                Path(temp_dir),
                filename="blank-shallow.md",
                target_rows=[["alpha", "", "2026-08-02"]],
                event_rows=[],
            )
            with self.assertRaises(FollowupInputError):
                select_followups(blank_shallow, date(2026, 8, 1))

    def test_later_record_empty_value_does_not_reuse_previous_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty_later_record = _write_list(
                root,
                target_rows=[
                    ["alpha", "active", "2026-08-02"],
                    ["beta", "", "2026-08-03"],
                ],
                event_rows=[],
            )

            with self.assertRaisesRegex(FollowupInputError, "浅い状態が空"):
                select_followups(empty_later_record, date(2026, 8, 1))

            explicit_unknown = _write_list(
                root,
                filename="explicit-unknown.md",
                target_rows=[
                    ["alpha", "active", "2026-08-02"],
                    ["beta", "不明", "2026-08-03"],
                ],
                event_rows=[],
            )
            items = select_followups(explicit_unknown, date(2026, 8, 1))

            self.assertEqual(
                [(item.project, item.reason) for item in items],
                [("beta", "shallow_state_unknown")],
            )

    def test_date_like_invalid_and_template_values_fail_closed(self) -> None:
        values = ["2026/08/01", "２０２６－０８－０１", "2026-13-01", "YYYY-MM-DD"]
        with TemporaryDirectory() as temp_dir:
            for index, value in enumerate(values):
                with self.subTest(value=value):
                    path = _write_list(
                        Path(temp_dir),
                        filename=f"date-{index}.md",
                        target_rows=[["alpha", "active", value]],
                        event_rows=[],
                    )
                    with self.assertRaises(FollowupInputError):
                        select_followups(path, date(2026, 8, 1))

    def test_symlink_is_not_read(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.md"
            with (
                patch("pma.followups.Path.is_symlink", return_value=True),
                patch(
                    "pma.followups.Path.read_text",
                    side_effect=AssertionError("symlink target was read"),
                ),
            ):
                with self.assertRaises(FollowupInputError):
                    select_followups(path, date(2026, 8, 1))

    def test_cli_does_not_expose_non_output_cells_or_change_the_list(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = _write_list(
                root,
                target_headers=[
                    "プロジェクト",
                    "Locators",
                    "導入状態",
                    "浅い状態",
                    "次回確認",
                    "Local evidence",
                ],
                target_rows=[
                    [
                        "alpha", "PRIVATE_LOCATOR", "導入済み", "active",
                        "2026-08-01", "PRIVATE_EVIDENCE",
                    ]
                ],
                event_headers=[
                    "プロジェクト",
                    "オーナー付きStewardの受領",
                    "正本への反映",
                    "Shallow summary",
                    "判断待ち / 確認先",
                    "次回確認",
                    "Evidence",
                    "緊急性",
                    "緊急性の理由",
                    "次の行動 / 戻る条件",
                    "横断事項",
                    "横断対応",
                ],
                event_rows=[
                    [
                        "alpha", "受領済み", "反映不要", "PRIVATE_SUMMARY", "なし", "再開時",
                        "PRIVATE_EVENT", "通常", "PRIVATE_URGENCY_REASON", "なし", "-", "該当なし",
                    ]
                ],
            )
            before = path.read_bytes()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["followups", "--list", str(path), "--as-of", "2026-08-01"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("alpha", stdout.getvalue())
            self.assertIn("next_review_due", stdout.getvalue())
            for private_value in (
                "PRIVATE_LOCATOR",
                "PRIVATE_EVIDENCE",
                "PRIVATE_SUMMARY",
                "PRIVATE_EVENT",
                "PRIVATE_URGENCY_REASON",
            ):
                self.assertNotIn(private_value, stdout.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_cli_error_does_not_quote_broken_or_private_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_headers=[
                    "プロジェクト",
                    "オーナー付きStewardの受領",
                    "正本への反映",
                    "Private",
                    "判断待ち / 確認先",
                    "次回確認",
                    "緊急性",
                    "緊急性の理由",
                    "次の行動 / 戻る条件",
                    "横断事項",
                    "横断対応",
                ],
                event_rows=[
                    [
                        "alpha", "SECRET_BAD_VALUE", "反映不要", "SECRET_DETAIL", "なし", "再開時",
                        "通常", "SECRET_REASON", "なし", "-", "該当なし",
                    ]
                ],
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["followups", "--list", str(path), "--as-of", "2026-08-01"]
                )

            self.assertNotEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertNotIn("SECRET_BAD_VALUE", stderr.getvalue())
            self.assertNotIn("SECRET_DETAIL", stderr.getvalue())

    def test_cli_fails_closed_when_guidance_is_not_defined(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = _write_list(
                Path(temp_dir),
                target_rows=[["alpha", "active", "2026-08-01"]],
                event_rows=[],
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch(
                    "pma.cli.build_followups_report",
                    side_effect=ValueError("PRIVATE_INTERNAL_REASON"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["followups", "--list", str(path), "--as-of", "2026-08-01"]
                )

            self.assertNotEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("提案を安全に作成できませんでした", stderr.getvalue())
            self.assertNotIn("PRIVATE_INTERNAL_REASON", stderr.getvalue())

    def test_python_module_process_uses_completion_exit_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = _write_list(
                root,
                target_rows=[["alpha", "active", "2026-08-01"]],
                event_rows=[],
            )
            before = path.read_bytes()

            completed = _run_followups_process(path)

            self.assertEqual(completed.returncode, 0)
            self.assertIn("next_review_due", completed.stdout)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(path.read_bytes(), before)

            invalid_path = _write_list(
                root,
                filename="invalid.md",
                target_rows=[["alpha", "active", "2026-08-02"]],
                event_rows=[
                    ["alpha", "SECRET_BAD_VALUE", "反映不要", "なし", "再開時"]
                ],
            )
            failed = _run_followups_process(invalid_path)

            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, "")
            self.assertNotIn("SECRET_BAD_VALUE", failed.stderr)


def _write_list(
    root: Path,
    *,
    target_rows: list[list[str]],
    event_rows: list[list[str]],
    filename: str = "project-list.md",
    target_headers: list[str] | None = None,
    event_headers: list[str] | None = None,
) -> Path:
    if target_headers is None:
        target_headers = TARGET_HEADERS
        target_rows = [
            [row[0], "導入済み", *row[1:]] if len(row) == 3 else row
            for row in target_rows
        ]
    if event_headers is None:
        event_headers = EVENT_HEADERS
        event_rows = [
            [
                *row,
                "通常",
                "定期確認",
                "確認先で結果を確認する",
                "-",
                "該当なし",
            ]
            if len(row) == 5
            else row
            for row in event_rows
        ]
    lines = [
        "# Private parent list",
        "",
        "## 対象",
        "",
        _row(target_headers),
        _separator(target_headers),
        *(_row(row) for row in target_rows),
        "",
        "## event受領記録",
        "",
        _row(event_headers),
        _separator(event_headers),
        *(_row(row) for row in event_rows),
        "",
    ]
    path = root / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _separator(headers: list[str]) -> str:
    return _row(["---"] * len(headers))


def _run_followups_process(path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    source_path = str(ROOT / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        os.pathsep.join([source_path, existing_pythonpath])
        if existing_pythonpath
        else source_path
    )
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pma",
            "followups",
            "--list",
            str(path),
            "--as-of",
            "2026-08-01",
        ],
        cwd=path.parent,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )


if __name__ == "__main__":
    unittest.main()
