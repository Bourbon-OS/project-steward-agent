from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tomllib
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pma.cli import build_parser, main
from pma.git_utils import GitInfo


class CliTests(unittest.TestCase):
    def test_distribution_name_changes_without_renaming_pma_entry_point(self) -> None:
        metadata = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

        self.assertEqual(metadata["name"], "ashiba-steward")
        self.assertEqual(metadata["scripts"], {"pma": "pma.cli:main"})

    def test_top_level_help_explains_pma_name_and_boundary(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("Project Memory Anchor", help_text)
        self.assertIn("operational memory", help_text)
        self.assertIn("Read-only by default", help_text)
        self.assertIn("does not repair project records, commit, or notify", help_text)

    def test_default_scan_preserves_head_and_working_tree(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_dirty_git_project(root)
            readme_before = (root / "README.md").read_bytes()
            notes_before = (root / "notes.txt").read_bytes()
            head_before = _git_output(root, ["rev-parse", "HEAD"])
            index_before = _git_output(root, ["ls-files", "--stage"])
            status_before = _git_output(
                root,
                ["status", "--porcelain=v1", "--untracked-files=all"],
            )
            buffer = io.StringIO()

            with contextlib.redirect_stdout(buffer):
                exit_code = main(["scan", "--path", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertIn("# 足場レビュー", buffer.getvalue())
            self.assertEqual((root / "README.md").read_bytes(), readme_before)
            self.assertEqual((root / "notes.txt").read_bytes(), notes_before)
            self.assertEqual(_git_output(root, ["rev-parse", "HEAD"]), head_before)
            self.assertEqual(_git_output(root, ["ls-files", "--stage"]), index_before)
            self.assertEqual(
                _git_output(
                    root,
                    ["status", "--porcelain=v1", "--untracked-files=all"],
                ),
                status_before,
            )
            self.assertFalse((root / "reports").exists())

    def test_python_module_process_reports_at_risk_without_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_dirty_git_project(root)
            readme_before = (root / "README.md").read_bytes()
            notes_before = (root / "notes.txt").read_bytes()
            head_before = _git_output(root, ["rev-parse", "HEAD"])
            index_before = _git_output(root, ["ls-files", "--stage"])
            status_before = _git_output(
                root,
                ["status", "--porcelain=v1", "--untracked-files=all"],
            )

            completed = _run_pma_process(root)

            self.assertEqual(completed.returncode, 0)
            self.assertIn("# 足場レビュー", completed.stdout)
            self.assertIn("- continuity: `at_risk`", completed.stdout)
            self.assertEqual(completed.stderr, "")
            self.assertEqual((root / "README.md").read_bytes(), readme_before)
            self.assertEqual((root / "notes.txt").read_bytes(), notes_before)
            self.assertEqual(_git_output(root, ["rev-parse", "HEAD"]), head_before)
            self.assertEqual(_git_output(root, ["ls-files", "--stage"]), index_before)
            self.assertEqual(
                _git_output(
                    root,
                    ["status", "--porcelain=v1", "--untracked-files=all"],
                ),
                status_before,
            )
            self.assertFalse((root / "reports").exists())

    def test_python_module_process_returns_nonzero_when_save_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            (root / ".project-agent.yml").write_text(
                "\n".join(
                    [
                        "report:",
                        "  output_dir: ../outside",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            completed = _run_pma_process(root, "--save-report")

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, "")
            self.assertNotEqual(completed.stderr, "")
            self.assertIn("プロジェクト外", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse((base / "outside").exists())

    def test_unknown_continuity_is_still_a_completed_scan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            buffer = io.StringIO()
            unavailable_git = GitInfo(
                is_repo=False,
                root=root,
                status_lines=[],
                last_commit_at=None,
                error="Git状態を確認できませんでした。",
                error_kind="unavailable",
            )

            with (
                patch("pma.scan.collect_git_info", return_value=unavailable_git),
                contextlib.redirect_stdout(buffer),
            ):
                exit_code = main(["scan", "--path", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertIn("- continuity: `unknown`", buffer.getvalue())

    def test_save_report_creates_report_file_only_when_requested(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            buffer = io.StringIO()

            with contextlib.redirect_stdout(buffer):
                exit_code = main(["scan", "--path", str(root), "--save-report"])

            report_dir = root / "reports"
            reports = list(report_dir.glob("footwork_review_*.md"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(reports), 1)
            self.assertIn("# 足場レビュー", reports[0].read_text(encoding="utf-8"))

    def test_save_report_does_not_overwrite_same_day_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                first_exit = main(["scan", "--path", str(root), "--save-report"])
                first_report = next((root / "reports").glob("footwork_review_*.md"))
                first_content = first_report.read_text(encoding="utf-8")
                second_exit = main(["scan", "--path", str(root), "--save-report"])
            reports = sorted((root / "reports").glob("footwork_review_*.md"))

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(len(reports), 2)
            self.assertEqual(first_report.read_text(encoding="utf-8"), first_content)
            self.assertTrue(reports[1].stem.endswith("_2"))

    def test_save_report_rejects_output_outside_project(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            (root / ".project-agent.yml").write_text(
                "\n".join(
                    [
                        "report:",
                        "  output_dir: ../outside",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with contextlib.redirect_stderr(buffer):
                exit_code = main(["scan", "--path", str(root), "--save-report"])

            self.assertNotEqual(exit_code, 0)
            self.assertFalse((base / "outside").exists())
            self.assertIn("プロジェクト外", buffer.getvalue())

    def test_save_report_rejects_unavailable_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".project-agent.yml").write_text(
                "[broken-config\n",
                encoding="utf-8",
            )
            buffer = io.StringIO()

            with contextlib.redirect_stderr(buffer):
                exit_code = main(
                    ["scan", "--path", str(root), "--save-report"]
                )

            self.assertNotEqual(exit_code, 0)
            self.assertFalse((root / "reports").exists())
            self.assertIn("保存先を推測せず", buffer.getvalue())


def _git_output(root: Path, args: list[str]) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _init_dirty_git_project(root: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    today = date.today().isoformat()
    (root / "README.md").write_text(
        "# Test project\n\n[Project status](PROJECT_STATUS.md)\n",
        encoding="utf-8",
    )
    (root / "PROJECT_STATUS.md").write_text(
        "\n".join(
            [
                "# Project Status",
                "",
                "Status: active",
                f"Last updated: {today}",
                f"last_reviewed: {today}",
                "next_review: 2099-01-01",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "README.md", "PROJECT_STATUS.md"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            "commit",
            "--quiet",
            "-m",
            "initial",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "README.md").write_text(
        "# Test project\n\nWork in progress.\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("local note\n", encoding="utf-8")


def _run_pma_process(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
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
            "scan",
            "--path",
            str(root),
            *args,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )


if __name__ == "__main__":
    unittest.main()
