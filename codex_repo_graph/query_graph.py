#!/usr/bin/env python3
"""Low-token query interface for the generated Codex repository graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


GRAPH_DIR = Path(__file__).resolve().parent
INDEX_DIR = GRAPH_DIR / "index"
SEMANTIC_DIR = GRAPH_DIR / "semantic"


def iter_jsonl(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
                record["_record_file"] = path.relative_to(GRAPH_DIR).as_posix()
                yield record


def all_record_paths() -> list[Path]:
    return sorted(INDEX_DIR.glob("*.jsonl")) + sorted(SEMANTIC_DIR.glob("*.jsonl"))


def emit(records: Iterable[dict[str, Any]], limit: int) -> int:
    count = 0
    for record in records:
        if count >= limit:
            break
        print(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        count += 1
    return count


def search_records(term: str, records: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    needle = term.casefold()
    for record in records:
        if needle in json.dumps(record, sort_keys=True, ensure_ascii=False).casefold():
            yield record


def ranked_matches(
    term: str,
    records: Iterable[dict[str, Any]],
    *,
    exact_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return matches with exact identifiers/names before broad text hits."""
    needle = term.casefold()
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for record in search_records(term, records):
        candidates: list[str] = []
        for field in exact_fields:
            value = record.get(field)
            if isinstance(value, list):
                candidates.extend(str(item).casefold() for item in value)
            elif value is not None:
                candidates.append(str(value).casefold())
        record_id = str(record.get("id", "")).casefold()
        id_tail = record_id.split(":", 1)[-1]
        if needle in candidates or needle == id_tail:
            rank = 0
        elif any(candidate.startswith(needle) for candidate in candidates) or id_tail.startswith(needle):
            rank = 1
        else:
            rank = 2
        ranked.append((rank, record_id, record))
    return [record for _, _, record in sorted(ranked, key=lambda item: (item[0], item[1]))]


def command_search(args: argparse.Namespace) -> int:
    return emit(search_records(args.term, iter_jsonl(all_record_paths())), args.limit)


def command_task(args: argparse.Namespace) -> int:
    records = iter_jsonl([SEMANTIC_DIR / "task_routes.jsonl"])
    return emit(ranked_matches(args.tag, records, exact_fields=("aliases", "tags")), args.limit)


def command_flow(args: argparse.Namespace) -> int:
    records = iter_jsonl([SEMANTIC_DIR / "runtime_flows.jsonl"])
    return emit(ranked_matches(args.name, records, exact_fields=("id", "tags")), args.limit)


def command_symbol(args: argparse.Namespace) -> int:
    records = iter_jsonl([INDEX_DIR / "symbols.jsonl"])
    return emit(ranked_matches(args.name, records, exact_fields=("name", "qualname")), args.limit)


def command_file(args: argparse.Namespace) -> int:
    normalized = args.path.replace("\\", "/")
    selected: list[dict[str, Any]] = []
    file_id = f"f:{normalized}"
    for record in iter_jsonl([
        INDEX_DIR / "files.jsonl",
        INDEX_DIR / "symbols.jsonl",
        INDEX_DIR / "edges.jsonl",
        INDEX_DIR / "tests.jsonl",
    ]):
        if (
            record.get("path") == normalized
            or record.get("source_id") == file_id
            or str(record.get("id", "")).startswith(f"s:{normalized}::")
        ):
            selected.append(record)

    def file_record_rank(record: dict[str, Any]) -> tuple[int, str]:
        record_id = str(record.get("id", ""))
        if record_id == file_id:
            rank = 0
        elif record_id.startswith(f"s:{normalized}::"):
            rank = 1
        elif record_id.startswith("test:"):
            rank = 2
        elif record.get("kind") == "edge":
            rank = 3
        else:
            rank = 4
        return rank, record_id

    return emit(sorted(selected, key=file_record_rank), args.limit)


def command_neighbors(args: argparse.Namespace) -> int:
    selected: list[dict[str, Any]] = []
    for edge in iter_jsonl([INDEX_DIR / "edges.jsonl"]):
        if args.edge_kind and edge.get("edge_kind") != args.edge_kind:
            continue
        outbound = edge.get("source_id") == args.node_id
        inbound = edge.get("target_id") == args.node_id
        if args.direction == "out" and outbound:
            selected.append(edge)
        elif args.direction == "in" and inbound:
            selected.append(edge)
        elif args.direction == "both" and (outbound or inbound):
            selected.append(edge)
    return emit(selected, args.limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_limit(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--limit", type=int, default=100)

    search = subparsers.add_parser("search")
    search.add_argument("term")
    add_limit(search)
    search.set_defaults(func=command_search)

    task = subparsers.add_parser("task")
    task.add_argument("tag")
    add_limit(task)
    task.set_defaults(func=command_task)

    flow = subparsers.add_parser("flow")
    flow.add_argument("name")
    add_limit(flow)
    flow.set_defaults(func=command_flow)

    symbol = subparsers.add_parser("symbol")
    symbol.add_argument("name")
    add_limit(symbol)
    symbol.set_defaults(func=command_symbol)

    file_query = subparsers.add_parser("file")
    file_query.add_argument("path")
    add_limit(file_query)
    file_query.set_defaults(func=command_file)

    neighbors = subparsers.add_parser("neighbors")
    neighbors.add_argument("node_id")
    neighbors.add_argument("--edge-kind")
    neighbors.add_argument("--direction", choices=("in", "out", "both"), default="both")
    add_limit(neighbors)
    neighbors.set_defaults(func=command_neighbors)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    count = args.func(args)
    if count == 0:
        print(json.dumps({"result": "no_match"}, separators=(",", ":")))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
