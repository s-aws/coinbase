from __future__ import annotations

import ast
import json
from pathlib import Path

from tools import run_admin_api_futures_r9_slice3_end_to_end as retired_r9


def test_consumed_r9_end_to_end_entrypoint_is_permanently_retired(
    capsys,
) -> None:
    assert retired_r9.R9_SLICE3_END_TO_END_READY is False

    assert retired_r9.main(["--confirm-one-r9-preview-and-slice3"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary == {
        "status": "blocked",
        "blocker": "futures_r9_slice3_permanently_retired",
        "workflow_ready": False,
        "artifact_created": False,
        "coinbase_client_constructed": False,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "slice3_exchange_mutation_attempt_count": 0,
    }


def test_consumed_r9_tombstone_imports_only_standard_library() -> None:
    source_path = Path(retired_r9.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots == {"__future__", "json", "sys", "typing"}
    assert "application" not in source_path.read_text(encoding="utf-8")
