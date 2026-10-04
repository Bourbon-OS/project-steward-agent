from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


DEFAULT_REQUIRED_FILES = ["README.md", "PROJECT_STATUS.md", ".project-agent.yml"]
DEFAULT_FOOTWORK_KEYWORDS = ["TODO", "FIXME", "あとで", "未定", "仮", "要確認"]
DEFAULT_EXCLUDE_PATHS = ["reports/**"]
DEFAULT_STATUS_FILE = "PROJECT_STATUS.md"
DEFAULT_SOURCE_OF_TRUTH = ["README.md", "PROJECT_STATUS.md"]
DEFAULT_STALE_DAYS = {"active": 14, "paused": 30, "archived": 180}
DEFAULT_OUTPUT_DIR = "reports"
DEFAULT_MAX_PRIORITY_ACTIONS = 3
DEFAULT_STATUS_MAX_CHARS = 4_096
DEFAULT_STATUS_MAX_LINES = 128
DEFAULT_FIXED_INPUT_TARGET_CHARS = 8_192
DEFAULT_FIXED_INPUT_TARGET_LINES = 192
DEFAULT_FIXED_INPUT_HIGH_CHARS = 16_384
DEFAULT_FIXED_INPUT_HIGH_LINES = 384
DEFAULT_TOKEN_ENCODING = "o200k_base"
MAX_CONFIG_BYTES = 1_000_000


@dataclass(frozen=True)
class AppConfig:
    status_file: str
    source_of_truth: list[str]
    required_files: list[str]
    footwork_keywords: list[str]
    exclude_paths: list[str]
    status_max_chars: int
    status_max_lines: int
    fixed_input_scope_declared: bool
    automatic_instruction_files: list[str]
    always_read_files: list[str]
    read_when_needed_files: list[str]
    reference_files: list[str]
    fixed_input_target_chars: int
    fixed_input_target_lines: int
    fixed_input_high_chars: int
    fixed_input_high_lines: int
    fixed_input_exception_reason: str | None
    fixed_input_review_condition: str | None
    token_encoding: str
    stale_days: dict[str, int]
    output_dir: str
    max_priority_actions: int


@dataclass(frozen=True)
class ConfigResult:
    path: Path
    exists: bool
    config: AppConfig
    warnings: list[str]
    load_state: Literal["loaded", "missing", "unavailable"] = "loaded"


def default_config() -> AppConfig:
    return AppConfig(
        status_file=DEFAULT_STATUS_FILE,
        source_of_truth=list(DEFAULT_SOURCE_OF_TRUTH),
        required_files=list(DEFAULT_REQUIRED_FILES),
        footwork_keywords=list(DEFAULT_FOOTWORK_KEYWORDS),
        exclude_paths=list(DEFAULT_EXCLUDE_PATHS),
        status_max_chars=DEFAULT_STATUS_MAX_CHARS,
        status_max_lines=DEFAULT_STATUS_MAX_LINES,
        fixed_input_scope_declared=False,
        automatic_instruction_files=[],
        always_read_files=[],
        read_when_needed_files=[],
        reference_files=[],
        fixed_input_target_chars=DEFAULT_FIXED_INPUT_TARGET_CHARS,
        fixed_input_target_lines=DEFAULT_FIXED_INPUT_TARGET_LINES,
        fixed_input_high_chars=DEFAULT_FIXED_INPUT_HIGH_CHARS,
        fixed_input_high_lines=DEFAULT_FIXED_INPUT_HIGH_LINES,
        fixed_input_exception_reason=None,
        fixed_input_review_condition=None,
        token_encoding=DEFAULT_TOKEN_ENCODING,
        stale_days=dict(DEFAULT_STALE_DAYS),
        output_dir=DEFAULT_OUTPUT_DIR,
        max_priority_actions=DEFAULT_MAX_PRIORITY_ACTIONS,
    )


def load_config(root: Path) -> ConfigResult:
    path = root / ".project-agent.yml"
    config = default_config()
    warnings: list[str] = []

    if path.is_symlink():
        return _unavailable_config(
            path,
            config,
            ".project-agent.yml はsymlinkのため読みませんでした。",
        )

    if not path.exists():
        warnings.append(".project-agent.yml が見つかりません。既定値で続行します。")
        return ConfigResult(
            path=path,
            exists=False,
            config=config,
            warnings=warnings,
            load_state="missing",
        )

    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            return _unavailable_config(
                path,
                config,
                ".project-agent.yml がサイズ上限を超えているため読みませんでした。",
            )
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _unavailable_config(
            path,
            config,
            ".project-agent.yml をUTF-8テキストとして読めませんでした。",
        )

    try:
        data = _load_yaml(raw)
    except Exception:  # noqa: BLE001 - config should not stop the MVP scan.
        return _unavailable_config(
            path,
            config,
            ".project-agent.yml の解釈に失敗しました。",
        )

    if not isinstance(data, dict):
        return _unavailable_config(
            path,
            config,
            ".project-agent.yml が辞書形式ではありません。",
        )

    checks = _dict_at(data, "checks")
    project = _dict_at(data, "project")
    stale = _dict_at(data, "stale")
    report = _dict_at(data, "report")
    reading = _dict_at(data, "reading")

    status_file = _string_value(project.get("status_file"), DEFAULT_STATUS_FILE)
    source_of_truth = _string_list(
        project.get("source_of_truth"),
        ["README.md", status_file],
    )
    default_required_files = ["README.md", status_file, ".project-agent.yml"]
    required_files = _string_list(
        checks.get("required_files"), default_required_files
    )
    keywords = _string_list(checks.get("footwork_keywords"), DEFAULT_FOOTWORK_KEYWORDS)
    exclude_paths = _string_list(
        checks.get("exclude_paths"), DEFAULT_EXCLUDE_PATHS
    )
    status_max_chars = _positive_int(
        checks.get("status_max_chars"), DEFAULT_STATUS_MAX_CHARS
    )
    status_max_lines = _positive_int(
        checks.get("status_max_lines"), DEFAULT_STATUS_MAX_LINES
    )
    fixed_input_scope_declared = any(
        key in reading
        for key in ("automatic_instruction_files", "always_read_files")
    )
    automatic_instruction_files = _string_list_allow_empty(
        reading.get("automatic_instruction_files")
    )
    always_read_files = _string_list_allow_empty(
        reading.get("always_read_files")
    )
    read_when_needed_files = _string_list_allow_empty(
        reading.get("read_when_needed_files")
    )
    reference_files = _string_list_allow_empty(
        reading.get("reference_files")
    )
    fixed_input_target_chars = _positive_int(
        reading.get("target_chars"), DEFAULT_FIXED_INPUT_TARGET_CHARS
    )
    fixed_input_target_lines = _positive_int(
        reading.get("target_lines"), DEFAULT_FIXED_INPUT_TARGET_LINES
    )
    fixed_input_high_chars = _positive_int(
        reading.get("high_cost_chars"), DEFAULT_FIXED_INPUT_HIGH_CHARS
    )
    fixed_input_high_lines = _positive_int(
        reading.get("high_cost_lines"), DEFAULT_FIXED_INPUT_HIGH_LINES
    )
    fixed_input_high_chars = max(
        fixed_input_high_chars, fixed_input_target_chars
    )
    fixed_input_high_lines = max(
        fixed_input_high_lines, fixed_input_target_lines
    )
    fixed_input_exception_reason = _optional_string(
        reading.get("exception_reason")
    )
    fixed_input_review_condition = _optional_string(
        reading.get("exception_review_condition")
    )
    token_encoding = _string_value(
        reading.get("token_encoding"), DEFAULT_TOKEN_ENCODING
    )
    stale_days = {
        "active": _positive_int(stale.get("active_days"), DEFAULT_STALE_DAYS["active"]),
        "paused": _positive_int(stale.get("paused_days"), DEFAULT_STALE_DAYS["paused"]),
        "archived": _positive_int(stale.get("archived_days"), DEFAULT_STALE_DAYS["archived"]),
    }
    output_dir = _string_value(report.get("output_dir"), DEFAULT_OUTPUT_DIR)
    max_priority_actions = _positive_int(
        report.get("max_priority_actions"), DEFAULT_MAX_PRIORITY_ACTIONS
    )

    return ConfigResult(
        path=path,
        exists=True,
        config=AppConfig(
            status_file=status_file,
            source_of_truth=source_of_truth,
            required_files=required_files,
            footwork_keywords=keywords,
            exclude_paths=exclude_paths,
            status_max_chars=status_max_chars,
            status_max_lines=status_max_lines,
            fixed_input_scope_declared=fixed_input_scope_declared,
            automatic_instruction_files=automatic_instruction_files,
            always_read_files=always_read_files,
            read_when_needed_files=read_when_needed_files,
            reference_files=reference_files,
            fixed_input_target_chars=fixed_input_target_chars,
            fixed_input_target_lines=fixed_input_target_lines,
            fixed_input_high_chars=fixed_input_high_chars,
            fixed_input_high_lines=fixed_input_high_lines,
            fixed_input_exception_reason=fixed_input_exception_reason,
            fixed_input_review_condition=fixed_input_review_condition,
            token_encoding=token_encoding,
            stale_days=stale_days,
            output_dir=output_dir,
            max_priority_actions=max_priority_actions,
        ),
        warnings=warnings,
    )


def _unavailable_config(
    path: Path,
    config: AppConfig,
    warning: str,
) -> ConfigResult:
    return ConfigResult(
        path=path,
        exists=True,
        config=config,
        warnings=[warning],
        load_state="unavailable",
    )


def _load_yaml(raw: str) -> Any:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _load_simple_yaml(raw)

    loaded = yaml.safe_load(raw)
    return {} if loaded is None else loaded


def _load_simple_yaml(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    section: str | None = None
    list_key: str | None = None
    in_block_scalar = False

    for original in raw.splitlines():
        if not original.strip() or original.lstrip().startswith("#"):
            continue

        indent = len(original) - len(original.lstrip(" "))
        line = original.strip()
        if " #" in line:
            line = line.split(" #", 1)[0].rstrip()

        if indent == 0:
            in_block_scalar = False
            if line.endswith(":"):
                section = line[:-1]
                data.setdefault(section, {})
                list_key = None
                continue
            if line.endswith((": |", ": |-", ": >", ": >-")):
                section = None
                list_key = None
                in_block_scalar = True
                continue
            raise ValueError("unsupported top-level YAML syntax")

        if in_block_scalar:
            continue

        if section is None or not isinstance(data.get(section), dict):
            raise ValueError("nested YAML value has no mapping section")

        section_data = data[section]
        if indent == 2 and line.endswith(":"):
            list_key = line[:-1]
            section_data[list_key] = []
            continue

        if indent == 2 and ":" in line:
            key, value = line.split(":", 1)
            section_data[key.strip()] = _parse_scalar(value.strip())
            list_key = None
            continue

        if indent >= 4 and list_key and line.startswith("- "):
            items = section_data.setdefault(list_key, [])
            if isinstance(items, list):
                items.append(_parse_scalar(line[2:].strip()))
                continue

        raise ValueError("unsupported nested YAML syntax")

    return data


def _parse_scalar(value: str) -> Any:
    if value == "":
        return None
    if value.startswith(("[", "{")):
        raise ValueError("inline YAML collections are not supported")
    if value.startswith(("\"", "'")):
        quote = value[0]
        if len(value) < 2 or not value.endswith(quote):
            raise ValueError("unterminated quoted YAML scalar")
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _dict_at(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _string_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or list(default)


def _string_list_allow_empty(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_value(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
