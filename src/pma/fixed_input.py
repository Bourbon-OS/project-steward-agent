from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from os.path import abspath, normcase
from pathlib import Path
from typing import Callable, Literal

from .config import AppConfig, ConfigResult
from .file_safety import is_allowed_text_file, is_sensitive_path


MAX_FIXED_INPUT_BYTES = 1_000_000

FixedInputCategory = Literal["automatic_instruction", "always_read", "legacy_status"]
FixedInputReadState = Literal[
    "loaded",
    "missing",
    "outside_project",
    "disallowed",
    "unreadable",
    "not_file",
]
FixedInputScopeState = Literal["declared", "legacy", "unconfirmed", "unavailable"]
FixedInputMeasurementState = Literal["complete", "partial", "unconfirmed"]


@dataclass(frozen=True)
class FixedInputFile:
    path: str
    category: FixedInputCategory
    read_state: FixedInputReadState
    character_count: int | None = None
    line_count: int | None = None
    token_count: int | None = None


@dataclass(frozen=True)
class FixedInputObservation:
    scope_state: FixedInputScopeState
    measurement_state: FixedInputMeasurementState
    files: tuple[FixedInputFile, ...]
    read_when_needed_files: tuple[str, ...]
    reference_files: tuple[str, ...]
    character_count: int | None
    line_count: int | None
    token_count: int | None
    token_encoding: str
    target_chars: int
    target_lines: int
    high_cost_chars: int
    high_cost_lines: int
    exception_reason: str | None
    exception_review_condition: str | None


def inspect_fixed_input(
    root: Path,
    config_result: ConfigResult,
) -> FixedInputObservation:
    config = config_result.config
    common = {
        "read_when_needed_files": tuple(config.read_when_needed_files),
        "reference_files": tuple(config.reference_files),
        "token_encoding": config.token_encoding,
        "target_chars": config.fixed_input_target_chars,
        "target_lines": config.fixed_input_target_lines,
        "high_cost_chars": config.fixed_input_high_chars,
        "high_cost_lines": config.fixed_input_high_lines,
        "exception_reason": config.fixed_input_exception_reason,
        "exception_review_condition": config.fixed_input_review_condition,
    }

    if config_result.load_state == "unavailable":
        return FixedInputObservation(
            scope_state="unavailable",
            measurement_state="unconfirmed",
            files=(),
            character_count=None,
            line_count=None,
            token_count=None,
            **common,
        )

    if config_result.load_state == "missing":
        return FixedInputObservation(
            scope_state="unconfirmed",
            measurement_state="unconfirmed",
            files=(),
            character_count=None,
            line_count=None,
            token_count=None,
            **common,
        )

    if config.fixed_input_scope_declared:
        paths = _deduplicated_fixed_paths(config)
        scope_state: FixedInputScopeState = "declared"
    else:
        paths = [(config.status_file, "legacy_status")]
        scope_state = "legacy"

    observations = tuple(
        _inspect_file(root, path, category, config.token_encoding)
        for path, category in paths
    )
    complete = all(item.read_state == "loaded" for item in observations)
    measurement_state: FixedInputMeasurementState = "complete" if complete else "partial"
    loaded = [item for item in observations if item.read_state == "loaded"]
    character_count = sum(item.character_count or 0 for item in loaded)
    line_count = sum(item.line_count or 0 for item in loaded)
    token_count = (
        sum(item.token_count or 0 for item in loaded)
        if complete and all(item.token_count is not None for item in loaded)
        else None
    )

    return FixedInputObservation(
        scope_state=scope_state,
        measurement_state=measurement_state,
        files=observations,
        character_count=character_count,
        line_count=line_count,
        token_count=token_count,
        **common,
    )


def _deduplicated_fixed_paths(
    config: AppConfig,
) -> list[tuple[str, FixedInputCategory]]:
    seen: set[str] = set()
    result: list[tuple[str, FixedInputCategory]] = []
    for category, paths in (
        ("automatic_instruction", config.automatic_instruction_files),
        ("always_read", config.always_read_files),
    ):
        for path in paths:
            normalized = normcase(str(Path(path)))
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append((path, category))
    return result


def _inspect_file(
    root: Path,
    configured_path: str,
    category: FixedInputCategory,
    token_encoding: str,
) -> FixedInputFile:
    root = root.resolve()
    configured = Path(configured_path)
    candidate = configured if configured.is_absolute() else root / configured
    candidate = Path(abspath(candidate))
    if not candidate.is_relative_to(root):
        return FixedInputFile(configured_path, category, "outside_project")

    relative = candidate.relative_to(root)
    try:
        resolved = candidate.resolve()
        if candidate.is_symlink() or resolved != candidate:
            return FixedInputFile(configured_path, category, "disallowed")
        if not candidate.exists():
            return FixedInputFile(configured_path, category, "missing")
        if not candidate.is_file():
            return FixedInputFile(configured_path, category, "not_file")
        if is_sensitive_path(relative) or not is_allowed_text_file(candidate):
            return FixedInputFile(configured_path, category, "disallowed")
        if candidate.stat().st_size > MAX_FIXED_INPUT_BYTES:
            return FixedInputFile(configured_path, category, "disallowed")
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return FixedInputFile(configured_path, category, "unreadable")

    return FixedInputFile(
        path=configured_path,
        category=category,
        read_state="loaded",
        character_count=len(text),
        line_count=len(text.splitlines()),
        token_count=count_text_tokens(text, token_encoding),
    )


def count_text_tokens(text: str, encoding_name: str) -> int | None:
    encoder = _load_token_encoder(encoding_name)
    if encoder is None:
        return None
    try:
        return len(encoder(text))
    except Exception:  # noqa: BLE001 - optional measurement must not stop scan.
        return None


@lru_cache(maxsize=4)
def _load_token_encoder(encoding_name: str) -> Callable[[str], list[int]] | None:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:  # noqa: BLE001 - unsupported optional encoding is unconfirmed.
        return None
    return encoding.encode
