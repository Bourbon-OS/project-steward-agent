"""Real Git regression checks for read-only CLI observations."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str, optional_locks: bool = False) -> str:
    command = ["git"]
    if not optional_locks:
        command.append("--no-optional-locks")
    command += ["-C", str(root), *args]
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="1")
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            encoding="utf-8", check=True, timeout=30)
    return result.stdout


def make_repo(root: Path, *, configured: bool = True) -> None:
    git(root, "init", "--quiet")
    (root / "README.md").write_text("# Example\nSee PROJECT_STATUS.md\n", encoding="utf-8")
    (root / "PROJECT_STATUS.md").write_text(
        "Status: active\nLast updated: 2026-10-05\nnext_review: 2026-10-30\n", encoding="utf-8")
    (root / "work.md").write_text("Original\n", encoding="utf-8")
    if configured:
        (root / ".project-agent.yml").write_text(
            "project:\n  status_file: PROJECT_STATUS.md\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
        "commit", "--quiet", "-m", "Fixture")
    # Same content, changed stat information: ordinary status can refresh index.
    path = root / "README.md"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


def fingerprint(root: Path) -> dict:
    index = root / ".git/index"
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "index_mtime_ns": index.stat().st_mtime_ns,
        "files": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob("*") if p.is_file()},
    }


class GitReadOnlyTests(unittest.TestCase):
    def test_control_plain_status_refreshes_stale_index(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_repo(root)
            before = (root / ".git/index").read_bytes()
            git(root, "status", "--short", optional_locks=True)
            self.assertNotEqual(before, (root / ".git/index").read_bytes(),
                                "control must reproduce optional index refresh")

    def test_scan_and_handoff_preserve_git_and_working_files(self) -> None:
        for configured in (True, False):
            for command in ("scan", "handoff"):
                with self.subTest(configured=configured, command=command), TemporaryDirectory() as directory:
                    root = Path(directory)
                    make_repo(root, configured=configured)
                    (root / "work.md").write_text("Staged\n", encoding="utf-8")
                    git(root, "add", "work.md")
                    (root / "work.md").write_text("Unstaged after staged\n", encoding="utf-8")
                    (root / "new.md").write_text("Untracked\n", encoding="utf-8")
                    path = root / "README.md"
                    stat = path.stat()
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
                    before = fingerprint(root)
                    args = [command, "--path", str(root)]
                    if command == "handoff":
                        args += ["--project", "example", "--trigger", "manual"]
                    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                               GIT_OPTIONAL_LOCKS="1")
                    result = subprocess.run([sys.executable, "-S", "-m", "pma", *args],
                                            cwd=root, env=env, capture_output=True, text=True,
                                            encoding="utf-8", timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout)
                    self.assertEqual(before, fingerprint(root))


if __name__ == "__main__":
    unittest.main()
