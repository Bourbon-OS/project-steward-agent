from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pma.config import (
    DEFAULT_FIXED_INPUT_HIGH_CHARS,
    DEFAULT_FIXED_INPUT_HIGH_LINES,
    DEFAULT_FIXED_INPUT_TARGET_CHARS,
    DEFAULT_FIXED_INPUT_TARGET_LINES,
    DEFAULT_STATUS_MAX_CHARS,
    DEFAULT_STATUS_MAX_LINES,
    MAX_CONFIG_BYTES,
    _load_simple_yaml,
    load_config,
)
from pma.git_utils import (
    GitCommandUnavailable,
    GitInfo,
    _format_git_timestamp,
    collect_git_info,
    collect_git_line_observation,
)
from pma.report import build_markdown_report
from pma.scan import (
    MAX_TEXT_FILE_BYTES,
    _capture_observation_path_state,
    _collect_observation_paths,
    find_keyword_matches,
    partition_untracked_files,
    scan_path,
)


class ScanTests(unittest.TestCase):
    def test_non_git_path_reports_single_guided_consultation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = scan_path(Path(temp_dir))
            report = build_markdown_report(result)

            self.assertFalse(result.git.is_repo)
            self.assertEqual(result.risks[0].code, "not_git_repo")
            self.assertIn("再確認してよろしいですか", result.consultation)
            self.assertNotIn("どうしますか", result.consultation)
            self.assertIn("- リポジトリルート: 対象外", report)
            self.assertIn("- HEAD commit: 対象外", report)
            self.assertIn("- branch: 対象外", report)
            self.assertIn("- 未コミット変更: 対象外", report)
            self.assertIn("- 未追跡ファイル: 対象外", report)
            self.assertIn("- 直近コミット日時: 対象外", report)
            self.assertIn("- 候補ファイル数: 対象外", report)
            self.assertIn(
                "Gitリポジトリではないため、working treeは対象外です。",
                report,
            )

    def test_git_state_unavailable_is_not_reported_as_non_git(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            error = (
                "fatal: detected dubious ownership in repository at "
                "'C:/Users/example-user/Projects/example-project'"
            )

            with (
                patch(
                    "pma.scan.collect_git_info",
                    return_value=GitInfo(
                        is_repo=False,
                        root=root,
                        status_lines=[],
                        last_commit_at=None,
                        error=error,
                        error_kind="unavailable",
                    ),
                ),
                patch("pma.scan.find_keyword_matches") as keyword_scan,
            ):
                result = scan_path(root)

            self.assertEqual(result.risks[0].code, "git_state_unavailable")
            self.assertEqual(result.risks[0].title, "Git状態を確認できませんでした")
            self.assertNotEqual(result.risks[0].title, "Git リポジトリではありません")
            self.assertIn("safe.directory", result.consultation)
            keyword_scan.assert_not_called()

    def test_git_timeout_is_reported_as_unavailable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            timeout = subprocess.TimeoutExpired(
                cmd=["git", "-C", str(root), "rev-parse"],
                timeout=30,
            )

            with patch(
                "pma.git_utils.subprocess.run",
                side_effect=timeout,
            ):
                git = collect_git_info(root)

            self.assertFalse(git.is_repo)
            self.assertEqual(git.error_kind, "unavailable")
            self.assertIn("timed out", git.error or "")

    def test_keyword_git_failure_is_reported_without_broadening_scan(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))

            with patch(
                "pma.scan.find_keyword_matches",
                side_effect=GitCommandUnavailable("git ls-files timed out"),
            ):
                result = scan_path(root)

            risk = next(
                risk
                for risk in result.risks
                if risk.code == "keyword_scan_unavailable"
            )
            report = build_markdown_report(result)
            self.assertIn("timed out", risk.evidence)
            self.assertEqual(result.keyword_matches, [])
            self.assertIn("- 候補ファイル数: 未確認", report)
            self.assertIn("- 今回変更された候補: 未確認", report)
            self.assertIn("- 既存不変の候補: 未確認", report)

    def test_scan_git_repo_detects_untracked_file(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "scratch.md", "temporary note\n")

            result = scan_path(root)

            self.assertTrue(result.git.is_repo)
            self.assertEqual(len(result.git.head_commit or ""), 40)
            self.assertTrue(result.git.branch)
            self.assertEqual(result.project_status.status, "active")
            self.assertTrue(any("scratch.md" in item for item in result.untracked_files))
            self.assertEqual(result.risks[0].code, "untracked_files")
            self.assertEqual(
                result.consultation,
                "まだGit管理に入っていないファイルがあります。次は、Gitに入れる候補をこちらで整理してよろしいですか？",
            )

    def test_untracked_directory_is_counted_by_file(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            scratch = root / "scratch"
            scratch.mkdir()
            for index in range(3):
                _write(scratch / f"note-{index}.md", "temporary note\n")

            result = scan_path(root)
            risk = next(
                risk for risk in result.risks if risk.code == "untracked_files"
            )

            self.assertEqual(len(result.untracked_files), 3)
            self.assertIn("3 件", risk.evidence)

    def test_excluded_untracked_files_are_background_not_risk(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  exclude_paths:",
                        "    - FABLE_*.md",
                        "    - outputs/**",
                        "",
                    ]
                ),
            )
            _run(root, ["git", "add", ".project-agent.yml"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "configure background paths",
                ],
            )
            output_dir = root / "outputs"
            output_dir.mkdir()
            _write(output_dir / "generated.md", "generated output\n")
            _write(root / "FABLE_REVIEW.md", "review material\n")

            result = scan_path(root)
            report = build_markdown_report(result)

            self.assertEqual(len(result.untracked_files), 2)
            self.assertFalse(
                any(risk.code == "untracked_files" for risk in result.risks)
            )
            self.assertIn("要確認の未追跡: なし", report)
            self.assertIn("設定上の背景にある未追跡: 2 件", report)

    def test_trailing_slash_excludes_untracked_files_under_directory(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  exclude_paths:",
                        "    - outputs/",
                        "",
                    ]
                ),
            )
            _run(root, ["git", "add", ".project-agent.yml"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "configure trailing slash exclusion",
                ],
            )
            output_dir = root / "outputs"
            output_dir.mkdir()
            _write(output_dir / "generated.md", "generated output\n")

            result = scan_path(root)
            report = build_markdown_report(result)

            self.assertEqual(len(result.untracked_files), 1)
            self.assertFalse(
                any(risk.code == "untracked_files" for risk in result.risks)
            )
            self.assertIn("要確認の未追跡: なし", report)
            self.assertIn("設定上の背景にある未追跡: 1 件", report)

    def test_trailing_slash_pattern_does_not_overmatch_other_paths(self) -> None:
        actionable, background = partition_untracked_files(
            [
                "?? note.md",
                "?? outputs",
                "?? outputs-old/file.md",
                "?? nested/outputs/file.md",
            ],
            ["*.md/", "outputs/"],
        )

        self.assertEqual(
            actionable,
            [
                "?? note.md",
                "?? outputs",
                "?? outputs-old/file.md",
                "?? nested/outputs/file.md",
            ],
        )
        self.assertEqual(background, [])

    def test_only_nonexcluded_untracked_files_are_actionable(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  exclude_paths:",
                        "    - outputs/**",
                        "",
                    ]
                ),
            )
            _run(root, ["git", "add", ".project-agent.yml"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "configure background paths",
                ],
            )
            output_dir = root / "outputs"
            output_dir.mkdir()
            _write(output_dir / "generated.md", "generated output\n")
            _write(root / "new-note.md", "new note\n")

            result = scan_path(root)
            risk = next(
                risk for risk in result.risks if risk.code == "untracked_files"
            )
            report = build_markdown_report(result)

            self.assertIn("1 件", risk.evidence)
            self.assertIn("要確認の未追跡: 1 件", report)
            self.assertIn("設定上の背景にある未追跡: 1 件", report)

    def test_missing_config_does_not_guess_root_status_file(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _run(root, ["git", "init"])

            result = scan_path(root)

            self.assertEqual(result.risks[0].code, "missing_readme")
            self.assertFalse(
                any(risk.code == "missing_project_status" for risk in result.risks)
            )
            self.assertTrue(
                any(
                    risk.code == "fixed_input_scope_unconfirmed"
                    for risk in result.risks
                )
            )
            self.assertIn("README", result.consultation)
            self.assertFalse(
                any(risk.code == "missing_source_of_truth" for risk in result.risks)
            )

    def test_missing_configured_required_file_is_reported(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  required_files:",
                        "    - README.md",
                        "    - PROJECT_STATUS.md",
                        "    - docs/required.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            risk = next(
                risk
                for risk in result.risks
                if risk.code == "missing_required_files"
            )

            self.assertIn("docs/required.md", risk.evidence)

    def test_source_of_truth_directory_and_readme_link_are_recognized(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            docs = root / "docs"
            docs.mkdir()
            _write(docs / "guide.md", "# Guide\n")
            _write(root / "README.md", "# Example\n\nSee [guide](docs/guide.md).\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  source_of_truth:",
                        "    - README.md",
                        "    - docs/",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(result.source_of_truth["docs/"].exists)
            self.assertTrue(result.source_of_truth["docs/"].readme_linked)
            self.assertFalse(
                any(
                    risk.code
                    in {"missing_source_of_truth", "source_of_truth_not_linked"}
                    for risk in result.risks
                )
            )

    def test_missing_source_of_truth_is_reported_without_link_duplicate(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  source_of_truth:",
                        "    - README.md",
                        "    - docs/missing.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(
                any(risk.code == "missing_source_of_truth" for risk in result.risks)
            )
            self.assertFalse(
                any(
                    risk.code == "source_of_truth_not_linked"
                    for risk in result.risks
                )
            )

    def test_existing_source_of_truth_without_readme_link_is_reported(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            docs = root / "docs"
            docs.mkdir()
            _write(docs / "guide.md", "# Guide\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  source_of_truth:",
                        "    - README.md",
                        "    - docs/guide.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            risk = next(
                risk
                for risk in result.risks
                if risk.code == "source_of_truth_not_linked"
            )

            self.assertIn("docs/guide.md", risk.evidence)

    def test_source_of_truth_outside_project_is_not_accepted(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            root = _make_repo(root)
            _write(base / "outside.md", "# Outside\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  source_of_truth:",
                        "    - README.md",
                        "    - ../outside.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertFalse(result.source_of_truth["../outside.md"].exists)
            self.assertTrue(
                any(risk.code == "missing_source_of_truth" for risk in result.risks)
            )

    def test_missing_project_agent_yml_warns_but_continues(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir), include_config=False)

            with patch(
                "pma.scan.find_keyword_matches",
                wraps=find_keyword_matches,
            ) as keyword_scan:
                result = scan_path(root)

            self.assertTrue(result.git.is_repo)
            self.assertEqual(result.config_result.load_state, "missing")
            self.assertIsNone(result.project_status.status)
            self.assertEqual(result.fixed_input.scope_state, "unconfirmed")
            self.assertTrue(any(risk.code == "config_warning" for risk in result.risks))
            keyword_scan.assert_called_once()

    def test_unavailable_config_stops_keyword_content_scan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / ".project-agent.yml", "[secret-value\n")

            with patch("pma.scan.find_keyword_matches") as keyword_scan:
                result = scan_path(root)
            report = build_markdown_report(result)

            self.assertEqual(result.config_result.load_state, "unavailable")
            self.assertEqual(result.risks[0].code, "config_unavailable")
            self.assertEqual(result.overall_judgment.continuity, "unknown")
            self.assertEqual(result.keyword_matches, [])
            keyword_scan.assert_not_called()
            self.assertIn("- 候補ファイル数: 未確認", report)
            self.assertIn("- 要確認の未追跡: 未確認", report)
            self.assertIn(
                "- 設定上の背景にある未追跡: 未確認",
                report,
            )
            self.assertIn(
                "- 状態ファイル: 未確認（設定ファイルを安全に使えないため）",
                report,
            )
            self.assertIn(
                "- 未確認（設定ファイルを安全に使えないため）",
                report,
            )
            self.assertIn(
                "working treeのpath表示は省略しました。",
                report,
            )
            self.assertFalse(
                any(
                    risk.code
                    in {
                        "missing_project_status",
                        "missing_required_files",
                        "missing_source_of_truth",
                        "untracked_files",
                    }
                    for risk in result.risks
                )
            )
            self.assertNotIn("secret-value", report)

    def test_non_git_config_unavailable_keeps_git_fields_not_applicable(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write(root / ".project-agent.yml", "[broken-config\n")

            result = scan_path(root)
            report = build_markdown_report(result)

            self.assertFalse(result.git.is_repo)
            self.assertEqual(result.config_result.load_state, "unavailable")
            self.assertIn("- 未追跡ファイル: 対象外", report)
            self.assertIn("- 要確認の未追跡: 対象外", report)
            self.assertIn(
                "- 設定上の背景にある未追跡: 対象外",
                report,
            )
            self.assertIn("- 候補ファイル数: 対象外", report)
            self.assertIn(
                "Gitリポジトリではないため、working treeは対象外です。",
                report,
            )

    def test_git_and_config_unavailable_do_not_claim_working_tree_change(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write(root / "README.md", "# Test\n")
            _write(root / ".project-agent.yml", "[broken-config\n")

            with patch(
                "pma.scan.collect_git_info",
                return_value=GitInfo(
                    is_repo=False,
                    root=root,
                    status_lines=[" M README.md"],
                    last_commit_at=None,
                    error="git status を確認できませんでした。",
                    error_kind="unavailable",
                ),
            ):
                result = scan_path(root)
            report = build_markdown_report(result)

            risk_codes = {risk.code for risk in result.risks}
            self.assertIn("git_state_unavailable", risk_codes)
            self.assertIn("config_unavailable", risk_codes)
            self.assertNotIn("uncommitted_changes", risk_codes)
            self.assertIn(
                "Git状態が未確認のため、working treeの変更は確認できません。",
                report,
            )
            self.assertNotIn(
                "設定ファイルを使用できないため、"
                "working treeのpath表示は省略しました。",
                report,
            )

    def test_non_utf8_config_is_unavailable_without_stopping_scan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            (root / ".project-agent.yml").write_bytes(b"\xff\xfe")

            result = scan_path(root)

            self.assertEqual(result.config_result.load_state, "unavailable")
            self.assertEqual(result.risks[0].code, "config_unavailable")
            self.assertEqual(result.overall_judgment.continuity, "unknown")

    def test_symlink_config_is_not_read(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write(root / ".project-agent.yml", "checks:\n")

            with (
                patch("pma.config.Path.is_symlink", return_value=True),
                patch(
                    "pma.config.Path.read_text",
                    side_effect=AssertionError("symlink target was read"),
                ),
            ):
                result = load_config(root)

            self.assertEqual(result.load_state, "unavailable")
            self.assertIn("symlink", result.warnings[0])

    def test_oversized_config_is_not_read(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".project-agent.yml").write_bytes(
                b"x" * (MAX_CONFIG_BYTES + 1)
            )

            result = load_config(root)

            self.assertEqual(result.load_state, "unavailable")
            self.assertIn("サイズ上限", result.warnings[0])

    def test_simple_yaml_parser_rejects_unsupported_top_level_values(self) -> None:
        invalid_values = (
            "[]\n",
            "false\n",
            "0\n",
            "[secret-value\n",
            "checks: [broken\n",
            "checks:\n  exclude_paths:\n    - [broken\n",
            "project:\n  status_file: 'unterminated\n",
        )
        for raw in invalid_values:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    _load_simple_yaml(raw)

    def test_simple_yaml_parser_supports_minimal_template_shape(self) -> None:
        data = _load_simple_yaml(
            "\n".join(
                [
                    "project:",
                    "  status_file: PROJECT_STATUS.md",
                    "checks:",
                    "  exclude_paths:",
                    "    - outputs/**",
                    "notes: |",
                    "  human-readable note",
                    "",
                ]
            )
        )

        self.assertEqual(
            data["project"]["status_file"],
            "PROJECT_STATUS.md",
        )
        self.assertEqual(
            data["checks"]["exclude_paths"],
            ["outputs/**"],
        )

    def test_status_document_budget_defaults_and_overrides(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            defaults = load_config(root).config

            self.assertEqual(defaults.status_max_chars, DEFAULT_STATUS_MAX_CHARS)
            self.assertEqual(defaults.status_max_lines, DEFAULT_STATUS_MAX_LINES)
            self.assertEqual(
                defaults.fixed_input_target_chars,
                DEFAULT_FIXED_INPUT_TARGET_CHARS,
            )
            self.assertEqual(
                defaults.fixed_input_target_lines,
                DEFAULT_FIXED_INPUT_TARGET_LINES,
            )
            self.assertEqual(
                defaults.fixed_input_high_chars,
                DEFAULT_FIXED_INPUT_HIGH_CHARS,
            )
            self.assertEqual(
                defaults.fixed_input_high_lines,
                DEFAULT_FIXED_INPUT_HIGH_LINES,
            )

            _write(
                root / ".project-agent.yml",
                "checks:\n  status_max_chars: 10000\n  status_max_lines: 500\n",
            )
            configured = load_config(root).config

            self.assertEqual(configured.status_max_chars, 10_000)
            self.assertEqual(configured.status_max_lines, 500)

    def test_fixed_input_uses_total_even_when_each_document_is_under_target(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            readme_text = "R" * 700
            status_text = "\n".join(
                [
                    "Status: active",
                    "Last updated: 2099-01-01",
                    "last_reviewed: 2099-01-01",
                    "next_review: 2099-06-21",
                    "S" * 700,
                ]
            )
            _write(root / "README.md", readme_text)
            _write(root / "PROJECT_STATUS.md", status_text)
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "reading:",
                        "  automatic_instruction_files:",
                        "  always_read_files:",
                        "    - README.md",
                        "    - PROJECT_STATUS.md",
                        "  target_chars: 1000",
                        "  target_lines: 100",
                        "  high_cost_chars: 5000",
                        "  high_cost_lines: 500",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertLess(len(readme_text), 1_000)
            self.assertLess(len(status_text), 1_000)
            self.assertEqual(
                result.fixed_input.character_count,
                len(readme_text) + len(status_text),
            )
            self.assertTrue(
                any(
                    risk.code == "fixed_input_review_needed"
                    for risk in result.risks
                )
            )

    def test_fixed_input_supports_non_root_status_file(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            (root / "docs").mkdir()
            current = "\n".join(
                [
                    "Status: paused",
                    "Last updated: 2099-01-01",
                    "last_reviewed: 2099-01-01",
                    "next_review: 2099-06-21",
                    "",
                ]
            )
            _write(root / "docs" / "project_status.md", current)
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: docs/project_status.md",
                        "reading:",
                        "  always_read_files:",
                        "    - README.md",
                        "    - docs/project_status.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertEqual(result.project_status.path, root / "docs" / "project_status.md")
            self.assertEqual(result.project_status.status, "paused")
            self.assertEqual(result.fixed_input.scope_state, "declared")
            self.assertFalse(
                any(risk.code == "missing_project_status" for risk in result.risks)
            )

    def test_conditional_and_history_documents_are_excluded_from_fixed_total(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            (root / "docs").mkdir()
            _write(root / "docs" / "details.md", "D" * 20_000)
            _write(root / "docs" / "history.md", "H" * 20_000)
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "reading:",
                        "  always_read_files:",
                        "    - README.md",
                        "    - PROJECT_STATUS.md",
                        "  read_when_needed_files:",
                        "    - docs/details.md",
                        "  reference_files:",
                        "    - docs/history.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            expected = len((root / "README.md").read_text(encoding="utf-8")) + len(
                (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
            )
            self.assertEqual(result.fixed_input.character_count, expected)
            self.assertEqual(result.fixed_input.read_when_needed_files, ("docs/details.md",))
            self.assertEqual(result.fixed_input.reference_files, ("docs/history.md",))

    def test_reasoned_exception_preserves_safety_text_and_review_condition(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            safety_text = "承認なしに削除・公開しない。\n" * 100
            _write(root / "AGENTS.md", safety_text)
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "reading:",
                        "  automatic_instruction_files:",
                        "    - AGENTS.md",
                        "  always_read_files:",
                        "  target_chars: 100",
                        "  target_lines: 10",
                        "  high_cost_chars: 200",
                        "  high_cost_lines: 20",
                        "  exception_reason: 安全と承認境界を守るため",
                        "  exception_review_condition: 安全規則の変更時",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            report = build_markdown_report(result)

            self.assertEqual((root / "AGENTS.md").read_text(encoding="utf-8"), safety_text)
            self.assertEqual(
                result.fixed_input.exception_review_condition,
                "安全規則の変更時",
            )
            self.assertFalse(
                any(
                    risk.code in {"fixed_input_review_needed", "fixed_input_high_cost"}
                    for risk in result.risks
                )
            )
            self.assertIn("理由と再確認条件あり", report)

    def test_fixed_input_high_cost_level_is_medium_without_exception(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "ALWAYS.md", "A" * 500)
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "reading:",
                        "  always_read_files:",
                        "    - ALWAYS.md",
                        "  target_chars: 100",
                        "  target_lines: 10",
                        "  high_cost_chars: 200",
                        "  high_cost_lines: 20",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            risk = next(
                risk for risk in result.risks if risk.code == "fixed_input_high_cost"
            )

            self.assertEqual(risk.severity, "medium")
            self.assertEqual(result.overall_judgment.continuity, "at_risk")

    def test_token_count_is_measured_independently_from_character_count(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "AUTO.md", "日本日本")
            _write(root / "CURRENT.md", "abab")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "reading:",
                        "  automatic_instruction_files:",
                        "    - AUTO.md",
                        "  always_read_files:",
                        "    - CURRENT.md",
                        "",
                    ]
                ),
            )

            with patch(
                "pma.fixed_input.count_text_tokens",
                side_effect=lambda text, _encoding: 7 if "日本" in text else 2,
            ):
                result = scan_path(root)

            self.assertEqual(result.fixed_input.character_count, 8)
            self.assertEqual(result.fixed_input.token_count, 9)

    def test_missing_optional_tokenizer_does_not_estimate_from_characters(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "reading:\n  always_read_files:\n    - README.md\n    - PROJECT_STATUS.md\n",
            )

            with patch("pma.fixed_input._load_token_encoder", return_value=None):
                result = scan_path(root)
            report = build_markdown_report(result)

            self.assertIsNone(result.fixed_input.token_count)
            self.assertIn("文字数から換算しません", report)

    def test_status_document_character_budget_is_actionable_without_leaking_text(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        marker = "PRIVATE-LIVE-STATE-MARKER"
        status_text = "\n".join(
            [
                "Status: active",
                "Last updated: 2099-01-01",
                "last_reviewed: 2099-01-01",
                "next_review: 2099-06-21",
                marker * 200,
                "",
            ]
        )
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir), status_text=status_text)

            result = scan_path(root)
            risk = next(
                risk
                for risk in result.risks
                if risk.code == "status_document_over_budget"
            )
            report = build_markdown_report(result)

            self.assertEqual(risk.severity, "medium")
            self.assertEqual(result.overall_judgment.continuity, "at_risk")
            self.assertIn("4096 文字・128 行", risk.evidence)
            self.assertIn("状態文書量:", report)
            self.assertTrue(
                any(
                    item.code == "fixed_input_scope_unconfirmed"
                    for item in result.risks
                )
            )
            self.assertNotIn(marker, risk.evidence)
            self.assertNotIn(marker, report)

    def test_status_document_line_budget_can_be_overridden(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        status_text = "\n".join(
            [
                "Status: active",
                "Last updated: 2099-01-01",
                "last_reviewed: 2099-01-01",
                "next_review: 2099-06-21",
                *("short note" for _ in range(125)),
                "",
            ]
        )
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir), status_text=status_text)

            first = scan_path(root)
            self.assertTrue(
                any(
                    risk.code == "status_document_over_budget"
                    for risk in first.risks
                )
            )

            _write(
                root / ".project-agent.yml",
                "checks:\n  status_max_chars: 10000\n  status_max_lines: 500\n",
            )
            second = scan_path(root)
            self.assertFalse(
                any(
                    risk.code == "status_document_over_budget"
                    for risk in second.risks
                )
            )

    def test_uncommitted_change_is_detected(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "README.md", "# Example\n\nchanged\n")

            result = scan_path(root)

            self.assertTrue(any(risk.code == "uncommitted_changes" for risk in result.risks))
            self.assertEqual(
                result.consultation,
                "未コミットの変更があります。後で迷わないように、変更内容を短く整理してよろしいですか？",
            )

    def test_missing_review_metadata_is_warning(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="Status: active\nLast updated: 2026-06-14\n",
            )

            result = scan_path(root)

            self.assertTrue(any(risk.code == "missing_review_fields" for risk in result.risks))

    def test_recognized_status_variants_keep_stale_detection(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        for status_value in ("active", "Active", "ACTIVE", "  Active  "):
            with self.subTest(status=status_value), TemporaryDirectory() as temp_dir:
                root = _make_repo(
                    Path(temp_dir),
                    status_text="\n".join(
                        [
                            f"Status: {status_value}",
                            "Last updated: 2000-01-01",
                            "last_reviewed: 2000-01-01",
                            "next_review: 2099-01-01",
                            "",
                        ]
                    ),
                    commit_date="2000-01-01T00:00:00+09:00",
                )

                result = scan_path(root)

                self.assertFalse(
                    any(
                        risk.code == "unrecognized_status"
                        for risk in result.risks
                    )
                )
                self.assertTrue(
                    any(risk.code == "active_stale" for risk in result.risks)
                )

    def test_unrecognized_status_is_reported_without_raw_value(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        for status_value in ("wip", "maintenance", "unknown"):
            with self.subTest(status=status_value), TemporaryDirectory() as temp_dir:
                root = _make_repo(
                    Path(temp_dir),
                    status_text="\n".join(
                        [
                            f"Status: {status_value}",
                            "Last updated: 2026-07-30",
                            "last_reviewed: 2026-07-30",
                            "next_review: 2099-01-01",
                            "",
                        ]
                    ),
                )

                result = scan_path(root)
                risk = next(
                    risk
                    for risk in result.risks
                    if risk.code == "unrecognized_status"
                )
                report = build_markdown_report(result)

                self.assertIn("stale判定は適用していません", risk.evidence)
                self.assertNotIn(status_value, risk.evidence)
                self.assertIn("未認識（値は状態ファイルで確認）", report)
                self.assertNotIn(f"- status: {status_value}", report)
                self.assertFalse(
                    any(
                        risk.code.startswith("invalid_")
                        for risk in result.risks
                    )
                )

    def test_missing_status_is_reported_separately(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(
                any(risk.code == "missing_status" for risk in result.risks)
            )
            self.assertFalse(
                any(risk.code == "unrecognized_status" for risk in result.risks)
            )

    def test_duplicate_status_fields_are_ambiguous_without_using_values(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "# Project Status",
                        "Status: active",
                        "Last updated: 2026-07-31",
                        "last_reviewed: 2026-07-31",
                        "next_review: 2026-08-01",
                        "",
                        "## Example",
                        "",
                        "```markdown",
                        "Status: paused",
                        "last_reviewed: 2025-01-01",
                        "next_review: 2025-01-08",
                        "```",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            risk = next(
                risk
                for risk in result.risks
                if risk.code == "ambiguous_status_fields"
            )

            self.assertIsNone(result.project_status.status)
            self.assertIsNone(result.project_status.last_reviewed)
            self.assertIsNone(result.project_status.next_review)
            self.assertEqual(
                result.project_status.duplicate_fields,
                ["status", "last_reviewed", "next_review"],
            )
            self.assertNotIn("active", risk.evidence)
            self.assertNotIn("paused", risk.evidence)
            self.assertFalse(
                any(
                    finding.code
                    in {
                        "missing_status",
                        "unrecognized_status",
                        "missing_review_fields",
                        "active_stale",
                        "paused_activity",
                    }
                    for finding in result.risks
                )
            )
            self.assertEqual(
                result.status_line_observation.state,
                "not_observable",
            )
            self.assertIn(
                "- status継続期間: 未確認",
                build_markdown_report(result),
            )

    def test_blocked_is_recognized_without_stale_threshold(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: blocked",
                        "Last updated: 2000-01-01",
                        "last_reviewed: 2000-01-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2000-01-01T00:00:00+09:00",
            )

            result = scan_path(root)

            self.assertFalse(
                any(risk.code == "unrecognized_status" for risk in result.risks)
            )
            self.assertFalse(
                any(risk.code.endswith("_stale") for risk in result.risks)
            )

    def test_valid_iso_status_dates_are_not_reported_invalid(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30T10:00:00+09:00",
                        "last_reviewed: 2026/07/30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertFalse(
                any(risk.code == "invalid_status_dates" for risk in result.risks)
            )

    def test_invalid_status_date_is_reported_without_raw_value(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30 trailing-text",
                        "last_reviewed: 2026-02-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )

            result = scan_path(root)
            risk = next(
                risk for risk in result.risks if risk.code == "invalid_status_dates"
            )
            report = build_markdown_report(result)

            self.assertIn("Last updated", risk.evidence)
            self.assertIn("last_reviewed", risk.evidence)
            self.assertNotIn("trailing-text", risk.evidence)
            self.assertNotIn("2026-02-30", risk.evidence)
            self.assertIn("不正な日付（値は非表示）", report)
            self.assertNotIn("trailing-text", report)
            self.assertNotIn("2026-02-30", report)

    def test_template_status_date_is_reported_invalid(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: YYYY-MM-DD",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(
                any(risk.code == "invalid_status_dates" for risk in result.risks)
            )
            self.assertFalse(
                any(risk.code == "missing_review_fields" for risk in result.risks)
            )

    def test_active_stale_candidate_is_warning(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2000-01-01",
                        "last_reviewed: 2000-01-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2000-01-01T00:00:00+09:00",
            )

            result = scan_path(root)

            self.assertTrue(any(risk.code == "active_stale" for risk in result.risks))
            self.assertIn("継続・休止・保留", result.consultation)

    def test_recent_review_does_not_hide_old_active_git_activity(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2000-01-01T00:00:00+09:00",
            )
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            risk = next(risk for risk in result.risks if risk.code == "active_stale")
            self.assertIn("直近コミット日", risk.evidence)
            self.assertIn("状態文書の確認日とは別", risk.evidence)

    def test_uncommitted_work_does_not_claim_active_has_no_activity(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2000-01-01T00:00:00+09:00",
            )
            _write(root / "README.md", "# Example\n\nwork in progress\n")
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertTrue(
                any(risk.code == "uncommitted_changes" for risk in result.risks)
            )
            self.assertFalse(
                any(risk.code == "active_stale" for risk in result.risks)
            )

    def test_recent_active_git_activity_with_old_status_is_separate_risk(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2026-07-29T00:00:00+09:00",
            )
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertTrue(
                any(risk.code == "status_document_stale" for risk in result.risks)
            )
            self.assertFalse(
                any(risk.code == "active_stale" for risk in result.risks)
            )

    def test_paused_activity_after_latest_status_observation_is_reported(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2026-07-29T00:00:00+09:00",
            )
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertTrue(
                any(risk.code == "paused_activity" for risk in result.risks)
            )

    def test_paused_activity_before_later_review_is_not_repeated(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2026-07-29T00:00:00+09:00",
            )
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertFalse(
                any(risk.code == "paused_activity" for risk in result.risks)
            )

    def test_status_duration_uses_git_history_without_manual_field(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: blocked",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2026-07-01T00:00:00+09:00",
            )
            fixed_now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertEqual(result.status_line_observation.state, "confirmed")
            self.assertEqual(
                result.status_line_observation.commit_at,
                "2026-07-01T00:00:00+09:00",
            )
            report = build_markdown_report(result)
            self.assertIn("status継続期間: 31日以上", report)
            self.assertIn("現在のstatus行をGit履歴で確認", report)

    def test_uncommitted_status_change_does_not_assert_duration(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                commit_date="2026-07-01T00:00:00+09:00",
            )
            status_path = root / "PROJECT_STATUS.md"
            status_text = status_path.read_text(encoding="utf-8")
            _write(status_path, status_text.replace("Status: active", "Status: blocked"))

            result = scan_path(root)

            self.assertEqual(result.status_line_observation.state, "uncommitted")
            self.assertIn(
                "- status継続期間: 未確認（status行が未コミット）",
                build_markdown_report(result),
            )

    def test_working_tree_change_during_scan_requires_rescan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            status_path = root / "PROJECT_STATUS.md"
            hook_calls = 0

            def change_status_before_history_check(*args, **kwargs):
                nonlocal hook_calls
                hook_calls += 1
                if hook_calls == 1:
                    _write(
                        status_path,
                        status_path.read_text(encoding="utf-8").replace(
                            "Status: paused",
                            "Status: active",
                        ),
                    )
                return collect_git_line_observation(*args, **kwargs)

            with patch(
                "pma.scan.collect_git_line_observation",
                side_effect=change_status_before_history_check,
            ):
                result = scan_path(root)

            report = build_markdown_report(result)
            self.assertEqual(hook_calls, 1)
            self.assertEqual(result.observation_consistency, "changed")
            self.assertEqual(
                [risk.code for risk in result.risks],
                ["scan_changed_during_observation"],
            )
            self.assertEqual(result.overall_judgment.continuity, "unknown")
            self.assertIn(
                "- 観測の一貫性: 要再確認（走査中に観測対象が変化）",
                report,
            )
            self.assertIn("- HEAD commit: 未確認", report)
            self.assertIn("- working tree: 未確認", report)
            self.assertNotIn("- status: paused", report)
            self.assertNotIn("- status: active", report)
            self.assertNotIn("追加対応なし", report)

            stable_result = scan_path(root)
            self.assertEqual(stable_result.observation_consistency, "stable")
            self.assertEqual(stable_result.project_status.status, "active")

    def test_already_dirty_status_content_change_requires_rescan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            status_path = root / "PROJECT_STATUS.md"
            _write(
                status_path,
                status_path.read_text(encoding="utf-8").replace(
                    "Status: active",
                    "Status: paused",
                ),
            )
            hook_calls = 0

            def change_dirty_status_again(*args, **kwargs):
                nonlocal hook_calls
                hook_calls += 1
                if hook_calls == 1:
                    _write(
                        status_path,
                        status_path.read_text(encoding="utf-8").replace(
                            "Status: paused",
                            "Status: active",
                        ),
                    )
                return collect_git_line_observation(*args, **kwargs)

            with patch(
                "pma.scan.collect_git_line_observation",
                side_effect=change_dirty_status_again,
            ):
                result = scan_path(root)

            self.assertEqual(hook_calls, 1)
            self.assertEqual(result.observation_consistency, "changed")
            self.assertEqual(
                [risk.code for risk in result.risks],
                ["scan_changed_during_observation"],
            )
            report = build_markdown_report(result)
            self.assertIn("- プロジェクトパス: 未確認", report)
            self.assertNotIn(f"`{root}`", report)
            self.assertNotIn("`README.md`: あり", report)
            self.assertNotIn("- status: paused", report)
            self.assertNotIn("- status: active", report)

    def test_ignored_status_content_change_requires_rescan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / ".gitignore", "CURRENT.md\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: CURRENT.md",
                        "checks:",
                        "  required_files:",
                        "    - README.md",
                        "    - CURRENT.md",
                        "    - .project-agent.yml",
                        "",
                    ]
                ),
            )
            current = root / "CURRENT.md"
            _write(
                current,
                "\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            _run(root, ["git", "add", ".gitignore", ".project-agent.yml"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "configure ignored status",
                ],
            )
            hook_calls = 0

            def change_ignored_status(*args, **kwargs):
                nonlocal hook_calls
                hook_calls += 1
                if hook_calls == 1:
                    _write(
                        current,
                        current.read_text(encoding="utf-8").replace(
                            "Status: paused",
                            "Status: active",
                        ),
                    )
                return collect_git_line_observation(*args, **kwargs)

            with patch(
                "pma.scan.collect_git_line_observation",
                side_effect=change_ignored_status,
            ):
                result = scan_path(root)

            self.assertEqual(hook_calls, 1)
            self.assertEqual(result.observation_consistency, "changed")
            self.assertEqual(result.overall_judgment.continuity, "unknown")
            self.assertNotIn("- status: paused", build_markdown_report(result))

    def test_head_change_during_scan_requires_rescan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            status_path = root / "PROJECT_STATUS.md"
            initial_head = collect_git_info(root).head_commit
            hook_calls = 0

            def commit_status_before_history_check(*args, **kwargs):
                nonlocal hook_calls
                hook_calls += 1
                if hook_calls == 1:
                    _write(
                        status_path,
                        status_path.read_text(encoding="utf-8").replace(
                            "Status: paused",
                            "Status: active",
                        ),
                    )
                    _run(root, ["git", "add", "PROJECT_STATUS.md"])
                    _run(
                        root,
                        [
                            "git",
                            "-c",
                            "user.email=test@example.com",
                            "-c",
                            "user.name=Test User",
                            "commit",
                            "-m",
                            "change status during scan",
                        ],
                    )
                return collect_git_line_observation(*args, **kwargs)

            with patch(
                "pma.scan.collect_git_line_observation",
                side_effect=commit_status_before_history_check,
            ):
                result = scan_path(root)

            report = build_markdown_report(result)
            self.assertEqual(hook_calls, 1)
            self.assertEqual(result.observation_consistency, "changed")
            self.assertEqual(
                [risk.code for risk in result.risks],
                ["scan_changed_during_observation"],
            )
            self.assertEqual(result.overall_judgment.continuity, "unknown")
            self.assertNotEqual(collect_git_info(root).head_commit, initial_head)
            self.assertIn("- HEAD commit: 未確認", report)
            self.assertNotIn("- status: paused", report)

            stable_result = scan_path(root)
            self.assertEqual(stable_result.observation_consistency, "stable")
            self.assertEqual(stable_result.project_status.status, "active")

    def test_final_git_state_unavailable_does_not_confirm_scan(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            start = collect_git_info(root)
            unavailable_end = GitInfo(
                is_repo=True,
                root=root,
                status_lines=[],
                last_commit_at=None,
                error="final git status unavailable",
                error_kind="unavailable",
            )

            with patch(
                "pma.scan.collect_git_info",
                side_effect=[start, unavailable_end],
            ):
                result = scan_path(root)

            report = build_markdown_report(result)
            self.assertEqual(result.observation_consistency, "unavailable")
            self.assertEqual(
                [risk.code for risk in result.risks],
                ["scan_consistency_unavailable"],
            )
            self.assertEqual(result.overall_judgment.continuity, "unknown")
            self.assertIn("- HEAD commit: 未確認", report)
            self.assertNotIn("- status: active", report)

    def test_uncommitted_line_before_status_keeps_the_status_history(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                commit_date="2026-07-01T00:00:00+09:00",
            )
            status_path = root / "PROJECT_STATUS.md"
            status_text = status_path.read_text(encoding="utf-8")
            _write(status_path, f"Local note\n{status_text}")
            fixed_now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)

            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertEqual(result.status_line_observation.state, "confirmed")
            self.assertEqual(
                result.status_line_observation.commit_at,
                "2026-07-01T00:00:00+09:00",
            )
            self.assertIn(
                "- status継続期間: 31日以上",
                build_markdown_report(result),
            )

    def test_untracked_status_file_does_not_assert_duration(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _run(root, ["git", "rm", "--cached", "PROJECT_STATUS.md"])

            result = scan_path(root)

            self.assertEqual(
                result.status_line_observation.state,
                "not_in_history",
            )
            self.assertIn(
                "- status継続期間: 未確認（status行のGit履歴なし）",
                build_markdown_report(result),
            )

    def test_non_git_line_separator_does_not_blame_another_line(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "# Project Status\fStatus: active",
                        "Last updated: 2026-07-01",
                        "last_reviewed: 2026-07-01",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
                commit_date="2026-07-01T00:00:00+09:00",
            )

            result = scan_path(root)

            self.assertEqual(
                result.status_line_observation.state,
                "unavailable",
            )
            self.assertIn(
                "- status継続期間: 未確認",
                build_markdown_report(result),
            )

    def test_out_of_range_git_timestamp_is_not_observed(self) -> None:
        self.assertIsNone(_format_git_timestamp(str(10**100), "+0000"))

    def test_metadata_update_does_not_reset_status_duration(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                commit_date="2026-07-01T00:00:00+09:00",
            )
            status_path = root / "PROJECT_STATUS.md"
            status_text = status_path.read_text(encoding="utf-8")
            _write(
                status_path,
                status_text.replace(
                    "last_reviewed: 2026-06-14",
                    "last_reviewed: 2026-07-20",
                ),
            )
            _run(root, ["git", "add", "PROJECT_STATUS.md"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "review status",
                ],
                env={
                    "GIT_AUTHOR_DATE": "2026-07-20T00:00:00+09:00",
                    "GIT_COMMITTER_DATE": "2026-07-20T00:00:00+09:00",
                },
            )

            result = scan_path(root)

            self.assertEqual(result.status_line_observation.state, "confirmed")
            self.assertEqual(
                result.status_line_observation.commit_at,
                "2026-07-01T00:00:00+09:00",
            )

    def test_configured_status_file_is_used(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / "CURRENT.md",
                "\n".join(
                    [
                        "Status: paused",
                        "Last updated: 2026-07-29",
                        "last_reviewed: 2026-07-29",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            _write(root / "README.md", "# Example\n\n[Status](CURRENT.md)\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: CURRENT.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertEqual(result.project_status.path, root / "CURRENT.md")
            self.assertEqual(result.project_status.status, "paused")
            self.assertIn("CURRENT.md", result.files)
            self.assertNotIn("PROJECT_STATUS.md", result.files)
            self.assertFalse(
                any(risk.code == "missing_project_status" for risk in result.risks)
            )

    def test_status_file_outside_project_is_not_read(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            root = _make_repo(root)
            _write(
                base / "outside.md",
                "\n".join(
                    [
                        "Status: active",
                        "last_reviewed: 2026-07-29",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: ../outside.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertFalse(result.project_status.exists)
            self.assertIsNone(result.project_status.status)
            self.assertFalse(result.files["../outside.md"].exists)
            self.assertEqual(
                result.risks[0].code, "status_file_outside_project"
            )
            self.assertTrue(
                any("プロジェクト外" in warning for warning in result.project_status.warnings)
            )

    def test_directory_status_path_is_disallowed(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: .",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(result.project_status.exists)
            self.assertFalse(result.files["."].exists)
            self.assertEqual(result.risks[0].code, "status_file_disallowed")

    def test_sensitive_status_file_is_not_read(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / ".env",
                "\n".join(
                    [
                        "Status: active",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "",
                    ]
                ),
            )
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: .env",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertIsNone(result.project_status.status)
            self.assertEqual(result.risks[0].code, "status_file_disallowed")

    def test_non_utf8_status_file_is_reported_unreadable(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            (root / "CURRENT.md").write_bytes(b"\xff\xfe\x00")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        "  status_file: CURRENT.md",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertIsNone(result.project_status.status)
            self.assertEqual(result.risks[0].code, "status_file_unreadable")

    def test_next_review_overdue_is_reported_separately(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-29",
                        "last_reviewed: 2026-07-29",
                        "next_review: 2000-01-01",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertTrue(
                any(risk.code == "next_review_overdue" for risk in result.risks)
            )

    def test_next_review_is_not_overdue_on_due_date(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2026-07-30",
                        "",
                    ]
                ),
            )
            fixed_now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
            with patch("pma.scan.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                result = scan_path(root)

            self.assertFalse(
                any(risk.code == "next_review_overdue" for risk in result.risks)
            )

    def test_keyword_scan_respects_gitignore_allowlist_and_secret_exclusions(
        self,
    ) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / ".gitignore", "ignored.md\n")
            _write(root / "notes.md", "TODO visible footwork note\n")
            _write(root / "ignored.md", "TODO ignored by Git\n")
            _write(root / ".env", "TODO secret value\n")
            _write(root / "credentials.json", '{"note": "TODO secret value"}\n')
            _write(root / "private.pem", "TODO private key\n")
            _write(root / "image.png", "TODO binary-like content\n")

            matches = find_keyword_matches(root, ["TODO"])

            self.assertEqual(
                [(match.path, match.keyword) for match in matches],
                [("notes.md", "TODO")],
            )

    def test_keyword_scan_returns_one_representative_per_file(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(
                root / "notes.md",
                "要確認 first candidate\nTODO preferred candidate\nTODO repeated\n",
            )

            matches = find_keyword_matches(root, ["TODO", "要確認"])

            self.assertEqual(
                [
                    (match.path, match.line_number, match.keyword)
                    for match in matches
                    if match.path == "notes.md"
                ],
                [("notes.md", 2, "TODO")],
            )

    def test_unchanged_keyword_candidate_is_background_not_risk(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "baseline.md", "TODO existing candidate\n")
            _run(root, ["git", "add", "baseline.md"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "add baseline candidate",
                ],
            )

            result = scan_path(root)

            match = next(
                match
                for match in result.keyword_matches
                if match.path == "baseline.md"
            )
            self.assertFalse(match.is_current)
            self.assertFalse(
                any(risk.code == "footwork_keywords" for risk in result.risks)
            )

    def test_current_keyword_candidate_is_prioritized_and_reported(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "baseline.md", "TODO existing candidate\n")
            _run(root, ["git", "add", "baseline.md"])
            _run(
                root,
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "add baseline candidate",
                ],
            )
            _write(root / "作業 メモ.md", "TODO current candidate\n")

            result = scan_path(root)
            report = build_markdown_report(result)

            self.assertEqual(result.keyword_matches[0].path, "作業 メモ.md")
            self.assertTrue(result.keyword_matches[0].is_current)
            self.assertTrue(
                any(risk.code == "footwork_keywords" for risk in result.risks)
            )
            self.assertIn("`作業 メモ.md:1`: `TODO`（今回変更）", report)
            self.assertIn("今回変更された候補: 1 ファイル", report)
            self.assertIn("既存不変の候補: 1 ファイル", report)

    def test_keyword_scan_skips_config_status_and_generated_reviews(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(
                Path(temp_dir),
                status_text="\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "TODO status note",
                        "",
                    ]
                ),
            )
            _write(root / ".project-agent.yml", "TODO configured keyword\n")
            review_dir = root / "work_logs" / "steward"
            review_dir.mkdir(parents=True)
            _write(review_dir / "footwork_review_2026-07-30.md", "TODO output\n")
            _write(root / "notes.md", "TODO actual candidate\n")

            matches = find_keyword_matches(
                root,
                ["TODO"],
                skip_paths=[".project-agent.yml", "PROJECT_STATUS.md"],
            )

            self.assertEqual(
                [(match.path, match.keyword) for match in matches],
                [("notes.md", "TODO")],
            )

    def test_scan_skips_absolute_status_path_from_keyword_candidates(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            current = root / "CURRENT.md"
            _write(
                current,
                "\n".join(
                    [
                        "Status: active",
                        "Last updated: 2026-07-30",
                        "last_reviewed: 2026-07-30",
                        "next_review: 2099-01-01",
                        "TODO status note",
                        "",
                    ]
                ),
            )
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "project:",
                        f"  status_file: {current}",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertEqual(result.keyword_matches, [])

    def test_single_character_keyword_requires_trailing_boundary(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            _write(root / "theory.md", "仮説を検討する\n")
            _write(root / "tentative.md", "名称（仮）\n")
            _write(root / "sentence.md", "この状態は仮。\n")

            matches = find_keyword_matches(root, ["仮"])

            self.assertEqual(
                sorted(match.path for match in matches),
                ["sentence.md", "tentative.md"],
            )

    def test_keyword_scan_respects_configured_exclude_patterns(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            excluded = root / "outputs" / "notes.md"
            excluded.parent.mkdir()
            _write(excluded, "TODO excluded output\n")
            hidden = root / ".private" / "notes.md"
            hidden.parent.mkdir()
            _write(hidden, "TODO excluded hidden note\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  exclude_paths:",
                        "    - outputs/**",
                        "    - .private/**",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertEqual(result.keyword_matches, [])

    def test_keyword_scan_supports_trailing_slash_directory_exclusion(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            excluded = root / "outputs" / "notes.md"
            excluded.parent.mkdir()
            _write(excluded, "TODO excluded output\n")
            _write(
                root / ".project-agent.yml",
                "\n".join(
                    [
                        "checks:",
                        "  exclude_paths:",
                        "    - outputs/",
                        "",
                    ]
                ),
            )

            result = scan_path(root)

            self.assertEqual(result.keyword_matches, [])

    def test_keyword_scan_skips_symlinks(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            candidate = root / "linked.md"
            _write(candidate, "TODO linked content\n")

            with (
                patch("pma.scan.list_git_scan_files", return_value=[candidate]),
                patch.object(type(candidate), "is_symlink", return_value=True),
                patch.object(
                    type(candidate),
                    "is_file",
                    side_effect=AssertionError("symlink target was inspected"),
                ),
            ):
                matches = find_keyword_matches(root, ["TODO"])

            self.assertEqual(matches, [])

    def test_observation_identity_does_not_hash_symlink_target(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            link = root / "README.md"
            config_result = load_config(root)

            with patch.object(type(link), "is_symlink", return_value=True):
                paths = _collect_observation_paths(root, config_result)
                readme_entry = next(item for item in paths if item[0] == link)
                self.assertFalse(readme_entry[1])
                with patch.object(
                    type(link),
                    "read_bytes",
                    side_effect=AssertionError("symlink target was hashed"),
                ):
                    states = _capture_observation_path_state(
                        root,
                        (readme_entry,),
                    )

            self.assertIsNotNone(states)
            self.assertEqual(states[0][1], "symlink")
            self.assertEqual(states[0][4], "")

    def test_observation_identity_does_not_hash_sensitive_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            sensitive = root / "private_secret.md"
            _write(sensitive, "DO_NOT_READ=secret\n")
            config_result = load_config(root)
            config_result = replace(
                config_result,
                config=replace(
                    config_result.config,
                    status_file="private_secret.md",
                ),
            )
            paths = _collect_observation_paths(root, config_result)
            sensitive_entry = next(
                item for item in paths if item[0] == sensitive
            )
            self.assertFalse(sensitive_entry[1])

            with patch.object(
                type(sensitive),
                "read_bytes",
                side_effect=AssertionError("sensitive status was hashed"),
            ):
                states = _capture_observation_path_state(
                    root,
                    (sensitive_entry,),
                )

            self.assertIsNotNone(states)

    def test_observation_identity_does_not_hash_oversized_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            readme = root / "README.md"
            readme.write_bytes(b"x" * (MAX_TEXT_FILE_BYTES + 1))
            config_result = load_config(root)
            paths = _collect_observation_paths(root, config_result)
            readme_entry = next(item for item in paths if item[0] == readme)
            self.assertFalse(readme_entry[1])

            with patch.object(
                type(readme),
                "read_bytes",
                side_effect=AssertionError("oversized text was hashed"),
            ):
                states = _capture_observation_path_state(
                    root,
                    (readme_entry,),
                )

            self.assertIsNotNone(states)

    def test_observation_identity_does_not_hash_unavailable_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = _make_repo(Path(temp_dir))
            config_path = root / ".project-agent.yml"
            _write(config_path, "project:\n  status_file: 'unterminated\n")
            config_result = load_config(root)
            self.assertEqual(config_result.load_state, "unavailable")
            paths = _collect_observation_paths(root, config_result)
            config_entry = next(
                item for item in paths if item[0] == config_path
            )
            self.assertFalse(config_entry[1])

            with patch.object(
                type(config_path),
                "read_bytes",
                side_effect=AssertionError("unavailable config was hashed"),
            ):
                states = _capture_observation_path_state(
                    root,
                    (config_entry,),
                )

            self.assertIsNotNone(states)


def _make_repo(
    root: Path,
    *,
    include_config: bool = True,
    status_text: str | None = None,
    commit_date: str | None = None,
) -> Path:
    _run(root, ["git", "init"])
    _write(
        root / "README.md",
        "# Example\n\n[Project status](PROJECT_STATUS.md)\n",
    )
    _write(
        root / "PROJECT_STATUS.md",
        status_text
        or "\n".join(
            [
                "Status: active",
                "Last updated: 2026-06-14",
                "last_reviewed: 2026-06-14",
                "next_review: 2099-06-21",
                "",
            ]
        ),
    )
    if include_config:
        _write(
            root / ".project-agent.yml",
            "\n".join(
                [
                    "checks:",
                    "  required_files:",
                    "    - README.md",
                    "    - PROJECT_STATUS.md",
                    "    - .project-agent.yml",
                    "stale:",
                    "  active_days: 14",
                    "  paused_days: 30",
                    "  archived_days: 180",
                    "report:",
                    "  max_priority_actions: 3",
                    "  output_dir: reports",
                    "",
                ]
            ),
        )
    add_targets = ["README.md", "PROJECT_STATUS.md"]
    if include_config:
        add_targets.append(".project-agent.yml")
    _run(root, ["git", "add", *add_targets])
    env = {}
    if commit_date:
        env = {"GIT_AUTHOR_DATE": commit_date, "GIT_COMMITTER_DATE": commit_date}
    _run(
        root,
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            "commit",
            "-m",
            "initial",
        ],
        env=env,
    )
    return root


def _run(cwd: Path, command: list[str], env: dict[str, str] | None = None) -> None:
    run_env = None
    if env:
        run_env = {**environ, **env}
    subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True, env=run_env)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
