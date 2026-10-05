from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal


GIT_COMMAND_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_RETURN_CODE = 124


class GitCommandUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GitInfo:
    is_repo: bool
    root: Path
    status_lines: list[str]
    last_commit_at: str | None
    head_commit: str | None = None
    branch: str | None = None
    current_paths: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None


@dataclass(frozen=True)
class GitLineObservation:
    state: Literal[
        "confirmed",
        "uncommitted",
        "not_in_history",
        "unavailable",
        "not_applicable",
        "not_observable",
    ]
    commit_at: str | None = None
    commit: str | None = None


def collect_git_info(path: Path) -> GitInfo:
    resolved = path.resolve()
    root_result = _run_git(resolved, ["rev-parse", "--show-toplevel"])
    if root_result.returncode != 0:
        error = _clean_error(root_result.stderr)
        error_kind = _classify_root_error(error)
        return GitInfo(
            is_repo=False,
            root=resolved,
            status_lines=[],
            last_commit_at=None,
            error=error or _default_error(error_kind),
            error_kind=error_kind,
        )

    repo_root = Path(root_result.stdout.strip()).resolve()
    status_result = _run_git(
        repo_root,
        [
            "-c",
            "core.quotePath=false",
            "status",
            "--short",
            "--untracked-files=all",
        ],
    )
    if status_result.returncode != 0:
        return GitInfo(
            is_repo=True,
            root=repo_root,
            status_lines=[],
            last_commit_at=None,
            error=_clean_error(status_result.stderr) or "git status に失敗しました。",
            error_kind="unavailable",
        )

    status_lines = [
        line.rstrip() for line in status_result.stdout.splitlines() if line.strip()
    ]
    log_result = _run_git(repo_root, ["log", "-1", "--format=%cI"])
    if _is_timeout(log_result):
        return _timed_out_git_info(repo_root, status_lines, log_result)
    last_commit_at = log_result.stdout.strip() if log_result.returncode == 0 else None

    head_result = _run_git(repo_root, ["rev-parse", "--verify", "HEAD"])
    if _is_timeout(head_result):
        return _timed_out_git_info(
            repo_root,
            status_lines,
            head_result,
            last_commit_at=last_commit_at,
        )
    head_commit = head_result.stdout.strip() if head_result.returncode == 0 else None

    branch_result = _run_git(repo_root, ["branch", "--show-current"])
    if _is_timeout(branch_result):
        return _timed_out_git_info(
            repo_root,
            status_lines,
            branch_result,
            last_commit_at=last_commit_at,
            head_commit=head_commit,
        )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    if head_commit and not branch:
        branch = "detached HEAD"

    current_paths_result = _run_git(
        repo_root,
        [
            "-c",
            "core.quotePath=false",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
    )
    if _is_timeout(current_paths_result):
        return _timed_out_git_info(
            repo_root,
            status_lines,
            current_paths_result,
            last_commit_at=last_commit_at,
            head_commit=head_commit,
            branch=branch,
        )
    if current_paths_result.returncode != 0:
        return GitInfo(
            is_repo=True,
            root=repo_root,
            status_lines=status_lines,
            last_commit_at=last_commit_at,
            head_commit=head_commit,
            branch=branch,
            current_paths=[],
            error=(
                _clean_error(current_paths_result.stderr)
                or "Gitの変更pathを確認できませんでした。"
            ),
            error_kind="unavailable",
        )
    current_paths = (
        _parse_porcelain_paths(current_paths_result.stdout)
        if current_paths_result.returncode == 0
        else []
    )

    return GitInfo(
        is_repo=True,
        root=repo_root,
        status_lines=status_lines,
        last_commit_at=last_commit_at or None,
        head_commit=head_commit or None,
        branch=branch or None,
        current_paths=current_paths,
        error=None,
        error_kind=None,
    )


def split_status_lines(status_lines: list[str]) -> tuple[list[str], list[str]]:
    untracked = [line for line in status_lines if line.startswith("??")]
    changed = [line for line in status_lines if not line.startswith("??")]
    return changed, untracked


def list_git_scan_files(root: Path) -> list[Path]:
    result = _run_git(
        root,
        ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    )
    if result.returncode != 0:
        raise GitCommandUnavailable(
            _clean_error(result.stderr)
            or "Gitの走査対象ファイルを確認できませんでした。"
        )

    return [
        root / relative
        for relative in result.stdout.split("\0")
        if relative
    ]


def collect_git_line_observation(
    git: GitInfo,
    path: Path,
    line_number: int | None,
    line_text: str | None,
) -> GitLineObservation:
    """Return the Git-backed lower bound for how long one line is unchanged."""
    if git.error_kind == "unavailable":
        return GitLineObservation(state="unavailable")
    if not git.is_repo:
        return GitLineObservation(state="not_applicable")
    if not line_number or line_number < 1 or line_text is None:
        return GitLineObservation(state="not_observable")

    root = git.root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return GitLineObservation(state="not_observable")
    relative = resolved.relative_to(root).as_posix()

    tracked_result = _run_git(
        root,
        ["ls-files", "--error-unmatch", "--", relative],
    )
    if _is_timeout(tracked_result):
        return GitLineObservation(state="unavailable")
    if tracked_result.returncode != 0:
        return GitLineObservation(state="not_in_history")

    blame_result = _run_git(
        root,
        [
            "blame",
            "--line-porcelain",
            "-L",
            f"{line_number},{line_number}",
            "--",
            relative,
        ],
    )
    if _is_timeout(blame_result) or blame_result.returncode != 0:
        return GitLineObservation(state="unavailable")

    lines = blame_result.stdout.splitlines()
    if not lines:
        return GitLineObservation(state="unavailable")
    blamed_lines = [line[1:] for line in lines if line.startswith("\t")]
    if blamed_lines != [line_text]:
        return GitLineObservation(state="unavailable")
    commit = lines[0].split(maxsplit=1)[0]
    if commit and set(commit) == {"0"}:
        return GitLineObservation(state="uncommitted")

    metadata = {}
    for line in lines[1:]:
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        if key in {"committer-time", "committer-tz"}:
            metadata[key] = value.strip()

    commit_at = _format_git_timestamp(
        metadata.get("committer-time"),
        metadata.get("committer-tz"),
    )
    if not commit_at:
        return GitLineObservation(state="unavailable")
    return GitLineObservation(
        state="confirmed",
        commit_at=commit_at,
        commit=commit or None,
    )


def _parse_porcelain_paths(raw: str) -> list[str]:
    fields = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry or len(entry) < 4:
            continue

        status = entry[:2]
        path = entry[3:]
        if path:
            paths.append(path.replace("\\", "/"))

        if "R" in status or "C" in status:
            index += 1

    return paths


def _format_git_timestamp(
    timestamp_value: str | None,
    timezone_value: str | None,
) -> str | None:
    if not timestamp_value or not timezone_value:
        return None
    try:
        timestamp = int(timestamp_value)
        sign = 1 if timezone_value[0] == "+" else -1
        hours = int(timezone_value[1:3])
        minutes = int(timezone_value[3:5])
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return datetime.fromtimestamp(timestamp, tz=offset).isoformat()
    except (IndexError, OSError, OverflowError, TypeError, ValueError):
        return None


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    # A read-only sensor must also avoid Git's optional index stat refresh.
    command = ["git", "--no-optional-locks", "-C", str(cwd), *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            command,
            GIT_TIMEOUT_RETURN_CODE,
            stdout="",
            stderr=(
                "Git command timed out after "
                f"{GIT_COMMAND_TIMEOUT_SECONDS} seconds."
            ),
        )


def _is_timeout(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == GIT_TIMEOUT_RETURN_CODE


def _timed_out_git_info(
    root: Path,
    status_lines: list[str],
    result: subprocess.CompletedProcess[str],
    *,
    last_commit_at: str | None = None,
    head_commit: str | None = None,
    branch: str | None = None,
) -> GitInfo:
    return GitInfo(
        is_repo=True,
        root=root,
        status_lines=status_lines,
        last_commit_at=last_commit_at,
        head_commit=head_commit,
        branch=branch,
        current_paths=[],
        error=_clean_error(result.stderr),
        error_kind="unavailable",
    )


def _clean_error(value: str) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) > 260:
        return f"{cleaned[:257]}..."
    return cleaned


def _classify_root_error(error: str) -> str:
    lowered = error.lower()
    if "not a git repository" in lowered:
        return "not_repo"
    return "unavailable"


def _default_error(error_kind: str) -> str:
    if error_kind == "not_repo":
        return "Git リポジトリではありません。"
    return "Git状態を確認できませんでした。"
