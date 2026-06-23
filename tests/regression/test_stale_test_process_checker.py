import json
from pathlib import Path

import pytest

from tools.check_stale_test_processes import (
    SUMMARY_PREFIX,
    ProcessInfo,
    find_stale_test_processes,
    is_test_process,
    parse_process_json,
)


pytestmark = pytest.mark.regression


def _process(
    *,
    name: str = "node.exe",
    process_id: int = 100,
    age_seconds: int | None = 1200,
    command_line: str,
) -> ProcessInfo:
    return ProcessInfo(
        name=name,
        process_id=process_id,
        parent_process_id=10,
        age_seconds=age_seconds,
        working_set_mb=512.0,
        command_line=command_line,
    )


def test_stale_checker_matches_only_repo_owned_test_processes():
    repo = Path("C:/coinbase-frontend")
    vitest = _process(
        command_line=(
            "C:/nvm4w/nodejs/node.exe "
            "C:/coinbase-frontend/node_modules/vitest/vitest.mjs run"
        )
    )
    codex_mcp = _process(command_line="C:/nvm4w/nodejs/node.exe ./mcp/server.mjs --stdio")
    unrelated_pytest = _process(
        name="python.exe",
        command_line="python -m pytest D:/other-project/tests",
    )

    assert is_test_process(vitest, [repo])
    assert not is_test_process(codex_mcp, [repo])
    assert not is_test_process(unrelated_pytest, [repo])


def test_stale_checker_respects_age_threshold():
    repo = Path("C:/coinbase")
    old_pytest = _process(
        name="python.exe",
        process_id=101,
        age_seconds=901,
        command_line="C:/Python314/python.exe -m pytest C:/coinbase/tests/regression",
    )
    young_pytest = _process(
        name="python.exe",
        process_id=102,
        age_seconds=10,
        command_line="C:/Python314/python.exe -m pytest C:/coinbase/tests/regression",
    )

    assert find_stale_test_processes(
        [old_pytest, young_pytest],
        roots=[repo],
        min_age_seconds=900,
    ) == [old_pytest]


def test_parse_process_json_accepts_single_or_list_payload():
    single = parse_process_json(
        json.dumps(
            {
                "Name": "python.exe",
                "ProcessId": 123,
                "ParentProcessId": 12,
                "AgeSeconds": 1200,
                "WorkingSetMB": 64.5,
                "CommandLine": "python -m pytest C:/coinbase/tests/regression",
            }
        )
    )
    multiple = parse_process_json(
        json.dumps(
            [
                {
                    "Name": "node.exe",
                    "ProcessId": 124,
                    "ParentProcessId": 12,
                    "AgeSeconds": None,
                    "WorkingSetMB": 128,
                    "CommandLine": "node C:/coinbase-frontend/node_modules/vitest/vitest.mjs",
                }
            ]
        )
    )

    assert single[0].process_id == 123
    assert single[0].working_set_mb == 64.5
    assert multiple[0].age_seconds is None
    assert multiple[0].process_id == 124


def test_summary_prefix_is_machine_readable_contract():
    assert SUMMARY_PREFIX == "STALE_TEST_PROCESS_SUMMARY "
