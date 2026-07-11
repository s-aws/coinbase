"""Classify repository files for cleanup planning without moving anything."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Classification:
    path: str
    category: str
    action: str
    reason: str


PACKAGE_DIRS = {
    "bridges",
    "business",
    "calculation",
    "core",
    "data",
    "database",
    "external",
    "integration",
    "market_intel",
    "websocket",
}

ROOT_RUNTIME_ENTRYPOINTS = {
    "main.py",
    "dashboard_server.py",
    "configuration.py",
    "order.py",
    "logging_service.py",
    "engine_console.py",
    "ui_console.py",
}

ROOT_CONFIG = {
    ".gitattributes",
    ".gitignore",
    ".vscode/settings.json",
    "pyproject.toml",
    "products.json",
}

PUBLIC_AGENT_FILES = {
    "AGENTS.md",
    "agent.md",
    "ai-context.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "tools/check_ownership.py",
    "tools/classify_repo_files.py",
}

EXPERIMENTAL_UI_PATTERNS = [
    "*investor_dashboard.html",
    "bounce_arc_dashboard.html",
    "sample.html",
    "ui_codex.html",
    "ui_chart.html",
]

ZERO_BYTE_UI_FILES = {
    "App.css",
    "App.js",
    "Dashboard.css",
    "Dashboard.js",
    "TradeChart.css",
    "TradeChart.js",
    "index.css",
    "index.js",
}

DIAGNOSTIC_PATTERNS = [
    "check_*.py",
    "audit_*.py",
    "verify_tables.py",
    "debug_*.py",
    "demo_*.py",
    "main_place_order.py",
    "cli_parent_child_orders.py",
    "__dangerous_delete_all_tables__.py",
]

HISTORICAL_MD_PATTERNS = [
    "*_COMPLETE.md",
    "*_FIX*.md",
    "*_ANALYSIS*.md",
    "*_SUMMARY.md",
    "PARTIAL_FILLS*.md",
    "WEBSOCKET_*.md",
    "EXCEPTIONS_IMPLEMENTATION.md",
    "DATABASE_AUDIT_ROOT_CAUSE_FIXES.md",
    "DEADLOCK_EXECUTIVE_SUMMARY.md",
    "RACE_CONDITIONS_ANALYSIS_COMPLETE.md",
    "ID_USAGE_ANALYSIS.md",
    "COMPREHENSIVE_TEST_SUITE_CREATED.md",
]


def _run_git(args: List[str]) -> List[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def repo_files(include_untracked: bool = True) -> List[str]:
    seen = set()
    files: List[str] = []
    commands = [["ls-files"]]
    if include_untracked:
        commands.append(["ls-files", "--others", "--exclude-standard"])
    for command in commands:
        for path in _run_git(command):
            if not (ROOT / path).exists():
                continue
            if path not in seen:
                seen.add(path)
                files.append(path)
    return sorted(files)


def _match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify(path: str) -> Classification:
    path = path.replace("\\", "/")
    parts = path.split("/")
    name = parts[-1]
    first = parts[0]

    if path.startswith("docs/agents/") or path.startswith(".agents/") or path in PUBLIC_AGENT_FILES:
        return Classification(path, "public_agent_contract", "keep_tracked", "public owner/context contract")

    if path == "docs/PUBLIC_ROADMAP.md":
        return Classification(path, "public_roadmap", "keep_tracked", "public feature planning")

    if path.startswith(".github/"):
        return Classification(path, "public_ci_metadata", "keep_tracked", "public CI or repository template")

    if path.startswith("genai_data/"):
        return Classification(path, "local_expanded_context", "keep_ignored", "local expanded agent context")

    if path.startswith("genai_tools/"):
        return Classification(path, "local_diagnostics", "keep_ignored_or_promote", "local scratch diagnostics")

    if first in PACKAGE_DIRS:
        return Classification(path, "package_code", "keep_in_place", "importable package module")

    if path.startswith("tests/"):
        return Classification(path, "public_tests", "keep_in_place", "public test suite")

    if path.startswith("api_reference/") or path.startswith("websocket_reference/"):
        return Classification(path, "public_reference_payloads", "keep_in_place", "public API/websocket references")

    if path.startswith("docs/archive/"):
        return Classification(path, "public_archive", "keep_in_archive", "archived public artifact")

    if path.startswith("docs/"):
        return Classification(path, "public_docs", "keep_in_docs", "tracked public documentation")

    if path.startswith("tools/diagnostics/"):
        return Classification(path, "public_diagnostic_tool", "keep_in_tools", "tracked diagnostic or operational script")

    if path.startswith("tools/"):
        return Classification(path, "public_tooling", "keep_in_tools", "tracked public tooling")

    if path.startswith("ui_order_span/"):
        return Classification(path, "ui_fixture_or_export_candidate", "review_then_move_or_ignore", "UI input/export artifact")

    if path in ROOT_RUNTIME_ENTRYPOINTS:
        return Classification(path, "root_runtime_entrypoint", "keep_until_refactor", "active root runtime entrypoint")

    if path in ROOT_CONFIG:
        return Classification(path, "root_config", "keep_in_place", "root repository or runtime config")

    if name.startswith("test_") and name.endswith(".py") and "/" not in path:
        return Classification(path, "root_test_candidate", "move_to_tests_or_archive", "root-level test file outside tests/")

    if _match_any(path, DIAGNOSTIC_PATTERNS) and "/" not in path:
        return Classification(path, "root_diagnostic_tool", "move_to_tools_diagnostics", "root diagnostic or operational script")

    if _match_any(path, HISTORICAL_MD_PATTERNS) and "/" not in path:
        return Classification(path, "root_historical_note", "move_to_docs_archive", "historical incident or implementation note")

    if _match_any(path, EXPERIMENTAL_UI_PATTERNS) and "/" not in path:
        return Classification(path, "experimental_ui_candidate", "move_to_docs_or_web_archive", "one-off or experimental UI artifact")

    if path in ZERO_BYTE_UI_FILES:
        return Classification(path, "empty_artifact_candidate", "delete_after_confirmation", "zero-byte UI artifact")

    if "/" not in path and name.endswith((".log", ".txt")):
        return Classification(path, "root_runtime_output", "stop_tracking_or_keep_ignored", "runtime output artifact")

    if path.startswith("."):
        return Classification(path, "root_hidden_config", "review", "root hidden config")

    if "/" not in path and name.endswith((".html", ".js", ".css")):
        return Classification(path, "root_ui_candidate", "review_ui_ownership", "root UI asset")

    return Classification(path, "unclassified_review", "review", "no cleanup rule matched")


def _render_markdown(items: List[Classification]) -> str:
    by_category: Dict[str, List[Classification]] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)

    lines = ["# Repo File Classification", ""]
    counts = Counter(item.category for item in items)
    lines.append("| Category | Count |")
    lines.append("| --- | ---: |")
    for category, count in sorted(counts.items()):
        lines.append(f"| `{category}` | {count} |")
    lines.append("")

    for category in sorted(by_category):
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Path | Action | Reason |")
        lines.append("| --- | --- | --- |")
        for item in sorted(by_category[category], key=lambda value: value.path):
            lines.append(f"| `{item.path}` | `{item.action}` | {item.reason} |")
        lines.append("")
    return "\n".join(lines)


def _render_text(items: List[Classification]) -> str:
    return "\n".join(
        f"{item.category}\t{item.action}\t{item.path}\t{item.reason}"
        for item in sorted(items, key=lambda value: (value.category, value.path))
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Optional explicit files to classify")
    parser.add_argument("--category", help="Only print one category")
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Ignore untracked files when scanning the repo",
    )
    parser.add_argument(
        "--fail-category",
        action="append",
        default=[],
        help="Return a failure if any file is classified into this category",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print disallowed files when used with --fail-category",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [path.replace("\\", "/") for path in args.files] if args.files else repo_files(not args.tracked_only)
    items = [classify(path) for path in paths]
    if args.category:
        items = [item for item in items if item.category == args.category]
    failed_items = [item for item in items if item.category in set(args.fail_category)]

    if not args.quiet:
        if args.format == "json":
            print(json.dumps([asdict(item) for item in items], indent=2, sort_keys=True))
        elif args.format == "markdown":
            print(_render_markdown(items))
        else:
            print(_render_text(items))

    if failed_items:
        for item in failed_items:
            print(
                f"DISALLOWED {item.category}\t{item.path}\t{item.action}",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
