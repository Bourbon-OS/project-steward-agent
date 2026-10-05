from __future__ import annotations

import argparse
import sys
from datetime import date
from itertools import count
from pathlib import Path

from .followups import (
    FollowupInputError,
    build_followups_report,
    select_followups,
)
from .handoff import (
    HandoffInputError,
    build_handoff_text,
    collect_handoff_observation,
)
from .report import build_markdown_report
from .scan import scan_path


EXIT_SCAN_COMPLETED = 0
EXIT_COMMAND_ERROR = 1
EXIT_REPORT_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return run_scan(args)
    if args.command == "followups":
        return run_followups(args)
    if args.command == "handoff":
        return run_handoff(args)

    parser.print_help()
    return EXIT_COMMAND_ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pma",
        description=(
            "Project Memory Anchor: observe and report anchor points for a "
            "project's operational memory."
        ),
        epilog=(
            "Read-only by default. pma does not repair project records, commit, "
            "or notify; scan writes a report only when --save-report is requested."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="Run a read-only footwork scan.")
    scan_parser.add_argument(
        "--path",
        default=".",
        help="Path to the local project or a path inside it. Defaults to current directory.",
    )
    scan_parser.add_argument(
        "--save-report",
        action="store_true",
        help="Save the Markdown report under reports/footwork_review_YYYY-MM-DD.md.",
    )

    followups_parser = subparsers.add_parser(
        "followups",
        help="Select current follow-up signals from an explicit parent list.",
    )
    followups_parser.add_argument(
        "--list",
        dest="list_path",
        required=True,
        help="Path to the existing private Markdown parent list.",
    )
    followups_parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        help="Date used for due checks in YYYY-MM-DD form. Defaults to today.",
    )

    handoff_parser = subparsers.add_parser(
        "handoff",
        help="Build a read-only, shallow Caddie handoff observation.",
    )
    handoff_parser.add_argument(
        "--path",
        default=".",
        help=(
            "Path to the local project or a path inside it. "
            "Defaults to current directory."
        ),
    )
    handoff_parser.add_argument(
        "--project",
        required=True,
        help="Owner-side project identifier to include in the observation.",
    )
    handoff_parser.add_argument(
        "--trigger",
        choices=("manual", "event-driven", "timing-driven"),
        required=True,
        help="Reason the observation is being handed off.",
    )

    return parser


def run_scan(args: argparse.Namespace) -> int:
    result = scan_path(Path(args.path))

    if args.save_report:
        try:
            saved_path, markdown = _save_report(result)
        except (OSError, ValueError) as exc:
            print(f"レポートを保存できませんでした: {exc}", file=sys.stderr)
            return EXIT_REPORT_ERROR
    else:
        markdown = build_markdown_report(result)

    print(markdown)
    return EXIT_SCAN_COMPLETED


def run_followups(args: argparse.Namespace) -> int:
    as_of = args.as_of or date.today()
    try:
        items = select_followups(Path(args.list_path), as_of)
        report = build_followups_report(items, as_of)
    except FollowupInputError as exc:
        print(f"follow-up候補を選別できませんでした: {exc}", file=sys.stderr)
        return EXIT_COMMAND_ERROR
    except ValueError:
        print(
            "再確認候補に対応する提案を安全に作成できませんでした。",
            file=sys.stderr,
        )
        return EXIT_COMMAND_ERROR

    print(report, end="")
    return EXIT_SCAN_COMPLETED


def run_handoff(args: argparse.Namespace) -> int:
    try:
        observation = collect_handoff_observation(
            Path(args.path),
            args.project,
            args.trigger,
        )
    except HandoffInputError as exc:
        print(f"handoff観測を作成できませんでした: {exc}", file=sys.stderr)
        return EXIT_COMMAND_ERROR
    except OSError:
        print(
            "handoff観測を作成できませんでした: 入力を安全に確認できませんでした。",
            file=sys.stderr,
        )
        return EXIT_COMMAND_ERROR

    print(build_handoff_text(observation), end="")
    return EXIT_SCAN_COMPLETED


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--as-of は YYYY-MM-DD で指定してください。"
        ) from exc


def _save_report(result) -> tuple[Path, str]:
    if result.config_result.load_state == "unavailable":
        raise ValueError(
            "設定ファイルを安全に使えないため、保存先を推測せず標準出力だけを使用します。"
        )

    project_root = result.project_path.resolve()
    configured = Path(result.config_result.config.output_dir)
    output_dir = (
        configured.resolve()
        if configured.is_absolute()
        else (project_root / configured).resolve()
    )
    if not output_dir.is_relative_to(project_root):
        raise ValueError("保存先がプロジェクト外を指しています。")

    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_output_dir = output_dir.resolve()
    if not resolved_output_dir.is_relative_to(project_root):
        raise ValueError("保存先がプロジェクト外を指しています。")

    report_date = date.today().isoformat()
    for index in count(1):
        suffix = "" if index == 1 else f"_{index}"
        saved_path = resolved_output_dir / f"footwork_review_{report_date}{suffix}.md"
        markdown = build_markdown_report(result, saved_path=saved_path)
        try:
            with saved_path.open("x", encoding="utf-8") as handle:
                handle.write(markdown)
        except FileExistsError:
            continue
        return saved_path, markdown

    raise RuntimeError("レポート保存先を確保できませんでした。")
