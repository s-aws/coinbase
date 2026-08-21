from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.read_service import AdminApiReadService


DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parent
    / "memory-investigation"
    / "futures-command-suite-serialization-progress.jsonl"
)


def _write_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()


def _container_len(value: object) -> int | None:
    if isinstance(value, (dict, list, tuple, str)):
        return len(value)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe futures command-suite field serialization cost."
    )
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--field", default=None)
    parser.add_argument("--command-fields", action="store_true")
    parser.add_argument("--risk-proof-fields", action="store_true")
    parser.add_argument("--command-index", type=int, default=None)
    parser.add_argument("--risk-proof-index", type=int, default=None)
    args = parser.parse_args()

    if args.log_path.exists():
        args.log_path.unlink()

    started_at = time.perf_counter()
    command_suite = AdminApiReadService().build_futures_command_suite()
    _write_row(
        args.log_path,
        {
            "event": "built",
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "command_count": command_suite.command_count,
        },
    )

    dump_started_at = time.perf_counter()
    payload = command_suite.model_dump(mode="json")
    _write_row(
        args.log_path,
        {
            "event": "dumped",
            "elapsed_seconds": round(time.perf_counter() - dump_started_at, 3),
            "top_level_key_count": len(payload),
        },
    )

    if args.command_fields:
        for command_index, command in enumerate(payload["commands"]):
            for key, value in command.items():
                _write_row(
                    args.log_path,
                    {
                        "event": "start_command_field",
                        "command_index": command_index,
                        "command": command.get("command"),
                        "key": key,
                        "type": type(value).__name__,
                        "len": _container_len(value),
                    },
                )
                field_started_at = time.perf_counter()
                encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
                _write_row(
                    args.log_path,
                    {
                        "event": "done_command_field",
                        "command_index": command_index,
                        "command": command.get("command"),
                        "key": key,
                        "elapsed_seconds": round(
                            time.perf_counter() - field_started_at,
                            3,
                        ),
                        "encoded_bytes": len(encoded),
                    },
                )
        return 0

    if args.risk_proof_fields:
        for command_index, command in enumerate(payload["commands"]):
            if args.command_index is not None and command_index != args.command_index:
                continue
            requirements = command["risk_proof_requirements"]
            for requirement_index, requirement in enumerate(requirements):
                if (
                    args.risk_proof_index is not None
                    and requirement_index != args.risk_proof_index
                ):
                    continue
                for key, value in requirement.items():
                    _write_row(
                        args.log_path,
                        {
                            "event": "start_risk_proof_field",
                            "command_index": command_index,
                            "command": command.get("command"),
                            "requirement_index": requirement_index,
                            "proof_kind": requirement.get("proof_kind"),
                            "key": key,
                            "type": type(value).__name__,
                            "len": _container_len(value),
                        },
                    )
                    field_started_at = time.perf_counter()
                    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
                    _write_row(
                        args.log_path,
                        {
                            "event": "done_risk_proof_field",
                            "command_index": command_index,
                            "command": command.get("command"),
                            "requirement_index": requirement_index,
                            "proof_kind": requirement.get("proof_kind"),
                            "key": key,
                            "elapsed_seconds": round(
                                time.perf_counter() - field_started_at,
                                3,
                            ),
                            "encoded_bytes": len(encoded),
                        },
                    )
        return 0

    keys = [args.field] if args.field else list(payload.keys())
    for key in keys:
        if key not in payload:
            _write_row(args.log_path, {"event": "missing", "key": key})
            continue
        value = payload[key]
        _write_row(
            args.log_path,
            {
                "event": "start_field",
                "key": key,
                "type": type(value).__name__,
                "len": _container_len(value),
            },
        )
        field_started_at = time.perf_counter()
        encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        _write_row(
            args.log_path,
            {
                "event": "done_field",
                "key": key,
                "elapsed_seconds": round(time.perf_counter() - field_started_at, 3),
                "encoded_bytes": len(encoded),
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
