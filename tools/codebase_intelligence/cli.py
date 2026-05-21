"""Command line entry point for the codebase-intelligence layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional

from tools.codebase_intelligence.indexer import build_repository_index
from tools.codebase_intelligence.models import RepositoryIndex
from tools.codebase_intelligence.registry import ToolRegistry, generate_callable_binding_specs


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Generate a static symbol index")
    index_parser.add_argument("--root", default=".", help="Repository root")
    index_parser.add_argument("--output", required=True, help="Output JSON path")
    index_parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Index only Python files tracked by git",
    )

    find_parser = subparsers.add_parser("find", help="Find relevant modules")
    find_parser.add_argument("--index", required=True, help="Index JSON path")
    find_parser.add_argument("query")
    find_parser.add_argument("--limit", type=int, default=10)

    tools_parser = subparsers.add_parser("tools", help="List registry tools")
    tools_parser.add_argument("--index", required=True, help="Index JSON path")
    tools_parser.add_argument("--allowlist", nargs="*", default=[])

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "index":
        index = build_repository_index(args.root, tracked_only=args.tracked_only)
        index.save(args.output)
        print(f"wrote {len(index.files)} files and {len(index.symbols)} symbols to {args.output}")
        return 0

    if args.command == "find":
        index = RepositoryIndex.load(args.index)
        registry = ToolRegistry(index)
        result = registry.call_tool("find_relevant_modules", query=args.query, limit=args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "tools":
        index = RepositoryIndex.load(args.index)
        registry = ToolRegistry(index, executable_allowlist=args.allowlist)
        specs = registry.list_tools()
        specs.extend(generate_callable_binding_specs(index, allowlist=args.allowlist))
        print(json.dumps([spec.__dict__ for spec in specs], indent=2, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
