from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .scan import (
    KeywordMatch,
    Risk,
    ScanResult,
    partition_untracked_files,
)
from .status import is_recognized_status, normalize_status, parse_date


def build_markdown_report(result: ScanResult, saved_path: Path | None = None) -> str:
    observation_unstable = result.observation_consistency in {
        "changed",
        "unavailable",
    }
    display_git = (
        replace(
            result.git,
            is_repo=False,
            status_lines=[],
            last_commit_at=None,
            head_commit=None,
            branch=None,
            current_paths=[],
            error="走査中の一貫性を確認できません。",
            error_kind="unavailable",
        )
        if observation_unstable
        else result.git
    )
    status_lines = display_git.status_lines
    status_preview = _preview(status_lines)
    git_unavailable = (
        display_git.error_kind == "unavailable"
    )
    config_unavailable = (
        result.config_result.load_state == "unavailable"
    )
    git_not_applicable = not display_git.is_repo and not git_unavailable
    keyword_unavailable = git_unavailable or any(
        risk.code in {"config_unavailable", "keyword_scan_unavailable"}
        for risk in result.risks
    )
    keyword_preview = (
        [] if observation_unstable else _keyword_preview(result.keyword_matches)
    )
    if git_unavailable:
        working_tree_preview = (
            "Git状態が未確認のため、working treeの変更は確認できません。"
        )
    elif git_not_applicable:
        working_tree_preview = (
            "Gitリポジトリではないため、working treeは対象外です。"
        )
    elif config_unavailable:
        working_tree_preview = (
            "設定ファイルを使用できないため、"
            "working treeのpath表示は省略しました。"
        )
    else:
        working_tree_preview = (
            status_preview
            or "working tree に表示対象の変更はありません。"
        )
    actionable_untracked, background_untracked = partition_untracked_files(
        result.untracked_files,
        result.config_result.config.exclude_paths,
    )
    actionable_untracked_text = (
        "未確認"
        if config_unavailable
        and display_git.is_repo
        and not git_unavailable
        else _git_count_text(display_git, len(actionable_untracked))
    )
    background_untracked_text = (
        "未確認"
        if config_unavailable
        and display_git.is_repo
        and not git_unavailable
        else _git_count_text(display_git, len(background_untracked))
    )
    current_keyword_count = sum(
        match.is_current for match in result.keyword_matches
    )
    background_keyword_count = (
        len(result.keyword_matches) - current_keyword_count
    )
    keyword_count_text = _observed_count_text(
        keyword_unavailable or git_not_applicable,
        len(result.keyword_matches),
        unit="ファイル",
        zero_as_none=False,
        unavailable_text=(
            "対象外" if git_not_applicable else "未確認"
        ),
    )
    current_keyword_count_text = _observed_count_text(
        keyword_unavailable or git_not_applicable,
        current_keyword_count,
        unit="ファイル",
        zero_as_none=False,
        unavailable_text=(
            "対象外" if git_not_applicable else "未確認"
        ),
    )
    background_keyword_count_text = _observed_count_text(
        keyword_unavailable or git_not_applicable,
        background_keyword_count,
        unit="ファイル",
        zero_as_none=False,
        unavailable_text=(
            "対象外" if git_not_applicable else "未確認"
        ),
    )
    risks = result.risks
    priority_risks = _select_priority_risks(
        risks,
        result.config_result.config.max_priority_actions,
    )
    saved_text = (
        "明示保存済み（pathは走査中の一貫性を確認できないため非表示）"
        if saved_path and observation_unstable
        else f"`{saved_path}`"
        if saved_path
        else "標準出力のみ"
    )

    lines = [
        "# 足場レビュー",
        "",
        "## 全体判断",
        "",
        f"- continuity: `{result.overall_judgment.continuity}`",
        f"- 理由: {result.overall_judgment.reason}",
        "",
        "## 観測スナップショット",
        "",
        (
            "- プロジェクトパス: 未確認（走査中の一貫性を確認できないため）"
            if observation_unstable
            else f"- プロジェクトパス: `{result.project_path}`"
        ),
        f"- 実行日時: {result.run_at.isoformat(timespec='seconds')}",
        f"- 保存先: {saved_text}",
        f"- 観測の一貫性: {_observation_consistency_text(result)}",
        "",
        "## Git状態の要約",
        "",
        f"- Gitリポジトリ: {_git_repo_text(display_git)}",
        f"- Git状態: {_git_state_text(display_git)}",
        f"- リポジトリルート: {_git_root_text(display_git)}",
        f"- HEAD commit: {_git_value_text(display_git, display_git.head_commit)}",
        f"- branch: {_git_value_text(display_git, display_git.branch)}",
        f"- working tree: {_working_tree_text(display_git)}",
        f"- 未コミット変更: {_git_count_text(display_git, len(result.changed_files))}",
        f"- 未追跡ファイル: {_git_count_text(display_git, len(result.untracked_files))}",
        f"- 要確認の未追跡: {actionable_untracked_text}",
        f"- 設定上の背景にある未追跡: {background_untracked_text}",
        f"- 直近コミット日時: {_git_date_text(display_git)}",
        "",
        "```text",
        working_tree_preview,
        "```",
        "",
        "## 管理ファイルの有無",
        "",
    ]

    if observation_unstable:
        lines.append("- 未確認（走査中の一貫性を確認できないため）")
    else:
        for name in sorted(result.files):
            presence = result.files[name]
            presence_text = "あり" if presence.exists else "なし"
            lines.append(f"- `{name}`: {presence_text}")

    lines.extend(["", "## 正本導線", ""])
    if observation_unstable:
        lines.append("- 未確認（走査中の一貫性を確認できないため）")
    elif config_unavailable:
        lines.append("- 未確認（設定ファイルを安全に使えないため）")
    elif result.source_of_truth:
        for source in result.source_of_truth.values():
            lines.append(
                f"- `{source.path}`: "
                f"{'あり' if source.exists else 'なし'} / "
                f"README導線: {_source_link_text(source)}"
            )
    else:
        lines.append("- 設定なし")

    lines.extend(
        [
            "",
            "## 状態ファイルの読み取り結果",
            "",
            (
                "- 状態ファイル: 未確認（走査中の一貫性を確認できないため）"
                if observation_unstable
                else "- 状態ファイル: 未確認（設定ファイルを安全に使えないため）"
                if config_unavailable
                else "- 状態ファイル: 未確認（設定がないため）"
                if result.config_result.load_state == "missing"
                else f"- 状態ファイル: `{result.project_status.path}`"
            ),
            f"- status: {_observed_status_text(result, result.project_status.status)}",
            f"- status継続期間: {_observed_status_duration_text(result)}",
            f"- Last updated: {_observed_status_date_text(result, result.project_status.last_updated)}",
            f"- last_reviewed: {_observed_status_date_text(result, result.project_status.last_reviewed)}",
            f"- next_review: {_observed_status_date_text(result, result.project_status.next_review)}",
            f"- 状態文書量: {_status_document_size_text(result)}",
        ]
    )

    warnings = (
        []
        if observation_unstable
        else result.project_status.warnings + result.config_result.warnings
    )
    if warnings:
        lines.append("- 警告:")
        lines.extend(f"  - {warning}" for warning in warnings)

    lines.extend(_fixed_input_lines(result))

    lines.extend(
        [
            "",
            "## 足場キーワード検知",
            "",
            f"- 候補ファイル数: {keyword_count_text}",
            f"- 今回変更された候補: {current_keyword_count_text}",
            f"- 既存不変の候補: {background_keyword_count_text}",
        ]
    )
    if keyword_preview:
        lines.append("")
        lines.append("代表例:")
        lines.extend(keyword_preview)

    lines.extend(["", "## 検知した足場リスク", ""])
    if risks:
        for risk in risks:
            lines.extend(_risk_lines(risk))
    else:
        lines.append("- 大きな足場リスクは見つかりませんでした。")

    lines.extend(["", "## 優先対応", ""])
    if priority_risks:
        for index, risk in enumerate(priority_risks, start=1):
            lines.append(f"{index}. {risk.title}: {risk.suggestion}")
    else:
        lines.append("1. 追加対応なし。")

    lines.extend(
        [
            "",
            "## ご確認いただきたいこと",
            "",
            priority_risks[0].title if priority_risks else "追加確認なし",
            "",
            "## Stewardからのご提案",
            "",
            result.consultation,
            "",
        ]
    )

    return "\n".join(lines)


def _risk_lines(risk: Risk) -> list[str]:
    return [
        f"- {risk.title}",
        f"  - code: `{risk.code}`",
        f"  - severity: `{risk.severity}`",
        f"  - 対象: {risk.subject}",
        f"  - Evidence: {risk.evidence}",
        f"  - 解釈: {risk.interpretation}",
        f"  - 提案: {risk.suggestion}",
        f"  - 状態: {risk.status}",
    ]


def _select_priority_risks(risks: list[Risk], limit: int) -> list[Risk]:
    critical = [risk for risk in risks if risk.severity == "critical"]
    regular = [risk for risk in risks if risk.severity != "critical"][:limit]
    return [*critical, *regular]


def _preview(lines: list[str], limit: int = 12) -> str:
    if not lines:
        return ""
    shown = lines[:limit]
    suffix = [] if len(lines) <= limit else [f"...ほか {len(lines) - limit} 件"]
    return "\n".join([*shown, *suffix])


def _keyword_preview(matches: list[KeywordMatch], limit: int = 5) -> list[str]:
    preview = []
    for match in matches[:limit]:
        current_label = "（今回変更）" if match.is_current else ""
        preview.append(
            f"- `{match.path}:{match.line_number}`: `{match.keyword}`{current_label}"
        )
    if len(matches) > limit:
        preview.append(f"- ...ほか {len(matches) - limit} ファイル")
    return preview


def _yes_no(value: bool) -> str:
    return "はい" if value else "いいえ"


def _git_repo_text(git) -> str:
    if git.error_kind == "unavailable" and not git.is_repo:
        return "確認不可"
    return _yes_no(git.is_repo)


def _git_state_text(git) -> str:
    if git.error_kind == "unavailable":
        return "確認できませんでした"
    if not git.is_repo:
        return "対象外"
    return "確認済み"


def _git_root_text(git) -> str:
    if git.error_kind == "unavailable" and not git.is_repo:
        return "未確認"
    if not git.is_repo:
        return "対象外"
    return f"`{git.root}`"


def _count_text(count: int, unit: str = "件") -> str:
    return "なし" if count == 0 else f"{count} {unit}"


def _git_count_text(
    git,
    count: int,
    unit: str = "件",
    *,
    zero_as_none: bool = True,
) -> str:
    unavailable = git.error_kind == "unavailable"
    return _observed_count_text(
        unavailable or not git.is_repo,
        count,
        unit=unit,
        zero_as_none=zero_as_none,
        unavailable_text="未確認" if unavailable else "対象外",
    )


def _observed_count_text(
    unavailable: bool,
    count: int,
    *,
    unit: str,
    zero_as_none: bool,
    unavailable_text: str = "未確認",
) -> str:
    if unavailable:
        return unavailable_text
    if zero_as_none:
        return _count_text(count, unit)
    return f"{count} {unit}"


def _git_value_text(git, value: str | None) -> str:
    if git.error_kind == "unavailable":
        return "未確認"
    if not git.is_repo:
        return "対象外"
    return f"`{value}`" if value else "未確認"


def _git_date_text(git) -> str:
    if git.error_kind == "unavailable":
        return "未確認"
    if not git.is_repo:
        return "対象外"
    return git.last_commit_at or "未確認"


def _status_date_text(value: str | None) -> str:
    if not value:
        return "未確認"
    if parse_date(value) is None:
        return "不正な日付（値は非表示）"
    return value


def _status_text(value: str | None) -> str:
    if not value:
        return "未確認"
    if not is_recognized_status(value):
        return "未認識（値は状態ファイルで確認）"
    return normalize_status(value) or "未確認"


def _observation_consistency_text(result: ScanResult) -> str:
    labels = {
        "stable": "確認済み（走査開始時と終了時のGit状態が一致）",
        "changed": "要再確認（走査中に観測対象が変化）",
        "unavailable": "未確認（走査開始時と終了時の一貫性を確認できず）",
        "not_applicable": "対象外（Gitリポジトリではない）",
    }
    return labels[result.observation_consistency]


def _observed_status_text(result: ScanResult, value: str | None) -> str:
    if result.observation_consistency in {"changed", "unavailable"}:
        return "未確認（走査中の一貫性を確認できないため）"
    return _status_text(value)


def _observed_status_date_text(result: ScanResult, value: str | None) -> str:
    if result.observation_consistency in {"changed", "unavailable"}:
        return "未確認（走査中の一貫性を確認できないため）"
    return _status_date_text(value)


def _status_document_size_text(result: ScanResult) -> str:
    if (
        result.observation_consistency in {"changed", "unavailable"}
        or result.config_result.load_state == "unavailable"
        or result.project_status.read_state != "loaded"
        or result.project_status.character_count is None
        or result.project_status.line_count is None
    ):
        return "未確認"
    return (
        f"{result.project_status.character_count} 文字 / "
        f"{result.project_status.line_count} 行"
    )


def _fixed_input_lines(result: ScanResult) -> list[str]:
    observation = result.fixed_input
    lines = ["", "## 毎回読む情報", ""]
    if result.observation_consistency in {"changed", "unavailable"}:
        lines.append("- 確認範囲: 未確認（走査中の一貫性を確認できないため）")
        return lines

    scope_labels = {
        "declared": "設定で確認済み",
        "legacy": "従来設定の状態文書単体だけ（合計範囲は未確認）",
        "unconfirmed": "未確認（設定がないため）",
        "unavailable": "未確認（設定ファイルを安全に使えないため）",
    }
    lines.append(f"- 確認範囲: {scope_labels[observation.scope_state]}")

    if observation.scope_state == "declared":
        automatic = [
            item
            for item in observation.files
            if item.category == "automatic_instruction"
        ]
        always = [
            item for item in observation.files if item.category == "always_read"
        ]
        lines.append(
            "- 自動適用されるプロジェクト指示: "
            + _fixed_file_group_text(automatic)
        )
        lines.append(
            "- 開始時に必ず読む文書: "
            + _fixed_file_group_text(always)
        )
    elif observation.scope_state == "legacy":
        lines.append(
            "- 従来の測定対象: "
            + _fixed_file_group_text(list(observation.files))
        )

    if observation.measurement_state == "complete":
        token_text = (
            f"{observation.token_count} token（{observation.token_encoding}）"
            if observation.token_count is not None
            else "未確認（利用可能な代表tokenizerなし。文字数から換算しません）"
        )
        lines.append(
            f"- 合計: {observation.character_count or 0} 文字 / "
            f"{observation.line_count or 0} 行 / token数: {token_text}"
        )
    elif observation.measurement_state == "partial":
        lines.append(
            f"- 合計: 未確認（安全に読めた分は {observation.character_count or 0} 文字 / "
            f"{observation.line_count or 0} 行）"
        )
    else:
        lines.append("- 合計: 未確認")

    lines.append(
        f"- 目安: 通常目標 {observation.target_chars} 文字 / "
        f"{observation.target_lines} 行、改善優先 {observation.high_cost_chars} 文字 / "
        f"{observation.high_cost_lines} 行"
    )
    exception_text = (
        "理由と再確認条件あり"
        if observation.exception_reason and observation.exception_review_condition
        else "不完全（理由と再確認条件の両方が必要）"
        if observation.exception_reason or observation.exception_review_condition
        else "なし"
    )
    lines.append(f"- 理由付き例外: {exception_text}")
    lines.append(
        f"- 必要な時だけ読む資料: 設定 {len(observation.read_when_needed_files)} 件（合計から除外）"
    )
    lines.append(
        f"- 履歴・索引・参考資料: 設定 {len(observation.reference_files)} 件（合計から除外）"
    )
    lines.append(
        "- システム、全プロジェクト共通指示、Skill、ツール定義: "
        "プロジェクト側で直接減らせないため、この合計の対象外"
    )
    return lines


def _fixed_file_group_text(items) -> str:
    loaded = [f"`{item.path}`" for item in items if item.read_state == "loaded"]
    failed_count = sum(item.read_state != "loaded" for item in items)
    parts = loaded
    if failed_count:
        parts.append(f"安全に確認できない設定 {failed_count} 件")
    return "、".join(parts) if parts else "なし"


def _observed_status_duration_text(result: ScanResult) -> str:
    if result.observation_consistency in {"changed", "unavailable"}:
        return "未確認（走査中の一貫性を確認できないため）"
    return _status_duration_text(result)


def _status_duration_text(result: ScanResult) -> str:
    observation = result.status_line_observation
    if observation.state == "not_applicable":
        return "対象外（Git履歴なし）"
    if observation.state == "uncommitted":
        return "未確認（status行が未コミット）"
    if observation.state == "not_in_history":
        return "未確認（status行のGit履歴なし）"
    if observation.state in {"unavailable", "not_observable"}:
        return "未確認"

    observed_at = _parse_observed_at(observation.commit_at)
    run_at = result.run_at
    if not observed_at or not run_at.tzinfo:
        return "未確認"
    if observed_at > run_at:
        return "未確認（Git日時が実行日時より未来）"
    elapsed = int((run_at - observed_at).total_seconds() // 86_400)
    return (
        f"{elapsed}日以上（{observed_at.isoformat(timespec='seconds')}以降、"
        "現在のstatus行をGit履歴で確認）"
    )


def _parse_observed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _working_tree_text(git) -> str:
    if git.error_kind == "unavailable":
        return "未確認"
    if not git.is_repo:
        return "対象外"
    return "dirty" if git.status_lines else "clean"


def _source_link_text(source) -> str:
    if source.is_readme:
        return "README自身"
    if not source.exists:
        return "対象なし"
    if source.readme_linked is True:
        return "あり"
    if source.readme_linked is False:
        return "確認できず"
    return "未確認"
