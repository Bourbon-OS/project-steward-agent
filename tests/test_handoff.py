from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pma.cli import main
from pma.handoff import build_handoff_text, collect_handoff_observation
from pma.git_utils import GitInfo


class HandoffTests(unittest.TestCase):
    def test_observation_is_shallow_identified_and_read_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_project(root)
            private_path = root / "private-plan.txt"
            private_path.write_text("SECRET_CONTEXT\n", encoding="utf-8")
            before = _snapshot(root)
            observed_at = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)

            observation = collect_handoff_observation(
                root / "docs",
                "alpha-project",
                "event-driven",
                observed_at=observed_at,
            )
            text = build_handoff_text(observation)

            self.assertIn("Caller-supplied project: `alpha-project`", text)
            self.assertIn("Project/path association: not verified", text)
            self.assertIn("Observed at: 2026-08-12T09:30:00+00:00", text)
            self.assertIn("Trigger: event-driven", text)
            self.assertIn("Declared status: active", text)
            self.assertIn("Last reviewed: 2026-08-10", text)
            self.assertIn("Next review: 2026-08-19", text)
            self.assertIn("Git state: dirty", text)
            self.assertIn(
                f"Observed HEAD: {_git(root, 'rev-parse', 'HEAD').strip()}",
                text,
            )
            self.assertIn("Status/HEAD relation: not verified", text)
            self.assertIn("Project-local evidence: `PROJECT_STATUS.md`", text)
            self.assertIn("Shallow field gaps: none", text)
            self.assertIn(
                "This line covers only missing values in the shallow fields above.",
                text,
            )
            self.assertNotIn(str(root), text)
            self.assertNotIn("private-feature-branch", text)
            self.assertNotIn("Observed branch", text)
            self.assertNotIn("private-plan.txt", text)
            self.assertNotIn("SECRET_CONTEXT", text)
            self.assertEqual(_snapshot(root), before)

    def test_unknown_status_and_dates_do_not_echo_raw_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_project(root)
            (root / "PROJECT_STATUS.md").write_text(
                "\n".join(
                    [
                        "# Project Status",
                        "",
                        "Status: SECRET_STATUS_VALUE",
                        "last_reviewed: SECRET_REVIEW_VALUE",
                        "next_review: SECRET_NEXT_VALUE",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "alpha-project",
                    "event-driven",
                )
            )

            self.assertIn("Declared status: unknown", text)
            self.assertIn("Last reviewed: unknown", text)
            self.assertIn("Next review: unknown", text)
            self.assertIn(
                "Shallow field gaps: declared status, last_reviewed, next_review",
                text,
            )
            self.assertNotIn("SECRET_STATUS_VALUE", text)
            self.assertNotIn("SECRET_REVIEW_VALUE", text)
            self.assertNotIn("SECRET_NEXT_VALUE", text)

    def test_uncommitted_status_is_not_presented_as_head_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_project(root)
            (root / "PROJECT_STATUS.md").write_text(
                "\n".join(
                    [
                        "# Project Status",
                        "",
                        "Status: paused",
                        "last_reviewed: 2026-08-12",
                        "next_review: 2026-08-20",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "alpha-project",
                    "event-driven",
                )
            )

            self.assertIn("Declared status: paused", text)
            self.assertIn("Git state: dirty", text)
            self.assertIn("Observed HEAD:", text)
            self.assertIn("Status/HEAD relation: not verified", text)

    def test_non_git_project_reports_not_applicable_without_snapshot(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_status(root)

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "non-git-project",
                    "manual",
                )
            )

            self.assertIn("Trigger: manual", text)
            self.assertIn("Git state: not_applicable", text)
            self.assertIn("Observed HEAD: not_applicable", text)
            self.assertNotIn(
                "Observed HEAD",
                text.split("Shallow field gaps:", 1)[1],
            )

    def test_unsafe_config_and_git_error_do_not_leak_raw_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_status(root)
            (root / ".project-agent.yml").write_text(
                "project:\n  status_file: C:\\private\\SECRET_STATUS.md\n",
                encoding="utf-8",
            )
            unavailable_git = GitInfo(
                is_repo=False,
                root=root,
                status_lines=[],
                last_commit_at=None,
                error="SECRET_GIT_ERROR",
                error_kind="unavailable",
            )

            with patch(
                "pma.handoff.collect_git_info",
                return_value=unavailable_git,
            ):
                text = build_handoff_text(
                    collect_handoff_observation(
                        root,
                        "alpha-project",
                        "event-driven",
                    )
                )

            self.assertIn("Git state: unavailable", text)
            self.assertIn("Declared status: unknown", text)
            self.assertIn("Project-local evidence: unknown", text)
            self.assertIn("project boundary", text)
            self.assertNotIn("SECRET_STATUS", text)
            self.assertNotIn("C:\\private", text)
            self.assertNotIn("SECRET_GIT_ERROR", text)

    def test_sensitive_status_filename_is_not_exposed_as_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sensitive = root / "private" / "secret-status.md"
            sensitive.parent.mkdir()
            sensitive.write_text("Status: active\n", encoding="utf-8")
            (root / ".project-agent.yml").write_text(
                "project:\n  status_file: private/secret-status.md\n",
                encoding="utf-8",
            )

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "alpha-project",
                    "event-driven",
                )
            )

            self.assertIn("Project-local evidence: unknown", text)
            self.assertNotIn("secret-status.md", text)
            self.assertNotIn("private/", text)

    def test_unknown_head_and_evidence_are_reported_as_gaps(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _git(root, "init", "--quiet")
            _write_status(root)
            (root / ".project-agent.yml").write_text(
                "project:\n  status_file: missing.md\n",
                encoding="utf-8",
            )

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "alpha-project",
                    "manual",
                )
            )

            self.assertIn("Observed HEAD: unknown", text)
            self.assertIn("Project-local evidence: unknown", text)
            self.assertIn("Observed HEAD", text.split("Shallow field gaps:", 1)[1])
            self.assertIn(
                "project-local evidence",
                text.split("Shallow field gaps:", 1)[1],
            )

    def test_cli_rejects_unsafe_label_without_echoing_it(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        secret_label = "SECRET_LABEL\nsecond-line"

        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = main(
                [
                    "handoff",
                    "--path",
                    ".",
                    "--project",
                    secret_label,
                    "--trigger",
                    "event-driven",
                ]
            )

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("SECRET_LABEL", stderr.getvalue())

    def test_cli_does_not_echo_unexpected_os_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "pma.cli.collect_handoff_observation",
                side_effect=OSError("C:\\private\\SECRET_PATH"),
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = main(
                [
                    "handoff",
                    "--path",
                    ".",
                    "--project",
                    "alpha-project",
                    "--trigger",
                    "manual",
                ]
            )

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("SECRET_PATH", stderr.getvalue())
        self.assertNotIn("C:\\private", stderr.getvalue())

    def test_output_does_not_claim_receipt_or_owner_decision(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_project(root)

            text = build_handoff_text(
                collect_handoff_observation(
                    root,
                    "alpha-project",
                    "event-driven",
                )
            )

            self.assertNotIn("受領済み", text)
            self.assertNotIn("反映確認済み", text)
            self.assertIn("Draft only: this command has not sent", text)
            self.assertIn("変更内容、節目、オーナー判断", text)
            self.assertIn("オーナー付きStewardによる受領", text)
            self.assertIn("プロジェクト内の正本", text)
            self.assertIn("正式ブランチへの反映", text)
            self.assertIn("プロジェクト識別子と場所の対応", text)
            self.assertIn("介入時期", text)

    def test_python_module_process_completes_without_writes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_project(root)
            before = _snapshot(root)
            git_before = _git_metadata_snapshot(root)

            completed = _run_pma_process(root)

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stderr, "")
            self.assertIn(
                "Caller-supplied project: `alpha-project`",
                completed.stdout,
            )
            self.assertIn("Trigger: timing-driven", completed.stdout)
            self.assertEqual(_snapshot(root), before)
            self.assertEqual(_git_metadata_snapshot(root), git_before)


def _init_project(root: Path) -> None:
    _git(root, "init", "--quiet")
    (root / "README.md").write_text("# Test project\n", encoding="utf-8")
    _write_status(root)
    (root / "docs").mkdir()
    (root / "docs" / "design.md").write_text("# Design\n", encoding="utf-8")
    _git(root, "add", "README.md", "PROJECT_STATUS.md", "docs/design.md")
    _git(
        root,
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test User",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    _git(root, "branch", "-m", "private-feature-branch")


def _write_status(root: Path) -> None:
    (root / "PROJECT_STATUS.md").write_text(
        "\n".join(
            [
                "# Project Status",
                "",
                "Status: active",
                "Last updated: 2026-08-10",
                "last_reviewed: 2026-08-10",
                "next_review: 2026-08-19",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def _git_metadata_snapshot(root: Path) -> tuple[str, bytes, str]:
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    return (
        _git(root, "rev-parse", "HEAD"),
        index_path.read_bytes(),
        _git(root, "status", "--porcelain=v1", "--untracked-files=all"),
    )


def _run_pma_process(root: Path) -> subprocess.CompletedProcess[str]:
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
            "handoff",
            "--path",
            str(root),
            "--project",
            "alpha-project",
            "--trigger",
            "timing-driven",
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
