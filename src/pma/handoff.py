from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .config import load_config
from .git_utils import GitInfo, collect_git_info
from .status import (
    ProjectStatus,
    is_recognized_status,
    normalize_status,
    parse_date,
    read_project_status,
)


Trigger = Literal["manual", "event-driven", "timing-driven"]
VALID_TRIGGERS = frozenset({"manual", "event-driven", "timing-driven"})


class HandoffInputError(ValueError):
    """Raised when a handoff observation cannot be collected safely."""


@dataclass(frozen=True)
class HandoffObservation:
    project: str
    observed_at: datetime
    trigger: Trigger
    declared_status: str | None
    last_reviewed: str | None
    next_review: str | None
    git_state: Literal["clean", "dirty", "unavailable", "not_applicable"]
    head_commit: str | None
    evidence_path: str | None
    observation_gaps: tuple[str, ...]


def collect_handoff_observation(
    path: Path,
    project: str,
    trigger: Trigger,
    *,
    observed_at: datetime | None = None,
) -> HandoffObservation:
    if not _is_safe_project_label(project):
        raise HandoffInputError(
            "--project は改行や制御文字を含まない120文字以内の識別子にしてください。"
        )
    if trigger not in VALID_TRIGGERS:
        raise HandoffInputError("triggerを認識できませんでした。")

    try:
        requested_path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HandoffInputError("指定pathを確認できませんでした。") from exc
    if not requested_path.is_dir():
        raise HandoffInputError("--path にはproject内のdirectoryを指定してください。")

    try:
        git = collect_git_info(requested_path)
    except OSError:
        git = GitInfo(
            is_repo=False,
            root=requested_path,
            status_lines=[],
            last_commit_at=None,
            error="Git状態を確認できませんでした。",
            error_kind="unavailable",
        )
    gaps: list[str] = []
    if git.error_kind == "unavailable":
        project_status = _unavailable_status(requested_path)
        evidence_path = None
        gaps.extend(
            [
                "project boundary",
                "status file（project境界を確認できないため）",
            ]
        )
    else:
        project_root = git.root if git.is_repo else requested_path
        config_result = load_config(project_root)
        if config_result.load_state == "unavailable":
            project_status = _unavailable_status(project_root)
            evidence_path = None
            gaps.append("status file（設定を安全に使用できないため）")
        else:
            project_status = read_project_status(
                project_root,
                config_result.config.status_file,
            )
            evidence_path = _relative_evidence_path(project_root, project_status)
            if not project_status.exists:
                gaps.append("status file")

    declared_status = _recognized_status(project_status.status)
    if declared_status is None:
        gaps.append("declared status")

    last_reviewed = _valid_date(project_status.last_reviewed)
    if last_reviewed is None:
        gaps.append("last_reviewed")

    next_review = _valid_date(project_status.next_review)
    if next_review is None:
        gaps.append("next_review")

    git_state = _git_state(git)
    if git_state == "unavailable":
        gaps.append("Git snapshot")
    head_commit = git.head_commit if git.is_repo and not git.error_kind else None
    if head_commit is None and git_state != "not_applicable":
        gaps.append("Observed HEAD")
    if evidence_path is None:
        gaps.append("project-local evidence")

    return HandoffObservation(
        project=project.strip(),
        observed_at=observed_at or datetime.now().astimezone(),
        trigger=trigger,
        declared_status=declared_status,
        last_reviewed=last_reviewed,
        next_review=next_review,
        git_state=git_state,
        head_commit=head_commit,
        evidence_path=evidence_path,
        observation_gaps=tuple(dict.fromkeys(gaps)),
    )


def build_handoff_text(observation: HandoffObservation) -> str:
    lines = [
        "# Caddie handoff observation",
        "",
        "Draft only: this command has not sent, received, or recorded an event.",
        "",
        f"Caller-supplied project: `{observation.project}`",
        "Project/path association: not verified by this command",
        f"Observed at: {observation.observed_at.isoformat(timespec='seconds')}",
        f"Trigger: {observation.trigger}",
        f"Declared status: {observation.declared_status or 'unknown'}",
        f"Last reviewed: {observation.last_reviewed or 'unknown'}",
        f"Next review: {observation.next_review or 'unknown'}",
        f"Git state: {observation.git_state}",
        f"Observed HEAD: {_head_text(observation)}",
        "Status/HEAD relation: not verified by this command",
        (
            f"Project-local evidence: `{observation.evidence_path}`"
            if observation.evidence_path
            else "Project-local evidence: unknown"
        ),
        (
            "Shallow field gaps: " + ", ".join(observation.observation_gaps)
            if observation.observation_gaps
            else "Shallow field gaps: none"
        ),
        "This line covers only missing values in the shallow fields above.",
        "",
        (
            "この観測だけでは、変更内容、節目、オーナー判断、オーナー付きStewardによる"
            "受領、プロジェクト内の正本や正式ブランチへの反映、プロジェクト識別子と"
            "場所の対応、介入時期を確定しません。"
        ),
    ]
    return "\n".join(lines) + "\n"


def _is_safe_project_label(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and len(stripped) <= 120 and all(
        character != "`" and character.isprintable()
        for character in stripped
    )


def _unavailable_status(root: Path) -> ProjectStatus:
    return ProjectStatus(
        path=root / "PROJECT_STATUS.md",
        exists=False,
        status=None,
        last_updated=None,
        last_reviewed=None,
        next_review=None,
        warnings=[],
        read_state="unavailable",
    )


def _relative_evidence_path(root: Path, status: ProjectStatus) -> str | None:
    if not status.exists or status.read_state != "loaded":
        return None
    try:
        relative = status.path.relative_to(root).as_posix()
    except ValueError:
        return None
    return relative if _is_safe_output_value(relative) else None


def _is_safe_output_value(value: str) -> bool:
    return bool(value) and all(
        character != "`" and character.isprintable()
        for character in value
    )


def _recognized_status(value: str | None) -> str | None:
    if not is_recognized_status(value):
        return None
    return normalize_status(value)


def _valid_date(value: str | None) -> str | None:
    return value if parse_date(value) is not None else None


def _git_state(
    git: GitInfo,
) -> Literal["clean", "dirty", "unavailable", "not_applicable"]:
    if git.error_kind == "unavailable":
        return "unavailable"
    if not git.is_repo:
        return "not_applicable"
    return "dirty" if git.status_lines else "clean"


def _head_text(observation: HandoffObservation) -> str:
    if observation.git_state == "not_applicable":
        return "not_applicable"
    return observation.head_commit or "unknown"
