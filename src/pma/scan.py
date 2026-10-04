from __future__ import annotations

import re
from os.path import abspath
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from .config import ConfigResult, load_config
from .file_safety import (
    is_allowed_text_file as _is_allowed_text_file,
    is_sensitive_path as _is_sensitive_path,
)
from .fixed_input import FixedInputObservation, inspect_fixed_input
from .git_utils import (
    GitCommandUnavailable,
    GitInfo,
    GitLineObservation,
    collect_git_info,
    collect_git_line_observation,
    list_git_scan_files,
    split_status_lines,
)
from .status import ProjectStatus, normalize_status, parse_date, read_project_status


SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "reports"}
MAX_TEXT_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class KeywordMatch:
    path: str
    line_number: int
    keyword: str
    is_current: bool = False


@dataclass(frozen=True)
class FilePresence:
    path: str
    exists: bool


@dataclass(frozen=True)
class SourceOfTruthPresence:
    path: str
    exists: bool
    readme_linked: bool | None
    is_readme: bool = False
    is_status_file: bool = False


@dataclass(frozen=True)
class Risk:
    priority: int
    code: str
    severity: Literal["critical", "high", "medium", "low"]
    subject: str
    title: str
    evidence: str
    interpretation: str
    suggestion: str
    status: str = "未決"


@dataclass(frozen=True)
class OverallJudgment:
    continuity: Literal["ready", "at_risk", "unknown"]
    reason: str


@dataclass(frozen=True)
class ScanResult:
    requested_path: Path
    project_path: Path
    run_at: datetime
    git: GitInfo
    config_result: ConfigResult
    project_status: ProjectStatus
    fixed_input: FixedInputObservation
    files: dict[str, FilePresence]
    source_of_truth: dict[str, SourceOfTruthPresence]
    changed_files: list[str]
    untracked_files: list[str]
    keyword_matches: list[KeywordMatch]
    risks: list[Risk]
    overall_judgment: OverallJudgment
    consultation: str
    status_line_observation: GitLineObservation
    observation_consistency: Literal[
        "stable",
        "changed",
        "unavailable",
        "not_applicable",
    ] = "stable"


ObservedPath = tuple[Path, bool]
ObservedPathState = tuple[str, str, int, int, str]


def scan_path(path: Path) -> ScanResult:
    requested_path = path.resolve()
    run_at = datetime.now().astimezone()
    git = collect_git_info(requested_path)
    project_path = git.root if git.is_repo else requested_path
    config_result = load_config(project_path)
    observation_paths = _collect_observation_paths(
        project_path,
        config_result,
    )
    observation_path_state = _capture_observation_path_state(
        project_path,
        observation_paths,
    )
    if config_result.load_state in {"unavailable", "missing"}:
        project_status = ProjectStatus(
            path=project_path / config_result.config.status_file,
            exists=False,
            status=None,
            last_updated=None,
            last_reviewed=None,
            next_review=None,
            warnings=[],
            read_state="unavailable",
        )
        files = {
            name: _file_presence_within_project(project_path, name)
            for name in ("README.md", ".project-agent.yml")
        }
        source_of_truth = {}
    else:
        project_status = read_project_status(
            project_path, config_result.config.status_file
        )
        files = {
            name: _file_presence_within_project(project_path, name)
            for name in config_result.config.required_files
        }
        for required in (
            "README.md",
            config_result.config.status_file,
            ".project-agent.yml",
        ):
            files.setdefault(
                required, _file_presence_within_project(project_path, required)
            )
        source_of_truth = inspect_source_of_truth(
            project_path,
            config_result.config.source_of_truth,
            config_result.config.status_file,
        )

    fixed_input = inspect_fixed_input(project_path, config_result)

    status_line_observation = collect_git_line_observation(
        git,
        project_status.path,
        project_status.status_line_number,
        project_status.status_line_text,
    )

    changed_files, untracked_files = split_status_lines(git.status_lines)
    keyword_scan_error: str | None = None
    if (
        git.error_kind == "unavailable"
        or not git.is_repo
        or config_result.load_state == "unavailable"
    ):
        keyword_matches = []
    else:
        try:
            keyword_matches = find_keyword_matches(
                project_path,
                config_result.config.footwork_keywords,
                config_result.config.exclude_paths,
                skip_paths=[
                    ".project-agent.yml",
                    _relative_status_path(project_path, project_status),
                ],
            )
        except GitCommandUnavailable as exc:
            keyword_matches = []
            keyword_scan_error = str(exc)
    keyword_matches = _mark_current_keyword_matches(
        keyword_matches, git.current_paths
    )
    final_git = (
        collect_git_info(project_path)
        if git.is_repo and git.error_kind != "unavailable"
        else None
    )
    final_config = (
        load_config(project_path)
        if git.is_repo and git.error_kind != "unavailable"
        else None
    )
    final_path_state = _capture_observation_path_state(
        project_path,
        observation_paths,
    )
    observation_consistency = _check_observation_consistency(
        git,
        final_git,
        config_result,
        final_config,
        observation_path_state,
        final_path_state,
    )
    risks = detect_risks(
        run_at=run_at,
        git=git,
        project_status=project_status,
        fixed_input=fixed_input,
        files=files,
        source_of_truth=source_of_truth,
        changed_files=changed_files,
        untracked_files=untracked_files,
        keyword_matches=keyword_matches,
        keyword_scan_error=keyword_scan_error,
        config_result=config_result,
        observation_consistency=observation_consistency,
    )
    overall_judgment = make_overall_judgment(risks)
    consultation = make_consultation(risks)

    return ScanResult(
        requested_path=requested_path,
        project_path=project_path,
        run_at=run_at,
        git=git,
        config_result=config_result,
        project_status=project_status,
        fixed_input=fixed_input,
        files=files,
        source_of_truth=source_of_truth,
        changed_files=changed_files,
        untracked_files=untracked_files,
        keyword_matches=keyword_matches,
        risks=risks,
        overall_judgment=overall_judgment,
        consultation=consultation,
        status_line_observation=status_line_observation,
        observation_consistency=observation_consistency,
    )


def find_keyword_matches(
    root: Path,
    keywords: list[str],
    exclude_paths: list[str] | None = None,
    skip_paths: list[str] | None = None,
) -> list[KeywordMatch]:
    matches: list[KeywordMatch] = []
    normalized_keywords = [
        (priority, keyword, keyword.lower())
        for priority, keyword in enumerate(keywords)
    ]
    normalized_skip_paths = {
        _normalize_relative_path(path)
        for path in (skip_paths or [])
        if _normalize_relative_path(path)
    }

    for file_path in _iter_candidate_files(root, exclude_paths or []):
        try:
            if file_path.stat().st_size > MAX_TEXT_FILE_BYTES:
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        relative = file_path.relative_to(root).as_posix()
        if relative in normalized_skip_paths:
            continue

        representative: tuple[int, KeywordMatch] | None = None
        for line_number, line in enumerate(text.splitlines(), start=1):
            for priority, keyword, lowered_keyword in normalized_keywords:
                if _line_contains_keyword(line, keyword, lowered_keyword):
                    candidate = (
                        priority,
                        KeywordMatch(
                            path=relative,
                            line_number=line_number,
                            keyword=keyword,
                        ),
                    )
                    if representative is None or priority < representative[0]:
                        representative = candidate
                    if priority == 0:
                        break
            if representative and representative[0] == 0:
                break

        if representative:
            matches.append(representative[1])

    return matches


def detect_risks(
    *,
    run_at: datetime,
    git: GitInfo,
    project_status: ProjectStatus,
    fixed_input: FixedInputObservation,
    files: dict[str, FilePresence],
    source_of_truth: dict[str, SourceOfTruthPresence],
    changed_files: list[str],
    untracked_files: list[str],
    keyword_matches: list[KeywordMatch],
    keyword_scan_error: str | None,
    config_result: ConfigResult,
    observation_consistency: Literal[
        "stable",
        "changed",
        "unavailable",
        "not_applicable",
    ] = "stable",
) -> list[Risk]:
    risks: list[Risk] = []

    if observation_consistency == "changed":
        return [
            Risk(
                priority=1,
                code="scan_changed_during_observation",
                severity="critical",
                subject="観測スナップショット",
                title="走査中に観測対象が変化しました",
                evidence=(
                    "走査開始時と終了時でGit状態、設定、または読み取り対象が一致しません。"
                ),
                interpretation=(
                    "異なる時点の状態が混ざる可能性があるため、今回の状態値とfindingは確定できません。"
                ),
                suggestion=(
                    "変更が落ち着いた時点で、対象を書き換えずに再走査するのがよさそうです。"
                ),
            )
        ]

    if observation_consistency == "unavailable":
        if git.error_kind == "unavailable":
            unavailable_risks = [_make_git_state_unavailable_risk(git)]
            if config_result.load_state == "unavailable":
                unavailable_risks.append(_make_config_unavailable_risk())
            return unavailable_risks
        return [
            Risk(
                priority=1,
                code="scan_consistency_unavailable",
                severity="critical",
                subject="観測スナップショット",
                title="走査終了時のGit状態を再確認できませんでした",
                evidence=(
                    "走査開始時と終了時が同じGit状態か確認できません。"
                ),
                interpretation=(
                    "異なる時点の状態が混ざっていないと確認できないため、今回の状態値とfindingは確定できません。"
                ),
                suggestion=(
                    "Git状態を読み取れる環境で、対象を書き換えずに再走査するのがよさそうです。"
                ),
            )
        ]

    if git.error_kind == "unavailable":
        risks.append(_make_git_state_unavailable_risk(git))
    elif not git.is_repo:
        risks.append(
            Risk(
                priority=1,
                code="not_git_repo",
                severity="high",
                subject="Git管理",
                title="Git リポジトリではありません",
                evidence=git.error or "git rev-parse に失敗しました。",
                interpretation="Git履歴を使う足場確認は適用できません。Git管理が必要かは担当判断です。",
                suggestion="対象pathが正しいかを確認し、Git管理が必要ならプロジェクト担当側へ方針確認するのがよさそうです。",
            )
        )

    if config_result.load_state == "unavailable":
        risks.append(_make_config_unavailable_risk())
        missing_readme = _make_missing_readme_risk(files)
        if missing_readme:
            risks.append(missing_readme)
        if git.error_kind != "unavailable":
            uncommitted = _make_uncommitted_risk(changed_files)
            if uncommitted:
                risks.append(uncommitted)
        return sorted(risks, key=lambda risk: risk.priority)

    status_file = config_result.config.status_file
    status_file_outside = any(
        "プロジェクト外" in warning for warning in project_status.warnings
    )
    status_file_unreadable = any(
        "読めませんでした" in warning for warning in project_status.warnings
    )
    status_file_disallowed = any(
        "安全な読み取り対象ではない" in warning
        for warning in project_status.warnings
    )
    if status_file_outside:
        risks.append(
            Risk(
                priority=2,
                code="status_file_outside_project",
                severity="high",
                subject=status_file,
                title="状態ファイルがプロジェクト外を指しています",
                evidence=" / ".join(project_status.warnings),
                interpretation="project-localな現在状態を安全な範囲で確認できません。",
                suggestion="project.status_file をプロジェクト内の状態ファイルへ向けるのがよさそうです。",
            )
        )
    elif not project_status.exists and config_result.exists:
        risks.append(
            Risk(
                priority=2,
                code="missing_project_status",
                severity="high",
                subject=status_file,
                title=f"{status_file} がありません",
                evidence=(
                    " / ".join(project_status.warnings)
                    or "現在の状態宣言を読めませんでした。"
                ),
                interpretation="現在状態と次回確認のproject-localな根拠を確認できません。",
                suggestion="まず現在の status だけを置く最小ファイル案を作るのがよさそうです。",
            )
        )
    elif status_file_disallowed:
        risks.append(
            Risk(
                priority=2,
                code="status_file_disallowed",
                severity="high",
                subject=status_file,
                title="状態ファイルを安全に読めません",
                evidence=" / ".join(project_status.warnings),
                interpretation="状態ファイルは存在しますが、安全境界のため内容を未確認として扱います。",
                suggestion="project.status_file を機密名ではない許可テキスト形式の状態ファイルへ向けるのがよさそうです。",
            )
        )
    elif status_file_unreadable:
        risks.append(
            Risk(
                priority=2,
                code="status_file_unreadable",
                severity="high",
                subject=status_file,
                title="状態ファイルを読めませんでした",
                evidence=" / ".join(project_status.warnings),
                interpretation="状態ファイルの内容を確認できないため、現在状態は未確認です。",
                suggestion="ファイル種別と読み取り権限を確認し、読めない範囲を未確認として扱うのがよさそうです。",
            )
        )

    if project_status.exists and project_status.duplicate_fields:
        risks.append(
            Risk(
                priority=2,
                code="ambiguous_status_fields",
                severity="high",
                subject=status_file,
                title="状態ファイルに重複した状態項目があります",
                evidence=(
                    "重複した項目: "
                    f"{', '.join(project_status.duplicate_fields)}。"
                    "値そのものはfindingへ転載していません。"
                ),
                interpretation="重複した項目はどの記述が現在値か一意に決められないため、値を採用せず関連する状態判定を未確認として扱います。",
                suggestion="状態ファイル内の現行メタデータと例・過去記録を分け、状態項目を1組だけにするのがよさそうです。",
            )
        )

    if fixed_input.scope_state == "legacy":
        status_document_budget = _make_status_document_budget_risk(
            project_status,
            config_result,
        )
        if status_document_budget:
            risks.append(status_document_budget)
    risks.extend(_make_fixed_input_risks(fixed_input))

    missing_readme = _make_missing_readme_risk(files)
    if missing_readme:
        risks.append(missing_readme)

    project_root = config_result.path.parent.resolve()
    special_required = {
        _resolve_project_path(project_root, "README.md"),
        _resolve_project_path(
            project_root, config_result.config.status_file
        ),
        _resolve_project_path(project_root, ".project-agent.yml"),
    }
    missing_required = [
        name
        for name in config_result.config.required_files
        if not files.get(name, FilePresence(name, False)).exists
        and _resolve_project_path(project_root, name) not in special_required
    ]
    if missing_required:
        risks.append(
            Risk(
                priority=3,
                code="missing_required_files",
                severity="high",
                subject="checks.required_files",
                title="設定された必須ファイルがありません",
                evidence=_path_list_evidence(missing_required),
                interpretation="設定上必要な足場を現在のproject内で確認できません。",
                suggestion="設定が現在も有効か確認し、必要なら既存の正しいファイルへ導線を戻すのがよさそうです。",
            )
        )

    missing_sources = [
        source.path
        for source in source_of_truth.values()
        if not source.exists
        and not source.is_readme
        and not source.is_status_file
    ]
    if missing_sources:
        risks.append(
            Risk(
                priority=3,
                code="missing_source_of_truth",
                severity="high",
                subject="project.source_of_truth",
                title="設定された正本pathを確認できません",
                evidence=_path_list_evidence(missing_sources),
                interpretation="正本が欠落したか、設定の導線が古い可能性があります。",
                suggestion="正本を新設せず、まず設定が既存の正しいpathを指しているか確認するのがよさそうです。",
            )
        )

    next_review_risk = _make_next_review_risk(run_at, project_status)
    if next_review_risk:
        risks.append(next_review_risk)

    actionable_untracked, _ = partition_untracked_files(
        untracked_files,
        config_result.config.exclude_paths,
    )
    if actionable_untracked:
        risks.append(
            Risk(
                priority=4,
                code="untracked_files",
                severity="high",
                subject="working tree",
                title="確認が必要な未追跡ファイルがあります",
                evidence=f"{len(actionable_untracked)} 件の未追跡ファイルが設定上の背景に含まれていません。",
                interpretation="Git履歴だけでは再現できない作業や生成物が含まれる可能性があります。",
                suggestion="まず管理対象に見えるものだけ分類案を作るのがよさそうです。",
            )
        )

    uncommitted = _make_uncommitted_risk(changed_files)
    if uncommitted:
        risks.append(uncommitted)

    risks.extend(
        _make_state_activity_risks(
            run_at, git, project_status, config_result
        )
    )

    missing_status = [
        warning
        for warning in project_status.warnings
        if "status が見つかりません" in warning
    ]
    if project_status.exists and missing_status:
        risks.append(
            Risk(
                priority=7,
                code="missing_status",
                severity="medium",
                subject=status_file,
                title="状態ファイルにstatusがありません",
                evidence=" / ".join(missing_status),
                interpretation="作業状態別の鮮度判定を適用できません。",
                suggestion="現在の作業状態を確認し、状態ファイルのstatusへ短く残すのがよさそうです。",
            )
        )

    unrecognized_status = [
        warning
        for warning in project_status.warnings
        if "status は既知の互換値ではありません" in warning
    ]
    if project_status.exists and unrecognized_status:
        risks.append(
            Risk(
                priority=7,
                code="unrecognized_status",
                severity="medium",
                subject=status_file,
                title="statusが既知の互換値ではありません",
                evidence=(
                    " / ".join(unrecognized_status)
                    + " このため、状態別のstale判定は適用していません。"
                ),
                interpretation="Ashiba Stewardの既知語彙だけでは作業状態か別軸の値かを判断できません。",
                suggestion="work stateかlifecycle相当の値かを状態ファイルで確認し、自動修正せず担当者へ確認するのがよさそうです。",
            )
        )

    invalid_status_dates = [
        warning
        for warning in project_status.warnings
        if "日付として解釈できません" in warning
    ]
    if project_status.exists and invalid_status_dates:
        risks.append(
            Risk(
                priority=7,
                code="invalid_status_dates",
                severity="medium",
                subject=status_file,
                title="状態ファイルの日付が不正です",
                evidence=" / ".join(invalid_status_dates),
                interpretation="日付に基づく鮮度または次回確認の判定を適用できない項目があります。",
                suggestion="元の値を自動修正せず、正しい確認日または次回確認日を担当者と確認するのがよさそうです。",
            )
        )

    missing_review_fields = [
        warning
        for warning in project_status.warnings
        if "見つかりません" in warning
        and ("last_reviewed" in warning or "next_review" in warning)
    ]
    if project_status.exists and missing_review_fields:
        risks.append(
            Risk(
                priority=7,
                code="missing_review_fields",
                severity="medium",
                subject=status_file,
                title="review metadata が不足しています",
                evidence=" / ".join(missing_review_fields),
                interpretation="状態確認の鮮度または次回確認時期を機械的に評価できません。",
                suggestion="まず確認日と次回確認日だけ補うのがよさそうです。",
            )
        )

    unlinked_sources = [
        source.path
        for source in source_of_truth.values()
        if source.exists
        and not source.is_readme
        and not (
            source.is_status_file
            and (
                status_file_outside
                or status_file_unreadable
                or status_file_disallowed
                or not project_status.exists
            )
        )
        and source.readme_linked is False
    ]
    if unlinked_sources:
        risks.append(
            Risk(
                priority=8,
                code="source_of_truth_not_linked",
                severity="medium",
                subject="README.md",
                title="READMEから設定された正本への導線を確認できません",
                evidence=_path_list_evidence(unlinked_sources),
                interpretation="入口から既存の正本へ辿れない可能性があります。",
                suggestion="READMEに詳細を複製せず、既存の正本pathへの短いリンクだけを置くのがよさそうです。",
            )
        )

    if keyword_scan_error:
        risks.append(
            Risk(
                priority=7,
                code="keyword_scan_unavailable",
                severity="medium",
                subject="足場キーワード走査",
                title="足場キーワードを確認できませんでした",
                evidence=keyword_scan_error,
                interpretation="他の観測は継続していますが、キーワード候補の範囲は未確認です。",
                suggestion="対象を書き換えず、Gitのファイル一覧を確認できる環境で再走査するのがよさそうです。",
            )
        )

    current_keyword_matches = [
        match for match in keyword_matches if match.is_current
    ]
    if current_keyword_matches:
        risks.append(
            Risk(
                priority=8,
                code="footwork_keywords",
                severity="low",
                subject="今回変更されたファイル",
                title="今回変更されたファイルに足場キーワードがあります",
                evidence=f"今回変更された {len(current_keyword_matches)} ファイルにキーワード候補があります。既存不変の候補とは分けて評価しています。",
                interpretation="未決・仮置き・確認待ちの痕跡かもしれませんが、キーワード一致だけでは問題と断定できません。",
                suggestion="まず今回の変更に含まれる足場ToDoだけ確認するのがよさそうです。",
            )
        )

    for warning in config_result.warnings:
        risks.append(
            Risk(
                priority=9,
                code="config_warning",
                severity="low",
                subject=".project-agent.yml",
                title="設定ファイルの警告があります",
                evidence=warning,
                interpretation="既定値で走査を継続していますが、意図した設定と異なる可能性があります。",
                suggestion="MVP では既定値で続行し、必要になったら設定を整えるのがよさそうです。",
            )
        )

    return sorted(risks, key=lambda risk: risk.priority)


def _make_missing_readme_risk(
    files: dict[str, FilePresence],
) -> Risk | None:
    if files.get("README.md", FilePresence("README.md", False)).exists:
        return None
    return Risk(
        priority=3,
        code="missing_readme",
        severity="high",
        subject="README.md",
        title="README.md がありません",
        evidence="プロジェクトの入口になる文書を確認できませんでした。",
        interpretation="人間や別エージェントが正本・状態・運用方法へ辿れない可能性があります。",
        suggestion="まず最小の入口ファイル案を作るのがよさそうです。",
    )


def _make_uncommitted_risk(changed_files: list[str]) -> Risk | None:
    if not changed_files:
        return None
    return Risk(
        priority=5,
        code="uncommitted_changes",
        severity="medium",
        subject="working tree",
        title="未コミット変更があります",
        evidence=f"{len(changed_files)} 件の変更があります。",
        interpretation="作業内容や意図がまだGit履歴へ固定されていない可能性があります。",
        suggestion="後で迷わないように、変更内容を短く整理するのがよさそうです。",
    )


def _make_status_document_budget_risk(
    project_status: ProjectStatus,
    config_result: ConfigResult,
) -> Risk | None:
    if (
        project_status.read_state != "loaded"
        or project_status.character_count is None
        or project_status.line_count is None
    ):
        return None

    max_chars = config_result.config.status_max_chars
    max_lines = config_result.config.status_max_lines
    if (
        project_status.character_count <= max_chars
        and project_status.line_count <= max_lines
    ):
        return None

    return Risk(
        priority=7,
        code="status_document_over_budget",
        severity="medium",
        subject=config_result.config.status_file,
        title="状態文書単体が従来の確認目安を超えています",
        evidence=(
            f"状態文書は {project_status.character_count} 文字・"
            f"{project_status.line_count} 行です。設定された試行中の予算は "
            f"{max_chars} 文字・{max_lines} 行です。これは毎回読む情報の合計ではありません。"
            "本文はfindingへ転載していません。"
        ),
        interpretation=(
            "従来設定との互換警告です。自動適用されるプロジェクト指示や"
            "他の必読文書を含む実際の毎回読む範囲は未確認です。"
        ),
        suggestion=(
            "自動分割や削除はせず、毎回読む文書を設定へ明示した上で"
            "合計を浅く再確認するのがよさそうです。"
        ),
    )


def _make_fixed_input_risks(
    observation: FixedInputObservation,
) -> list[Risk]:
    if observation.scope_state in {"unconfirmed", "legacy"}:
        detail = (
            "従来設定では状態文書単体だけを確認できます。"
            if observation.scope_state == "legacy"
            else "設定がないため、実際の状態文書と毎回読む文書を特定していません。"
        )
        return [
            Risk(
                priority=8,
                code="fixed_input_scope_unconfirmed",
                severity="low",
                subject="毎回読む情報",
                title="毎回読む範囲を確認できません",
                evidence=detail,
                interpretation="条件付き資料や履歴を混ぜずに合計を判断する材料が不足しています。",
                suggestion=(
                    "自動適用されるプロジェクト指示と、開始時に必ず読む文書だけを"
                    "設定へ明示して浅く再確認するのがよさそうです。"
                ),
            )
        ]

    if observation.scope_state == "unavailable":
        return []

    if observation.measurement_state != "complete":
        failed = [
            item.path for item in observation.files if item.read_state != "loaded"
        ]
        return [
            Risk(
                priority=7,
                code="fixed_input_measurement_unavailable",
                severity="low",
                subject="毎回読む情報",
                title="毎回読む情報の合計を確認できません",
                evidence=(
                    f"設定された {len(failed)} 件を安全に読めませんでした。"
                    "本文や読み取れなかった値は転載していません。"
                ),
                interpretation="読めた文書だけの合計で合否を決めないよう、判定を保留しています。",
                suggestion="設定したpathと安全な読み取り範囲を確認するのがよさそうです。",
            )
        ]

    chars = observation.character_count or 0
    lines = observation.line_count or 0
    over_target = chars > observation.target_chars or lines > observation.target_lines
    if not over_target:
        return []

    exception_complete = bool(
        observation.exception_reason and observation.exception_review_condition
    )
    if exception_complete:
        return []

    high_cost = (
        chars > observation.high_cost_chars
        or lines > observation.high_cost_lines
    )
    return [
        Risk(
            priority=7 if high_cost else 8,
            code="fixed_input_high_cost" if high_cost else "fixed_input_review_needed",
            severity="medium" if high_cost else "low",
            subject="毎回読む情報",
            title=(
                "毎回読む情報が改善を優先する目安を超えています"
                if high_cost
                else "毎回読む情報が通常目標を超えています"
            ),
            evidence=(
                f"合計は {chars} 文字・{lines} 行です。通常目標は "
                f"{observation.target_chars} 文字・{observation.target_lines} 行、"
                f"改善を優先する目安は {observation.high_cost_chars} 文字・"
                f"{observation.high_cost_lines} 行です。本文はfindingへ転載していません。"
            ),
            interpretation=(
                "文字数はtoken数やクレジット量ではなく、毎回読む量を浅く比べる"
                "確認材料です。安全や権限に必要な情報は削減対象と断定しません。"
            ),
            suggestion=(
                "現在値と閉じた履歴を分けられるか確認し、必要な超過なら理由と"
                "再確認条件を設定するのがよさそうです。"
            ),
        )
    ]


def make_consultation(risks: list[Risk]) -> str:
    if not risks:
        return "大きな足場リスクは見つかりませんでした。今は追加対応なしで進めてよさそうです。"

    top = risks[0]
    if top.code == "scan_changed_during_observation":
        return "走査中に観測対象が変化したため、今回の状態は確定しません。変更が落ち着いた時点で再走査してよろしいですか？"
    if top.code == "scan_consistency_unavailable":
        return "走査終了時のGit状態を再確認できないため、今回の状態は確定しません。Git状態を読み取れる環境で再走査してよろしいですか？"
    if top.code == "git_state_unavailable":
        return "Git状態を確認できませんでした。safe.directory や権限設定の影響かもしれません。読み取れる状態で再確認してよろしいですか？"
    if top.code == "not_git_repo":
        return "Git リポジトリではありません。まず `--path` に対象リポジトリを指定して再確認してよろしいですか？"
    if top.code == "missing_project_status":
        status_file = top.title.removesuffix(" がありません")
        return f"{status_file} が見つかりません。まず現在の状態だけを書いた最小ファイル案を出してよろしいですか？"
    if top.code == "status_file_outside_project":
        return "状態ファイルがプロジェクト外を指しているため読みませんでした。project内の正本へ設定を向け直してよろしいですか？"
    if top.code == "status_file_unreadable":
        return "状態ファイルを読めませんでした。対象を書き換えず、ファイル種別と読み取り権限を確認してよろしいですか？"
    if top.code == "status_file_disallowed":
        return "設定された状態ファイルは安全な読み取り対象ではないため読みませんでした。project内の通常のテキスト状態ファイルへ設定を向け直してよろしいですか？"
    if top.code == "missing_readme":
        return "README が見つかりません。まず最小の入口ファイルを作る案を出してよろしいですか？"
    if top.code == "ambiguous_status_fields":
        return "状態ファイルに同じ状態項目が複数あります。値を選ばず、現行メタデータと例・過去記録を分ける案を作ってよろしいですか？"
    if top.code == "missing_required_files":
        return "設定された必須ファイルが見つかりません。設定と既存pathのどちらが現在正しいか確認してよろしいですか？"
    if top.code == "missing_source_of_truth":
        return "設定された正本pathを確認できません。新設せず、まず既存の正しい正本を確認してよろしいですか？"
    if top.code == "config_unavailable":
        return "設定ファイルを安全に使えないため、内容走査を止めました。値を推測せず、ファイル形式または読み取り可能性を確認してよろしいですか？"
    if top.code == "untracked_files":
        return "まだGit管理に入っていないファイルがあります。次は、Gitに入れる候補をこちらで整理してよろしいですか？"
    if top.code == "uncommitted_changes":
        return "未コミットの変更があります。後で迷わないように、変更内容を短く整理してよろしいですか？"
    if top.code == "next_review_overdue":
        return "状態ファイルの next_review を過ぎています。現在地を確認し、次回確認日を決め直してよろしいですか？"
    if top.code == "active_stale":
        return "active ですが、Gitで確認できる活動が一定期間ありません。実際の継続状況を確認し、継続・休止・保留の宣言を整えてよろしいですか？"
    if top.code == "status_document_stale":
        return "Git活動はありますが、状態文書の確認が追いついていない可能性があります。現在の状態宣言を確認してよろしいですか？"
    if top.code == "paused_activity":
        return "paused の確認後にもGit活動があります。再開済みか、意図した保守作業かを確認してよろしいですか？"
    if top.code == "missing_status":
        return "状態ファイルにstatusがありません。現在の作業状態を確認してよろしいですか？"
    if top.code == "unrecognized_status":
        return "statusが既知の互換値ではないため、状態別のstale判定を適用していません。状態ファイルの値を担当者と確認してよろしいですか？"
    if top.code == "invalid_status_dates":
        return "状態ファイルに日付として解釈できない項目があります。値を自動修正せず、正しい日付を確認してよろしいですか？"
    if top.code == "missing_review_fields":
        return "確認日か次回確認日が足りません。まず PROJECT_STATUS に確認日だけ足す案を出してよろしいですか？"
    if top.code == "status_document_over_budget":
        return "状態文書単体が従来の確認目安を超えています。毎回読む範囲を明示して合計を再確認してよろしいですか？"
    if top.code in {"fixed_input_review_needed", "fixed_input_high_cost"}:
        return "毎回読む情報が目安を超えています。必要な情報を削らず、履歴との分離か理由付き例外を確認してよろしいですか？"
    if top.code in {"fixed_input_scope_unconfirmed", "fixed_input_measurement_unavailable"}:
        return "毎回読む範囲を確認できません。自動適用される指示と開始時に必ず読む文書だけを確認してよろしいですか？"
    if top.code == "keyword_scan_unavailable":
        return "足場キーワードの走査範囲を確認できませんでした。対象を書き換えず、Gitのファイル一覧を確認できる環境で再走査してよろしいですか？"
    if top.code == "footwork_keywords":
        return "足場キーワードが見つかりました。まず後回しになりそうな1件だけ確認する案を出してよろしいですか？"
    if top.code == "source_of_truth_not_linked":
        return "READMEから設定された正本への導線を確認できません。既存の正本へ短いリンクを置く案を作ってよろしいですか？"
    return f"{top.title}。まず {top.suggestion} この方向で進めてよろしいですか？"


UNKNOWN_CONTINUITY_CODES = {
    "scan_changed_during_observation",
    "scan_consistency_unavailable",
    "git_state_unavailable",
    "config_unavailable",
    "status_file_outside_project",
    "missing_project_status",
    "status_file_disallowed",
    "status_file_unreadable",
    "missing_status",
    "unrecognized_status",
}


def _make_git_state_unavailable_risk(git: GitInfo) -> Risk:
    return Risk(
        priority=1,
        code="git_state_unavailable",
        severity="critical",
        subject="Git状態",
        title="Git状態を確認できませんでした",
        evidence=git.error or "git status の確認に失敗しました。",
        interpretation="Gitに基づく変更、未追跡、活動鮮度の観測範囲が未確認です。",
        suggestion="safe.directory、権限、応答停止の影響を確認し、対象を書き換えず読み取り可能な環境で再確認するのがよさそうです。",
    )


def _make_config_unavailable_risk() -> Risk:
    return Risk(
        priority=1,
        code="config_unavailable",
        severity="high",
        subject=".project-agent.yml",
        title="設定ファイルを安全に使えません",
        evidence=(
            ".project-agent.yml は存在しますが、"
            "読み取りまたは解釈を完了できませんでした。"
        ),
        interpretation=(
            "意図された状態ファイル、正本、除外範囲を確認できないため、"
            "設定に依存する観測とキーワード内容走査は未確認です。"
        ),
        suggestion=(
            "設定値を推測せず、ファイル形式または読み取り可能性を"
            "確認するのがよさそうです。"
        ),
    )


def _collect_observation_paths(
    root: Path,
    config_result: ConfigResult,
) -> tuple[ObservedPath, ...] | None:
    root = root.resolve()
    config_path = _lexical_project_path(root, ".project-agent.yml")
    paths: dict[Path, bool] = {
        config_path: (
            config_result.load_state == "loaded"
            and _can_observe_content(root, config_path)
        ),
        _lexical_project_path(root, "README.md"): False,
    }
    readme_path = _lexical_project_path(root, "README.md")
    paths[readme_path] = _can_observe_content(root, readme_path)
    configured_paths = [
        config_result.config.status_file,
        *config_result.config.required_files,
        *config_result.config.source_of_truth,
        *config_result.config.automatic_instruction_files,
        *config_result.config.always_read_files,
    ]
    for configured_path in configured_paths:
        candidate = _lexical_project_path(root, configured_path)
        if candidate.is_relative_to(root):
            paths.setdefault(candidate, False)

    status_path = _lexical_project_path(
        root,
        config_result.config.status_file,
    )
    if config_result.exists and status_path.is_relative_to(root):
        relative = status_path.relative_to(root)
        if (
            not _is_sensitive_path(relative)
            and _is_allowed_text_file(status_path)
        ):
            paths[status_path] = _can_observe_content(root, status_path)

    for fixed_path in (
        *config_result.config.automatic_instruction_files,
        *config_result.config.always_read_files,
    ):
        candidate = _lexical_project_path(root, fixed_path)
        if candidate.is_relative_to(root):
            paths[candidate] = _can_observe_content(root, candidate)

    if config_result.load_state != "unavailable":
        try:
            for candidate in _iter_candidate_files(
                root,
                config_result.config.exclude_paths,
            ):
                paths[candidate] = _can_observe_content(root, candidate)
        except GitCommandUnavailable:
            return None
    return tuple(
        sorted(paths.items(), key=lambda item: item[0].as_posix())
    )


def _capture_observation_path_state(
    root: Path,
    paths: tuple[ObservedPath, ...] | None,
) -> tuple[ObservedPathState, ...] | None:
    if paths is None:
        return None
    root = root.resolve()
    states: list[ObservedPathState] = []
    try:
        for path, observe_content in paths:
            if not path.is_relative_to(root):
                continue
            relative = path.relative_to(root).as_posix()
            resolved = path.resolve()
            link_like = path.is_symlink() or resolved != path
            if link_like:
                stat = path.lstat()
                kind = "symlink"
                content_digest = ""
            elif not resolved.is_relative_to(root):
                continue
            elif not path.exists():
                states.append((relative, "missing", 0, 0, ""))
                continue
            elif path.is_dir():
                stat = path.stat()
                kind = "directory"
                content_digest = ""
            else:
                stat = path.stat()
                kind = "file"
                content_digest = (
                    sha256(path.read_bytes()).hexdigest()
                    if observe_content
                    else ""
                )
            states.append(
                (
                    relative,
                    kind,
                    stat.st_size,
                    stat.st_mtime_ns,
                    content_digest,
                )
            )
    except OSError:
        return None
    return tuple(states)


def _lexical_project_path(root: Path, configured_path: str) -> Path:
    configured = Path(configured_path)
    candidate = configured if configured.is_absolute() else root / configured
    return Path(abspath(candidate))


def _can_observe_content(root: Path, path: Path) -> bool:
    if not path.is_relative_to(root):
        return False
    relative = path.relative_to(root)
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or _is_sensitive_path(relative)
            or not _is_allowed_text_file(path)
        ):
            return False
        return path.stat().st_size <= MAX_TEXT_FILE_BYTES
    except OSError:
        return False


def _check_observation_consistency(
    start: GitInfo,
    end: GitInfo | None,
    start_config: ConfigResult,
    end_config: ConfigResult | None,
    start_paths: tuple[ObservedPathState, ...] | None,
    end_paths: tuple[ObservedPathState, ...] | None,
) -> Literal["stable", "changed", "unavailable", "not_applicable"]:
    if start.error_kind == "unavailable":
        return "unavailable"
    if not start.is_repo:
        return "not_applicable"
    if (
        end is None
        or end.error_kind == "unavailable"
        or end_config is None
        or start_paths is None
        or end_paths is None
    ):
        return "unavailable"
    if not end.is_repo or start.root.resolve() != end.root.resolve():
        return "changed"

    start_identity = (
        start.head_commit,
        start.branch,
        tuple(start.status_lines),
        tuple(start.current_paths),
    )
    end_identity = (
        end.head_commit,
        end.branch,
        tuple(end.status_lines),
        tuple(end.current_paths),
    )
    stable = (
        start_identity == end_identity
        and start_config == end_config
        and start_paths == end_paths
    )
    return "stable" if stable else "changed"


def make_overall_judgment(risks: list[Risk]) -> OverallJudgment:
    unknown_risk = next(
        (risk for risk in risks if risk.code in UNKNOWN_CONTINUITY_CODES),
        None,
    )
    if unknown_risk:
        return OverallJudgment(
            continuity="unknown",
            reason=(
                "必要な観測が未確認のため、継続性を確定できません"
                f"（{unknown_risk.title}）。"
            ),
        )

    at_risk = next(
        (
            risk
            for risk in risks
            if risk.severity in {"critical", "high", "medium"}
        ),
        None,
    )
    if at_risk:
        return OverallJudgment(
            continuity="at_risk",
            reason=(
                "対応候補が残っているため、継続性に注意が必要です"
                f"（{at_risk.title}）。"
            ),
        )

    if risks:
        return OverallJudgment(
            continuity="ready",
            reason=(
                "確認できた範囲では、低優先の確認候補はありますが、"
                "大きな足場リスクは見つかっていません。"
            ),
        )

    return OverallJudgment(
        continuity="ready",
        reason="確認できた範囲では、大きな足場リスクは見つかっていません。",
    )


def _make_state_activity_risks(
    run_at: datetime,
    git: GitInfo,
    project_status: ProjectStatus,
    config_result: ConfigResult,
) -> list[Risk]:
    status_value = normalize_status(project_status.status)
    if not status_value:
        return []

    commit_date = parse_date(git.last_commit_at)
    observed_dates = [
        value
        for value in (
            parse_date(project_status.last_updated),
            parse_date(project_status.last_reviewed),
        )
        if value
    ]
    state_observed_date = max(observed_dates) if observed_dates else None

    if status_value == "active":
        threshold_days = config_result.config.stale_days.get("active")
        if threshold_days and commit_date and not git.status_lines:
            activity_elapsed = (run_at.date() - commit_date).days
            if activity_elapsed >= threshold_days:
                return [
                    Risk(
                        priority=6,
                        code="active_stale",
                        severity="medium",
                        subject="Git活動",
                        title="active ですがGit活動が一定期間確認できません",
                        evidence=f"working treeに変更はなく、Gitで確認できた直近コミット日は {commit_date.isoformat()} で、{activity_elapsed} 日経過しています。状態文書の確認日とは別に評価しています。",
                        interpretation="状態宣言はactiveですが、Gitで確認できる活動が設定期間ありません。実際の継続状況は未確認です。",
                        suggestion="実際の活動を確認し、継続・休止・保留のどれとして扱うかを短く残すのがよさそうです。",
                    )
                ]

        if threshold_days and commit_date and state_observed_date:
            state_elapsed = (run_at.date() - state_observed_date).days
            if commit_date > state_observed_date and state_elapsed >= threshold_days:
                return [
                    Risk(
                        priority=6,
                        code="status_document_stale",
                        severity="medium",
                        subject="状態文書",
                        title="Git活動に状態文書の確認が追いついていない可能性があります",
                        evidence=f"状態文書で確認できた最新日は {state_observed_date.isoformat()}、Gitの直近コミット日は {commit_date.isoformat()} です。",
                        interpretation="Git活動後の現在状態が状態文書へ反映されていない可能性があります。",
                        suggestion="活動内容と現在の状態宣言を照合し、必要な場合だけ状態文書を更新するのがよさそうです。",
                    )
                ]
        return []

    if (
        status_value == "paused"
        and commit_date
        and state_observed_date
        and commit_date > state_observed_date
    ):
        return [
            Risk(
                priority=6,
                code="paused_activity",
                severity="medium",
                subject="Git活動",
                title="paused の確認後にGit活動があります",
                evidence=f"状態文書で確認できた最新日は {state_observed_date.isoformat()}、Gitの直近コミット日は {commit_date.isoformat()} です。",
                interpretation="再開済みか、paused中の意図した作業かを観測事実だけでは判断できません。",
                suggestion="再開済みか、paused中に意図した保守作業かを確認し、必要な場合だけ状態宣言を整えるのがよさそうです。",
            )
        ]

    threshold_days = config_result.config.stale_days.get(status_value)
    if not threshold_days or not state_observed_date:
        return []

    state_elapsed = (run_at.date() - state_observed_date).days
    if state_elapsed < threshold_days:
        return []

    return [
        Risk(
            priority=6,
            code=f"{status_value}_stale",
            severity="medium",
            subject="状態文書",
            title=f"{status_value} の状態確認から一定期間経過しています",
            evidence=f"状態文書で確認できた最新日は {state_observed_date.isoformat()} で、{state_elapsed} 日経過しています。Git活動とは別に評価しています。",
            interpretation=f"{status_value} の状態が現在も有効か再確認する時期です。",
            suggestion="状態と再開条件を確認し、必要な場合だけ確認日または次回確認日を整えるのがよさそうです。",
        )
    ]


def _make_next_review_risk(
    run_at: datetime,
    project_status: ProjectStatus,
) -> Risk | None:
    next_review_date = parse_date(project_status.next_review)
    if not next_review_date or run_at.date() <= next_review_date:
        return None

    elapsed = (run_at.date() - next_review_date).days
    return Risk(
        priority=4,
        code="next_review_overdue",
        severity="high",
        subject="状態文書",
        title="next_review を過ぎています",
        evidence=f"次回確認日は {next_review_date.isoformat()} で、{elapsed} 日経過しています。",
        interpretation="予定していた再確認がまだ記録されていない可能性があります。",
        suggestion="現在地を確認し、次回確認日または再確認条件を短く残すのがよさそうです。",
    )


def _file_presence_within_project(root: Path, name: str) -> FilePresence:
    root = root.resolve()
    configured = Path(name)
    candidate = (
        configured.resolve()
        if configured.is_absolute()
        else (root / configured).resolve()
    )
    exists = candidate.is_relative_to(root) and candidate.is_file()
    return FilePresence(path=name, exists=exists)


def inspect_source_of_truth(
    root: Path,
    configured_paths: list[str],
    status_file: str,
) -> dict[str, SourceOfTruthPresence]:
    root = root.resolve()
    readme_path = (root / "README.md").resolve()
    status_path = _resolve_project_path(root, status_file)
    readme_text = _read_readme_for_links(root, readme_path)
    sources: dict[str, SourceOfTruthPresence] = {}

    for configured_path in configured_paths:
        candidate = _resolve_project_path(root, configured_path)
        within_project = candidate.is_relative_to(root)
        exists = within_project and (candidate.is_file() or candidate.is_dir())
        is_readme = candidate == readme_path
        is_status_file = candidate == status_path
        readme_linked: bool | None = None
        if is_readme:
            readme_linked = True
        elif exists and readme_text is not None:
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_dir():
                relative = f"{relative.rstrip('/')}/"
            readme_linked = _readme_mentions_path(readme_text, relative)

        sources[configured_path] = SourceOfTruthPresence(
            path=configured_path,
            exists=exists,
            readme_linked=readme_linked,
            is_readme=is_readme,
            is_status_file=is_status_file,
        )

    return sources


def _iter_candidate_files(root: Path, exclude_paths: list[str]):
    root = root.resolve()
    candidates = list_git_scan_files(root)

    for path in candidates:
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            relative_path = path.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_relative_to(root):
            continue
        if any(part in SKIP_DIRS for part in relative_path.parts):
            continue
        if _is_footwork_review(relative_path):
            continue
        relative = relative_path.as_posix()
        if _matches_exclude(relative, exclude_paths):
            continue
        if _is_sensitive_path(relative_path):
            continue
        if not _is_allowed_text_file(path):
            continue
        yield path


def _matches_exclude(relative: str, patterns: list[str]) -> bool:
    for raw_pattern in patterns:
        pattern = _normalize_relative_path(raw_pattern)
        if pattern and fnmatchcase(relative, pattern):
            return True
        if pattern.endswith("/"):
            directory_pattern = pattern.rstrip("/")
            relative_parts = relative.rstrip("/").split("/")
            directory_limit = (
                len(relative_parts) + 1
                if relative.endswith("/")
                else len(relative_parts)
            )
            directories = (
                "/".join(relative_parts[:index])
                for index in range(1, directory_limit)
            )
            if directory_pattern and any(
                fnmatchcase(directory, directory_pattern)
                for directory in directories
            ):
                return True
        if pattern.endswith("/**"):
            directory = pattern[:-3].rstrip("/")
            normalized_relative = relative.rstrip("/")
            if normalized_relative == directory or normalized_relative.startswith(
                f"{directory}/"
            ):
                return True
    return False


def partition_untracked_files(
    untracked_files: list[str],
    exclude_paths: list[str],
) -> tuple[list[str], list[str]]:
    actionable: list[str] = []
    background: list[str] = []
    for status_line in untracked_files:
        relative = _status_line_path(status_line)
        if relative and _matches_exclude(relative, exclude_paths):
            background.append(status_line)
        else:
            actionable.append(status_line)
    return actionable, background


def _status_line_path(status_line: str) -> str:
    if len(status_line) < 4:
        return ""
    relative = status_line[3:]
    if " -> " in relative:
        relative = relative.split(" -> ", 1)[1]
    return _normalize_relative_path(relative)


def _normalize_relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _mark_current_keyword_matches(
    matches: list[KeywordMatch],
    current_paths: list[str],
) -> list[KeywordMatch]:
    normalized_current_paths = {
        _normalize_relative_path(path) for path in current_paths
    }
    classified = [
        KeywordMatch(
            path=match.path,
            line_number=match.line_number,
            keyword=match.keyword,
            is_current=match.path in normalized_current_paths,
        )
        for match in matches
    ]
    return sorted(
        classified,
        key=lambda match: (not match.is_current, match.path),
    )


def _relative_status_path(root: Path, project_status: ProjectStatus) -> str:
    try:
        return project_status.path.relative_to(root).as_posix()
    except ValueError:
        return ""


def _resolve_project_path(root: Path, configured_path: str) -> Path:
    candidate = Path(configured_path)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )


def _read_readme_for_links(root: Path, readme_path: Path) -> str | None:
    if (
        not readme_path.is_relative_to(root)
        or readme_path.is_symlink()
        or not readme_path.is_file()
        or not _is_allowed_text_file(readme_path)
    ):
        return None
    try:
        return readme_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _readme_mentions_path(readme_text: str, relative_path: str) -> bool:
    normalized_text = readme_text.replace("\\", "/").lower()
    normalized_path = _normalize_relative_path(relative_path).lower()
    if not normalized_path:
        return False
    return normalized_path in normalized_text


def _path_list_evidence(paths: list[str], limit: int = 4) -> str:
    shown = ", ".join(f"`{path}`" for path in paths[:limit])
    if len(paths) > limit:
        shown = f"{shown}, ほか {len(paths) - limit} 件"
    return f"確認できない対象: {shown}"


def _is_footwork_review(path: Path) -> bool:
    name = path.name.lower()
    return name == "footwork_review.md" or (
        name.startswith("footwork_review_") and path.suffix.lower() == ".md"
    )


def _line_contains_keyword(
    line: str,
    keyword: str,
    lowered_keyword: str,
) -> bool:
    if len(keyword) != 1:
        return lowered_keyword in line.lower()

    trailing_boundary = r"(?=$|[\s\]\)）「」』】>＞:：、。,.!?！？])"
    return re.search(
        re.escape(keyword) + trailing_boundary,
        line,
        flags=re.IGNORECASE,
    ) is not None
