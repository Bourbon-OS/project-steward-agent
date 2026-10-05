from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pma.config import ConfigResult, default_config
from pma.fixed_input import FixedInputObservation
from pma.git_utils import GitInfo, GitLineObservation
from pma.report import build_markdown_report
from pma.scan import (
    FilePresence,
    KeywordMatch,
    make_overall_judgment,
    Risk,
    ScanResult,
    SourceOfTruthPresence,
)
from pma.status import ProjectStatus


class ReportTests(unittest.TestCase):
    def _result(
        self,
        risks: list[Risk],
        max_priority_actions: int = 3,
    ) -> ScanResult:
        root = Path("/example/project")
        return ScanResult(
            requested_path=root,
            project_path=root,
            run_at=datetime(2026, 6, 14, 12, 0).astimezone(),
            git=GitInfo(
                is_repo=True,
                root=root,
                status_lines=["?? memo.md"],
                last_commit_at="2026-06-14T00:00:00+09:00",
                head_commit="0123456789abcdef0123456789abcdef01234567",
                branch="main",
            ),
            config_result=ConfigResult(
                path=root / ".project-agent.yml",
                exists=True,
                config=replace(
                    default_config(),
                    max_priority_actions=max_priority_actions,
                ),
                warnings=[],
            ),
            project_status=ProjectStatus(
                path=root / "PROJECT_STATUS.md",
                exists=True,
                status="active",
                last_updated="2026-06-14",
                last_reviewed="2026-06-14",
                next_review="2026-06-21",
                warnings=[],
            ),
            fixed_input=FixedInputObservation(
                scope_state="unconfirmed",
                measurement_state="unconfirmed",
                files=(),
                read_when_needed_files=(),
                reference_files=(),
                character_count=None,
                line_count=None,
                token_count=None,
                token_encoding="o200k_base",
                target_chars=8192,
                target_lines=192,
                high_cost_chars=16384,
                high_cost_lines=384,
                exception_reason=None,
                exception_review_condition=None,
            ),
            files={
                "README.md": FilePresence("README.md", True),
                "PROJECT_STATUS.md": FilePresence("PROJECT_STATUS.md", True),
                ".project-agent.yml": FilePresence(".project-agent.yml", True),
            },
            source_of_truth={
                "README.md": SourceOfTruthPresence(
                    path="README.md",
                    exists=True,
                    readme_linked=True,
                    is_readme=True,
                ),
                "docs/": SourceOfTruthPresence(
                    path="docs/",
                    exists=True,
                    readme_linked=True,
                ),
            },
            changed_files=[],
            untracked_files=["?? memo.md"],
            keyword_matches=[
                KeywordMatch(path="notes.md", line_number=3, keyword="TODO")
            ],
            risks=risks,
            overall_judgment=make_overall_judgment(risks),
            consultation="まだGit管理に入っていないファイルがあります。次は、Gitに入れる候補をこちらで整理してよろしいですか？",
            status_line_observation=GitLineObservation(
                state="confirmed",
                commit_at="2026-06-01T00:00:00+09:00",
                commit="0123456789abcdef0123456789abcdef01234567",
            ),
        )

    def test_report_includes_required_sections_and_single_consultation(self) -> None:
        root = Path("/example/project")
        risk = Risk(
            priority=4,
            code="untracked_files",
            severity="high",
            subject="working tree",
            title="未追跡ファイルがあります",
            evidence="1 件の未追跡ファイルがあります。",
            interpretation="Git履歴だけでは再現できない可能性があります。",
            suggestion="まず分類案を作るのがよさそうです。",
        )
        result = self._result([risk])

        report = build_markdown_report(result)

        self.assertIn("## 全体判断", report)
        self.assertIn("- continuity: `at_risk`", report)
        self.assertIn("## 観測スナップショット", report)
        self.assertIn("- 観測の一貫性: 確認済み", report)
        self.assertIn("## Git状態の要約", report)
        self.assertIn("- Git状態: 確認済み", report)
        self.assertIn(
            "- HEAD commit: `0123456789abcdef0123456789abcdef01234567`",
            report,
        )
        self.assertIn("- branch: `main`", report)
        self.assertIn("- working tree: dirty", report)
        self.assertIn("- 要確認の未追跡: 1 件", report)
        self.assertIn("- 設定上の背景にある未追跡: なし", report)
        self.assertIn("## 管理ファイルの有無", report)
        self.assertIn("## 状態ファイルの読み取り結果", report)
        self.assertIn("## 正本導線", report)
        self.assertIn("`README.md`: あり / README導線: README自身", report)
        self.assertIn("`docs/`: あり / README導線: あり", report)
        self.assertIn(f"- 状態ファイル: `{root / 'PROJECT_STATUS.md'}`", report)
        self.assertIn(
            "- status継続期間: 13日以上（2026-06-01T00:00:00+09:00以降",
            report,
        )
        self.assertIn("- `notes.md:3`: `TODO`", report)
        self.assertIn("- 候補ファイル数: 1", report)
        self.assertIn("- 今回変更された候補: 0 ファイル", report)
        self.assertIn("- 既存不変の候補: 1 ファイル", report)
        self.assertIn("- code: `untracked_files`", report)
        self.assertIn("- severity: `high`", report)
        self.assertIn("- 対象: working tree", report)
        self.assertIn(
            "- 解釈: Git履歴だけでは再現できない可能性があります。",
            report,
        )
        self.assertIn("- 状態: 未決", report)
        self.assertIn("## ご確認いただきたいこと", report)
        self.assertIn("## Stewardからのご提案", report)
        self.assertEqual(report.count("## Stewardからのご提案"), 1)
        self.assertNotIn("どうしますか", report)

    def test_status_duration_uses_elapsed_time_not_calendar_boundary(self) -> None:
        result = self._result([])
        jst = timezone(timedelta(hours=9))
        result = replace(
            result,
            run_at=datetime(2026, 8, 1, 0, 1, tzinfo=jst),
            status_line_observation=GitLineObservation(
                state="confirmed",
                commit_at="2026-07-31T23:59:00+09:00",
                commit="0123456789abcdef0123456789abcdef01234567",
            ),
        )

        report = build_markdown_report(result)

        self.assertIn("- status継続期間: 0日以上", report)
        self.assertNotIn("- status継続期間: 1日以上", report)

    def test_future_status_history_timestamp_is_not_asserted(self) -> None:
        result = self._result([])
        jst = timezone(timedelta(hours=9))
        result = replace(
            result,
            run_at=datetime(2026, 8, 1, 0, 0, tzinfo=jst),
            status_line_observation=GitLineObservation(
                state="confirmed",
                commit_at="2026-08-01T00:01:00+09:00",
                commit="0123456789abcdef0123456789abcdef01234567",
            ),
        )

        report = build_markdown_report(result)

        self.assertIn(
            "- status継続期間: 未確認（Git日時が実行日時より未来）",
            report,
        )

    def test_git_unavailable_counts_are_reported_as_unconfirmed(self) -> None:
        result = self._result([])
        unavailable_git = replace(
            result.git,
            is_repo=False,
            status_lines=[],
            last_commit_at=None,
            head_commit=None,
            branch=None,
            error="git status timed out after 30 seconds",
            error_kind="unavailable",
        )
        result = replace(
            result,
            git=unavailable_git,
            changed_files=[],
            untracked_files=[],
            keyword_matches=[],
        )

        report = build_markdown_report(result)

        self.assertIn("- リポジトリルート: 未確認", report)
        self.assertIn("- 未コミット変更: 未確認", report)
        self.assertIn("- 未追跡ファイル: 未確認", report)
        self.assertIn("- 要確認の未追跡: 未確認", report)
        self.assertIn("- 設定上の背景にある未追跡: 未確認", report)
        self.assertIn("- 候補ファイル数: 未確認", report)
        self.assertIn("- 今回変更された候補: 未確認", report)
        self.assertIn("- 既存不変の候補: 未確認", report)
        self.assertIn(
            "Git状態が未確認のため、working treeの変更は確認できません。",
            report,
        )
        self.assertNotIn("working tree に表示対象の変更はありません。", report)

    def test_overall_judgment_distinguishes_continuity_states(self) -> None:
        low = Risk(
            priority=8,
            code="footwork_keywords",
            severity="low",
            subject="今回変更されたファイル",
            title="足場キーワードがあります",
            evidence="1件あります。",
            interpretation="確認候補です。",
            suggestion="確認します。",
        )
        at_risk = replace(
            low,
            priority=5,
            code="uncommitted_changes",
            severity="medium",
            title="未コミット変更があります",
        )
        unknown = replace(
            low,
            priority=1,
            code="git_state_unavailable",
            severity="critical",
            title="Git状態を確認できませんでした",
        )
        partial_status_unknown = replace(
            low,
            priority=7,
            code="invalid_status_dates",
            severity="medium",
            title="状態ファイルの日付が不正です",
        )

        cases = [
            ([], "ready", "確認できた範囲では"),
            ([low], "ready", "低優先の確認候補"),
            ([at_risk], "at_risk", "未コミット変更があります"),
            (
                [partial_status_unknown],
                "at_risk",
                "状態ファイルの日付が不正です",
            ),
            ([unknown, at_risk], "unknown", "Git状態を確認できませんでした"),
        ]
        for risks, expected_continuity, expected_reason in cases:
            with self.subTest(continuity=expected_continuity):
                judgment = make_overall_judgment(risks)
                self.assertEqual(judgment.continuity, expected_continuity)
                self.assertIn(expected_reason, judgment.reason)

    def test_critical_findings_bypass_priority_limit(self) -> None:
        critical_one = Risk(
            priority=1,
            code="critical_one",
            severity="critical",
            subject="Git状態",
            title="重大事項1",
            evidence="Git状態を確認できません。",
            interpretation="観測範囲が未確認です。",
            suggestion="再確認します。",
        )
        critical_two = Risk(
            priority=2,
            code="critical_two",
            severity="critical",
            subject="状態文書",
            title="重大事項2",
            evidence="状態文書を確認できません。",
            interpretation="現在状態が未確認です。",
            suggestion="状態文書を確認します。",
        )
        regular = Risk(
            priority=3,
            code="regular",
            severity="high",
            subject="README.md",
            title="通常事項",
            evidence="READMEを確認できません。",
            interpretation="入口が未確認です。",
            suggestion="READMEを確認します。",
        )
        result = self._result(
            [critical_one, critical_two, regular],
            max_priority_actions=1,
        )

        report = build_markdown_report(result)
        priority_section = report.split("## 優先対応", 1)[1].split(
            "## ご確認いただきたいこと",
            1,
        )[0]

        self.assertIn("重大事項1", priority_section)
        self.assertIn("重大事項2", priority_section)
        self.assertIn("通常事項", priority_section)


if __name__ == "__main__":
    unittest.main()
