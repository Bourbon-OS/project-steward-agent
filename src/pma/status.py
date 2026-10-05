from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from .file_safety import is_allowed_text_file, is_sensitive_path


KNOWN_STATUS_VALUES = frozenset({"active", "paused", "blocked", "archived"})


@dataclass(frozen=True)
class ProjectStatus:
    path: Path
    exists: bool
    status: str | None
    last_updated: str | None
    last_reviewed: str | None
    next_review: str | None
    warnings: list[str]
    read_state: Literal["loaded", "missing", "unavailable"] = "loaded"
    duplicate_fields: list[str] = field(default_factory=list)
    status_line_number: int | None = None
    status_line_text: str | None = None
    character_count: int | None = None
    line_count: int | None = None

    @property
    def review_date(self) -> date | None:
        return parse_date(self.last_reviewed) or parse_date(self.last_updated)


def read_project_status(root: Path, filename: str = "PROJECT_STATUS.md") -> ProjectStatus:
    root = root.resolve()
    configured = Path(filename)
    path = (
        configured.resolve()
        if configured.is_absolute()
        else (root / configured).resolve()
    )
    warnings: list[str] = []
    display_name = configured.as_posix()
    if not path.is_relative_to(root):
        return ProjectStatus(
            path=path,
            exists=False,
            status=None,
            last_updated=None,
            last_reviewed=None,
            next_review=None,
            warnings=[
                f"設定されたstatus file `{display_name}` がプロジェクト外を指すため読みませんでした。"
            ],
            read_state="unavailable",
        )

    if not path.exists():
        return ProjectStatus(
            path=path,
            exists=False,
            status=None,
            last_updated=None,
            last_reviewed=None,
            next_review=None,
            warnings=[f"status file `{display_name}` が見つかりません。"],
            read_state="missing",
        )

    relative = path.relative_to(root)
    if is_sensitive_path(relative) or not is_allowed_text_file(path):
        return ProjectStatus(
            path=path,
            exists=True,
            status=None,
            last_updated=None,
            last_reviewed=None,
            next_review=None,
            warnings=[
                f"設定されたstatus file `{display_name}` は安全な読み取り対象ではないため読みませんでした。"
            ],
            read_state="unavailable",
        )

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ProjectStatus(
            path=path,
            exists=True,
            status=None,
            last_updated=None,
            last_reviewed=None,
            next_review=None,
            warnings=[f"status file `{display_name}` を読めませんでした: {exc}"],
            read_state="unavailable",
        )

    fields, duplicate_fields, field_lines, field_texts = _parse_status_fields(text)
    for duplicate_field in duplicate_fields:
        fields.pop(duplicate_field, None)

    status_value = fields.get("status")
    last_updated = fields.get("last updated")
    last_reviewed = fields.get("last_reviewed")
    next_review = fields.get("next_review")

    if duplicate_fields:
        warnings.append(
            f"status file `{display_name}` に重複した状態項目があります: "
            f"{', '.join(duplicate_fields)}。"
        )

    if "status" not in duplicate_fields:
        if not status_value:
            warnings.append(
                f"status file `{display_name}` に status が見つかりません。"
            )
        elif not is_recognized_status(status_value):
            warnings.append(
                f"status file `{display_name}` の status は既知の互換値ではありません。"
            )
    if not last_reviewed and "last_reviewed" not in duplicate_fields:
        warnings.append(
            f"status file `{display_name}` に last_reviewed が見つかりません。"
        )
    if not next_review and "next_review" not in duplicate_fields:
        warnings.append(
            f"status file `{display_name}` に next_review が見つかりません。"
        )
    for field_name, value in (
        ("Last updated", last_updated),
        ("last_reviewed", last_reviewed),
        ("next_review", next_review),
    ):
        if value and parse_date(value) is None:
            warnings.append(
                f"status file `{display_name}` の {field_name} を日付として解釈できません。"
            )

    return ProjectStatus(
        path=path,
        exists=True,
        status=status_value,
        last_updated=last_updated,
        last_reviewed=last_reviewed,
        next_review=next_review,
        warnings=warnings,
        read_state="loaded",
        duplicate_fields=duplicate_fields,
        status_line_number=(
            field_lines.get("status")
            if "status" not in duplicate_fields
            else None
        ),
        status_line_text=(
            field_texts.get("status")
            if "status" not in duplicate_fields
            else None
        ),
        character_count=len(text),
        line_count=len(text.splitlines()),
    )


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text or "YYYY" in text:
        return None

    if len(text) == 10:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize_status(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def is_recognized_status(value: str | None) -> bool:
    return normalize_status(value) in KNOWN_STATUS_VALUES


def _parse_status_fields(
    text: str,
) -> tuple[dict[str, str], list[str], dict[str, int], dict[str, str]]:
    fields: dict[str, str] = {}
    duplicate_fields: list[str] = []
    field_lines: dict[str, int] = {}
    field_texts: dict[str, str] = {}
    wanted = {"status", "last updated", "last_reviewed", "next_review"}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().lower()
        if normalized in wanted:
            if normalized in fields and normalized not in duplicate_fields:
                duplicate_fields.append(normalized)
            fields[normalized] = value.strip()
            field_lines[normalized] = line_number
            field_texts[normalized] = line
    return fields, duplicate_fields, field_lines, field_texts
