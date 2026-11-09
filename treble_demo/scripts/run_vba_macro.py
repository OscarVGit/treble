#!/usr/bin/env python3
"""Mock Excel/VBA macro runner for the Treble "Old Way vs. Treble Way" demo.

This is a simulation. It never opens Excel, touches a real workbook, or writes
report artifacts. It exists to show how many brittle flags a legacy report
runner can demand -- and how Treble collapses that invocation into intent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_vba_macro.py",
        description="Execute a weekly-report Excel/VBA macro.",
        allow_abbrev=False,
        epilog=(
            "Example: python3 scripts/run_vba_macro.py "
            "--config-path config/weekly_report.json "
            "--target-date 2026-11-05 "
            "--macro-name ThursdayWeeklyReport "
            "--output-dir output/2026-11-05 "
            "--verbose"
        ),
    )
    parser.add_argument(
        "--config-path",
        required=True,
        metavar="FILE",
        help="Path to the weekly-report configuration JSON.",
    )
    parser.add_argument(
        "--target-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Report date to process.",
    )
    parser.add_argument(
        "--macro-name",
        required=True,
        metavar="NAME",
        help="VBA macro to execute in the workbook.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory for generated report artifacts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        required=True,
        help="Enable verbose logging (yes, this flag is required too).",
    )
    return parser


def _load_config(
    parser: argparse.ArgumentParser, raw_path: str
) -> tuple[Path, dict[str, Any]]:
    path = Path(raw_path).expanduser()
    if not path.is_file():
        parser.error(f"--config-path does not point to a file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        parser.error(f"--config-path is not valid JSON: {path} ({exc})")
    if not isinstance(data, dict):
        parser.error(f"--config-path must contain a JSON object: {path}")
    return path, data


def _log(level: str, message: str, *, clock: str) -> None:
    print(f"[{level}] {clock} {message}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path, config = _load_config(parser, args.config_path)

    try:
        target_date = dt.date.fromisoformat(args.target_date)
    except ValueError:
        parser.error(
            f"--target-date must be an ISO date (YYYY-MM-DD), got "
            f"{args.target_date!r}"
        )

    if not args.macro_name.strip():
        parser.error("--macro-name must not be empty")

    output_dir = Path(args.output_dir).expanduser()
    clock = dt.datetime.now().strftime("%H:%M:%S")
    workbook = config.get("workbook", "Weekly_Report.xlsm")
    worksheet = config.get("worksheet", "WeeklyData")
    profile = config.get("profile", "weekly-report-production")
    regions = config.get("regions", [])

    _log("INFO", f"Loading configuration: {config_path}", clock=clock)
    _log("INFO", f"Workbook profile: {profile}", clock=clock)
    _log("INFO", f"Workbook: {workbook} (sheet: {worksheet})", clock=clock)
    _log(
        "INFO",
        f"Target report date: {target_date.isoformat()} "
        f"({target_date.strftime('%A')})",
        clock=clock,
    )
    _log("INFO", f"Output directory: {output_dir}", clock=clock)

    if args.verbose:
        _log(
            "DEBUG",
            "Resolved required flags: --config-path --target-date "
            "--macro-name --output-dir --verbose",
            clock=clock,
        )
        if regions:
            _log(
                "DEBUG",
                f"Region scope: {len(regions)} regions ({', '.join(map(str, regions))})",
                clock=clock,
            )

    _log("INFO", "Opening workbook in Excel", clock=clock)
    _log("INFO", "Application.ScreenUpdating = False", clock=clock)
    _log("INFO", f"Running macro: {args.macro_name}", clock=clock)
    _log("INFO", "Refreshing Power Query connections...", clock=clock)
    _log("INFO", "Processing weekly report rows: 1,248 rows across 6 regions", clock=clock)
    _log("INFO", "Building summary tables and charts", clock=clock)
    _log("INFO", "Application.ScreenUpdating = True", clock=clock)
    _log("INFO", f"Report saved to: {output_dir}", clock=clock)
    print(f"[SUCCESS] Macro '{args.macro_name}' executed in 1.4s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
