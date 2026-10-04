from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .file_safety import is_sensitive_path


MAX_PROJECT_LIST_BYTES = 1_000_000
MAX_STEWARD_PROPOSALS = 3

TARGET_SECTION = "対象"
EVENT_SECTION = "event受領記録"

TARGET_REQUIRED_COLUMNS = (
    "プロジェクト",
    "導入状態",
    "浅い状態",
    "次回確認",
)
EVENT_REQUIRED_COLUMNS = (
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
)

TARGET_COLUMN_ALIASES = {
    "Project": "プロジェクト",
    "Next review": "次回確認",
}

EVENT_COLUMN_ALIASES = {
    "Project": "プロジェクト",
    "Parent receipt": "オーナー付きStewardの受領",
    "Local reflection": "正本への反映",
    "Pending / Owner": "判断待ち / 確認先",
    "Next check": "次回確認",
}

PARENT_RECEIPT_VALUES = frozenset({"未受領", "受領済み", "不明"})
LOCAL_REFLECTION_VALUES = frozenset(
    {"未確認", "反映待ち", "反映確認済み", "反映不要"}
)
UNKNOWN_VALUES = frozenset({"unknown", "不明"})
CLOSED_PENDING_VALUES = frozenset({"-", "なし"})
INTRODUCED_VALUE = "導入済み"
URGENCY_VALUES = frozenset({"通常", "優先", "緊急", "不明"})
CROSS_COVERAGE_VALUES = frozenset(
    {"対応済み", "対象外", "未確認", "該当なし"}
)


class FollowupInputError(ValueError):
    """Raised when a parent list cannot be interpreted without guessing."""


@dataclass(frozen=True)
class Followup:
    project: str
    reason: str
    due: date | None = None


@dataclass(frozen=True)
class FollowupGuidance:
    order: int
    label: str
    proposal: str


FOLLOWUP_GUIDANCE = {
    "owner_urgency_urgent": FollowupGuidance(
        1,
        "オーナーが緊急とした事項が未完了",
        "緊急性と理由を保ったまま、許可済みの次の行動を進めます。障害がある場合も遠い日付へ送らず、確認先と戻る条件を確定します。",
    ),
    "owner_urgency_priority": FollowupGuidance(
        2,
        "オーナーが優先とした事項が未完了",
        "優先理由を保ったまま、損失拡大、作業停止、履歴の再現性、現在の許可範囲を確認して次の一手を進めます。",
    ),
    "cross_project_coverage_missing": FollowupGuidance(
        3,
        "横断対応の照合先が不足",
        "導入済みプロジェクトのうち照合記録がない対象を確認し、対応済み、対象外、未確認のいずれかへ根拠付きで分けます。",
    ),
    "cross_project_coverage_unconfirmed": FollowupGuidance(
        4,
        "横断対応が未確認",
        "名前の一致だけで適用を決めず、このプロジェクトが対応済みか対象外かを根拠から確認します。",
    ),
    "urgency_unknown": FollowupGuidance(
        5,
        "未完了事項の緊急性が不明",
        "元の依頼またはオーナーの指示を確認し、緊急性と理由を推測せず回収します。",
    ),
    "next_action_missing": FollowupGuidance(
        6,
        "未完了事項の次の行動が未設定",
        "許可済みの次の行動、確認先、戻る条件を定め、今実行できることはその場で進めます。",
    ),
    "local_reflection_pending": FollowupGuidance(
        7,
        "プロジェクト内の正本への反映待ち",
        "プロジェクト内の根拠と反映結果を確認し、反映済みか、理由付きで反映不要かまで閉じます。",
    ),
    "local_reflection_unconfirmed": FollowupGuidance(
        8,
        "プロジェクト内の正本への反映が未確認",
        "変更連絡が正本へ影響するかを確認し、必要なら担当へ最小修復案を渡します。受領状態は別に確認します。",
    ),
    "parent_receipt_unreceived": FollowupGuidance(
        9,
        "オーナー付きStewardが未受領",
        "変更連絡の確認先を特定し、まだ渡していない場合だけ一度届け、受領結果を確認します。",
    ),
    "parent_receipt_unknown": FollowupGuidance(
        10,
        "オーナー付きStewardの受領が不明",
        "既存の受領痕跡を照合し、判断できなければ確認先を絞って一度だけ確認します。",
    ),
    "confirmation_target_unknown": FollowupGuidance(
        11,
        "判断待ちまたは確認先が不明",
        "確認済みの事実と不明を分け、オーナーへ最重要の質問を1件だけ提案します。",
    ),
    "next_check_due": FollowupGuidance(
        12,
        "変更連絡の再確認日が来ています",
        "保留中の結果を確認し、次の扱いを決めるか、確認先と次に戻る条件を更新します。",
    ),
    "shallow_state_unknown": FollowupGuidance(
        13,
        "浅い状態が不明",
        "個別プロジェクト付きStewardの根拠から現在地を回収し、決められなければ状態を推測せず確認します。",
    ),
    "next_review_due": FollowupGuidance(
        14,
        "プロジェクトの次回確認日が来ています",
        "現在地と具体的な次の作業を確認し、現在の状態宣言を続けるか見直す案を作ります。",
    ),
    "review_deadline_missing": FollowupGuidance(
        6,
        "見守り対象の確認期限が未設定",
        "連絡がなくても実態を確認する日と確認先を、既存の許可範囲で定めます。確定できなければオーナーへ確認方法を相談し、条件待ちだけで放置しません。",
    ),
}


@dataclass(frozen=True)
class _TableRow:
    line_number: int
    values: dict[str, str]


def select_followups(list_path: Path, as_of: date) -> list[Followup]:
    """Select shallow follow-up signals from one explicitly supplied list."""

    text = _read_project_list(list_path)
    target_rows = _read_table(
        text,
        section_name=TARGET_SECTION,
        required_columns=TARGET_REQUIRED_COLUMNS,
        column_aliases=TARGET_COLUMN_ALIASES,
    )
    event_rows = _read_table(
        text,
        section_name=EVENT_SECTION,
        required_columns=EVENT_REQUIRED_COLUMNS,
        column_aliases=EVENT_COLUMN_ALIASES,
    )

    _validate_target_rows(target_rows)
    _validate_event_rows(event_rows)

    selected: list[Followup] = []
    for row in target_rows:
        project = row.values["プロジェクト"]
        review_due = _parse_trigger_date(
            row.values["次回確認"],
            section_name=TARGET_SECTION,
            line_number=row.line_number,
            column_name="次回確認",
        )
        if review_due is not None and review_due <= as_of:
            selected.append(
                Followup(project, "next_review_due", due=review_due)
            )
        elif review_due is None and row.values["導入状態"] == INTRODUCED_VALUE:
            selected.append(Followup(project, "review_deadline_missing"))
        if _is_unknown(row.values["浅い状態"]):
            selected.append(Followup(project, "shallow_state_unknown"))

    for row in event_rows:
        project = row.values["プロジェクト"]
        receipt = row.values["オーナー付きStewardの受領"]
        reflection = row.values["正本への反映"]
        pending = row.values["判断待ち / 確認先"]
        next_check = _parse_trigger_date(
            row.values["次回確認"],
            section_name=EVENT_SECTION,
            line_number=row.line_number,
            column_name="次回確認",
        )

        if receipt == "未受領":
            selected.append(Followup(project, "parent_receipt_unreceived"))
        elif receipt == "不明":
            selected.append(Followup(project, "parent_receipt_unknown"))

        if reflection == "未確認":
            selected.append(Followup(project, "local_reflection_unconfirmed"))
        elif reflection == "反映待ち":
            selected.append(Followup(project, "local_reflection_pending"))

        if _is_unknown(pending):
            selected.append(Followup(project, "confirmation_target_unknown"))

        event_is_open = (
            receipt in {"未受領", "不明"}
            or reflection in {"未確認", "反映待ち"}
            or pending not in CLOSED_PENDING_VALUES
            or row.values["横断対応"] == "未確認"
        )
        urgency = row.values["緊急性"]
        if event_is_open and urgency == "緊急":
            selected.append(Followup(project, "owner_urgency_urgent"))
        elif event_is_open and urgency == "優先":
            selected.append(Followup(project, "owner_urgency_priority"))
        elif event_is_open and urgency == "不明":
            selected.append(Followup(project, "urgency_unknown"))

        if (
            event_is_open
            and row.values["次の行動 / 戻る条件"] in CLOSED_PENDING_VALUES | UNKNOWN_VALUES
        ):
            selected.append(Followup(project, "next_action_missing"))

        if row.values["横断対応"] == "未確認":
            selected.append(Followup(project, "cross_project_coverage_unconfirmed"))

        if event_is_open and next_check is not None and next_check <= as_of:
            selected.append(Followup(project, "next_check_due", due=next_check))

    introduced_projects = {
        row.values["プロジェクト"]
        for row in target_rows
        if row.values["導入状態"] == INTRODUCED_VALUE
    }
    cross_project_rows: dict[str, set[str]] = {}
    for row in event_rows:
        cross_item = row.values["横断事項"]
        if cross_item in CLOSED_PENDING_VALUES:
            continue
        cross_project_rows.setdefault(cross_item, set()).add(
            row.values["プロジェクト"]
        )
    for covered_projects in cross_project_rows.values():
        for project in sorted(introduced_projects - covered_projects):
            selected.append(
                Followup(project, "cross_project_coverage_missing")
            )

    return list(dict.fromkeys(selected))


def build_followups_report(items: list[Followup], as_of: date) -> str:
    lines = [
        "# オーナー付きStewardの再確認候補",
        "",
        f"- 基準日: `{as_of.isoformat()}`",
        "- 選別範囲: 指定された対象一覧全体",
        f"- 件数: `{len(items)}`",
    ]
    if not items:
        return "\n".join(
            [
                *lines,
                "",
                "一覧に記録された範囲では、機械的な再確認候補はありません。",
                "これは全プロジェクトの実状態を確認したことや、オーナーが今することがないことを意味しません。",
                "未完了全体と個別の定期確認の未回収結果も照合してください。取得できない結果を無回答と断定しません。",
            ]
        ) + "\n"

    lines.extend(
        [
            "",
            "| プロジェクト | 理由 | 内部コード | 期限 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in items:
        project = _escape_table_cell(item.project)
        guidance = _guidance_for(item.reason)
        due = item.due.isoformat() if item.due is not None else "-"
        lines.append(
            f"| {project} | {guidance.label} | `{item.reason}` | {due} |"
        )

    proposals = _prioritized_project_proposals(items)
    lines.extend(
        [
            "",
            "## Stewardからのご提案",
            "",
            "指定された対象一覧全体から選別した後、記録済みの緊急性と浅い理由から決めた機械的な確認順です。プロジェクトの実状態を読んだ判定ではありません。",
            "",
        ]
    )
    for index, (project, guidance) in enumerate(proposals, start=1):
        lines.append(
            f"{index}. `{_escape_inline_code(project)}`: {guidance.proposal}"
        )
    remaining = len({item.project for item in items}) - len(proposals)
    if remaining > 0:
        lines.append(
            f"- 残る {remaining} プロジェクトも候補として保持し、今回の提案表示からだけ省略しています。"
        )

    lines.extend(
        [
            "",
            "### 完了の確認",
            "",
            "- この候補を記録または通知しただけでは完了にしません。",
            "- 根拠を確認済みの結果があれば浅い対象一覧へ同期し、判断が必要なら推奨を添えた質問を1件だけ返します。",
            "- 項目を閉じる時は、同じ基準日で再選別し、同じ候補が消えたことを確認します。候補を消すためだけの日付変更はしません。",
            "- 判断待ちや結果待ちなら、確認先と次に戻る条件を残して今回の確認だけを終えます。項目自体は未完了のままです。",
            "- 確認期限を過ぎ、限定した再確認でも実態や結果を回収できなければ、Butlerがオーナーへ危険と回復案を報告・相談します。確認せず日付だけを先送りしません。",
        ]
    )
    return "\n".join(lines) + "\n"


def _prioritized_project_proposals(
    items: list[Followup],
) -> list[tuple[str, FollowupGuidance]]:
    first_seen: dict[str, int] = {}
    best: dict[str, FollowupGuidance] = {}
    for index, item in enumerate(items):
        guidance = _guidance_for(item.reason)
        first_seen.setdefault(item.project, index)
        current = best.get(item.project)
        if current is None or guidance.order < current.order:
            best[item.project] = guidance

    ranked = sorted(
        best,
        key=lambda project: (best[project].order, first_seen[project]),
    )
    return [
        (project, best[project])
        for project in ranked[:MAX_STEWARD_PROPOSALS]
    ]


def _guidance_for(reason: str) -> FollowupGuidance:
    guidance = FOLLOWUP_GUIDANCE.get(reason)
    if guidance is None:
        raise ValueError("再確認候補に対応する提案が定義されていません。")
    return guidance


def _read_project_list(path: Path) -> str:
    if path.suffix.lower() != ".md" or is_sensitive_path(Path(path.name)):
        raise FollowupInputError(
            "一覧は機密名ではないMarkdownファイルを明示してください。"
        )
    try:
        if path.is_symlink():
            raise FollowupInputError("一覧がsymlinkのため読みませんでした。")
        if not path.is_file():
            raise FollowupInputError("一覧ファイルを確認できませんでした。")
        if path.stat().st_size > MAX_PROJECT_LIST_BYTES:
            raise FollowupInputError("一覧が読み取り上限を超えています。")
        return path.read_text(encoding="utf-8")
    except FollowupInputError:
        raise
    except (OSError, UnicodeError) as exc:
        raise FollowupInputError("一覧ファイルを安全に読めませんでした。") from exc


def _read_table(
    text: str,
    *,
    section_name: str,
    required_columns: tuple[str, ...],
    column_aliases: dict[str, str],
) -> list[_TableRow]:
    lines = text.splitlines()
    heading = f"## {section_name}"
    heading_lines = [
        index for index, line in enumerate(lines) if line.strip() == heading
    ]
    if len(heading_lines) != 1:
        raise FollowupInputError(
            f"`{section_name}`セクションを一意に確認できませんでした。"
        )

    start = heading_lines[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index].strip()):
            end = index
            break

    candidates: list[tuple[int, list[str]]] = []
    for index in range(start, max(start, end - 1)):
        if not _looks_like_table_row(lines[index]):
            continue
        try:
            raw_headers = _split_markdown_row(lines[index])
            headers = [column_aliases.get(header, header) for header in raw_headers]
            separator = _split_markdown_row(lines[index + 1])
        except FollowupInputError:
            continue
        if len(headers) != len(separator) or not all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in separator
        ):
            continue
        if set(required_columns).issubset(headers):
            candidates.append((index, headers))

    if len(candidates) != 1:
        raise FollowupInputError(
            f"`{section_name}`の対象表を一意に確認できませんでした。"
        )

    header_index, headers = candidates[0]
    duplicate_headers = sorted(
        {header for header in headers if headers.count(header) > 1}
    )
    if duplicate_headers:
        raise FollowupInputError(
            f"`{section_name}`の表に重複した列があります。"
        )
    missing = [column for column in required_columns if column not in headers]
    if missing:
        raise FollowupInputError(
            f"`{section_name}`の表に必須列がありません。"
        )

    rows: list[_TableRow] = []
    for index in range(header_index + 2, end):
        line = lines[index]
        if not line.strip():
            break
        if not line.lstrip().startswith("|"):
            if _looks_like_missing_leading_table_row(line, len(headers)):
                raise FollowupInputError(
                    f"`{section_name}`の表の{index + 1}行目が壊れています。"
                )
            break
        cells = _split_markdown_row(line)
        if len(cells) != len(headers):
            raise FollowupInputError(
                f"`{section_name}`の表の{index + 1}行目が壊れています。"
            )
        rows.append(
            _TableRow(
                line_number=index + 1,
                values=dict(zip(headers, cells, strict=True)),
            )
        )
    return rows


def _validate_target_rows(rows: list[_TableRow]) -> None:
    projects: set[str] = set()
    for row in rows:
        project = _validate_project(row, TARGET_SECTION)
        if project in projects:
            raise FollowupInputError("`対象`の表に重複したプロジェクトがあります。")
        projects.add(project)
        if not row.values["導入状態"]:
            raise FollowupInputError(
                f"`{TARGET_SECTION}`の{row.line_number}行目の導入状態が空です。"
            )
        if not row.values["浅い状態"]:
            raise FollowupInputError(
                f"`{TARGET_SECTION}`の{row.line_number}行目の浅い状態が空です。"
            )
        _parse_trigger_date(
            row.values["次回確認"],
            section_name=TARGET_SECTION,
            line_number=row.line_number,
            column_name="次回確認",
        )


def _validate_event_rows(rows: list[_TableRow]) -> None:
    seen_cross_projects: set[tuple[str, str]] = set()
    for row in rows:
        project = _validate_project(row, EVENT_SECTION)
        if row.values["オーナー付きStewardの受領"] not in PARENT_RECEIPT_VALUES:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目に既知でない"
                "オーナー付きStewardの受領状態があります。"
            )
        if row.values["正本への反映"] not in LOCAL_REFLECTION_VALUES:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目に既知でない"
                "正本への反映状態があります。"
            )
        if not row.values["判断待ち / 確認先"]:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目の"
                "判断待ち / 確認先が空です。"
            )
        urgency = row.values["緊急性"]
        if urgency not in URGENCY_VALUES:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目に既知でない"
                "緊急性があります。"
            )
        if not row.values["緊急性の理由"]:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目の緊急性の理由が空です。"
            )
        if not row.values["次の行動 / 戻る条件"]:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目の"
                "次の行動 / 戻る条件が空です。"
            )
        cross_item = row.values["横断事項"]
        coverage = row.values["横断対応"]
        if not cross_item:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目の横断事項が空です。"
            )
        if coverage not in CROSS_COVERAGE_VALUES:
            raise FollowupInputError(
                f"`{EVENT_SECTION}`の{row.line_number}行目に既知でない"
                "横断対応があります。"
            )
        if cross_item in CLOSED_PENDING_VALUES:
            if coverage != "該当なし":
                raise FollowupInputError(
                    f"`{EVENT_SECTION}`の{row.line_number}行目の横断対応が"
                    "横断事項と一致しません。"
                )
        else:
            if coverage == "該当なし":
                raise FollowupInputError(
                    f"`{EVENT_SECTION}`の{row.line_number}行目の横断対応が"
                    "横断事項と一致しません。"
                )
            cross_project = (cross_item, project)
            if cross_project in seen_cross_projects:
                raise FollowupInputError(
                    f"`{EVENT_SECTION}`の{row.line_number}行目に重複した"
                    "横断事項の照合があります。"
                )
            seen_cross_projects.add(cross_project)
        _parse_trigger_date(
            row.values["次回確認"],
            section_name=EVENT_SECTION,
            line_number=row.line_number,
            column_name="次回確認",
        )


def _validate_project(row: _TableRow, section_name: str) -> str:
    project = row.values["プロジェクト"]
    if (
        not project
        or len(project) > 200
        or any(unicodedata.category(character).startswith("C") for character in project)
    ):
        raise FollowupInputError(
            f"`{section_name}`の{row.line_number}行目のプロジェクトを安全に表示できません。"
        )
    return project


def _parse_trigger_date(
    value: str,
    *,
    section_name: str,
    line_number: int,
    column_name: str,
) -> date | None:
    text = value.strip()
    if not text:
        raise FollowupInputError(
            f"`{section_name}`の{line_number}行目の{column_name}が空です。"
        )
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise FollowupInputError(
                f"`{section_name}`の{line_number}行目の{column_name}が不正な日付です。"
            ) from exc
    if "YYYY" in text.upper() or any(character.isdigit() for character in text):
        raise FollowupInputError(
            f"`{section_name}`の{line_number}行目の{column_name}が日付として曖昧です。"
        )
    return None


def _is_unknown(value: str) -> bool:
    return value.strip().casefold() in UNKNOWN_VALUES


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _looks_like_missing_leading_table_row(line: str, column_count: int) -> bool:
    stripped = line.strip()
    if stripped.startswith("|") or not stripped.endswith("|"):
        return False
    try:
        return len(_split_markdown_row(f"|{stripped}")) == column_count
    except FollowupInputError:
        return False


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise FollowupInputError("Markdown表の行を解釈できませんでした。")

    cells: list[str] = []
    current: list[str] = []
    for character in stripped[1:-1]:
        if character == "|":
            backslashes = 0
            for previous in reversed(current):
                if previous != "\\":
                    break
                backslashes += 1
            if backslashes % 2 == 0:
                cells.append("".join(current).strip().replace(r"\|", "|"))
                current = []
                continue
        current.append(character)
    cells.append("".join(current).strip().replace(r"\|", "|"))
    return cells


def _escape_table_cell(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;")


def _escape_inline_code(value: str) -> str:
    return html.escape(value, quote=False).replace("`", "&#96;")
