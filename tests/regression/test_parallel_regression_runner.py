import re
import pytest
from pathlib import Path

from tools.run_parallel_regression import (
    SUMMARY_PREFIX,
    build_commands,
    build_parser,
    main,
)


pytestmark = pytest.mark.regression


REGRESSION_POLICY_DOCS = (
    "AGENTS.md",
    "agent.md",
    "docs/agents/README.md",
    "docs/agents/INVARIANTS.md",
    "docs/agents/AGENT_ADMIN_API_CONTRACT.md",
    "docs/STEALTH_ORDER_READS.md",
    "docs/SPOT_READINESS_TEST_GATE.md",
    "docs/SPOT_READINESS_ROADMAP.md",
    "docs/REPO_CLEANUP_CLASSIFICATION.md",
    "genai_data/AGENT_ARCHITECT.md",
    "genai_data/AGENT_CONSISTENCY_PROTOCOL.md",
    "genai_data/DEBUGGING_STRATEGY.md",
    "genai_data/TESTING_STRATEGY.md",
    "genai_data/CONFIGURATION.md",
    "genai_data/agent_state.md",
    "tests/README.md",
    "tests/DEPLOYMENT_CHECKLIST.md",
    "tests/SETUP_SUMMARY.md",
    "tests/TEST_COVERAGE_SUMMARY.md",
    "tests/TEST_FILES_INDEX.md",
)


def test_regression_policy_docs_make_parallel_runner_canonical():
    root = Path(__file__).resolve().parents[2]
    canonical_command = "python tools/run_parallel_regression.py --workers 4"
    stale_default_markers = (
        "Default full Bash regression command",
        "python3 -m pytest tests/regression/ -v",
    )
    sequential_full_regression = re.compile(
        r"(?:python(?:3)? -m )?pytest tests[\\/]+regression[\\/]* -v(?: --tb=short)?"
    )

    for relative_path in REGRESSION_POLICY_DOCS:
        text = (root / relative_path).read_text(encoding="utf-8")

        assert canonical_command in text, relative_path
        for marker in stale_default_markers:
            assert marker not in text, relative_path

        for match in sequential_full_regression.finditer(text):
            context = text[max(0, match.start() - 160) : match.end() + 160].lower()
            assert "fallback" in context, (
                f"{relative_path} names sequential regression without fallback "
                f"context: {match.group(0)}"
            )


def test_parallel_regression_runner_defaults_to_split_lanes():
    args = build_parser().parse_args([])

    commands = build_commands(args, python="python")

    assert [command.name for command in commands] == [
        "parallel_safe_regression",
        "serial_regression",
    ]
    assert commands[0].command == (
        "python",
        "-m",
        "pytest",
        "tests/regression",
        "-m",
        "not serial",
        "-n",
        "4",
        "--dist",
        "loadfile",
        "--max-worker-restart=0",
    )
    assert commands[1].command == (
        "python",
        "-m",
        "pytest",
        "tests/regression",
        "-m",
        "serial",
    )


def test_parallel_regression_runner_lane_switches():
    parallel_args = build_parser().parse_args(["--parallel-only", "--workers", "2"])
    serial_args = build_parser().parse_args(["--serial-only"])

    assert [command.name for command in build_commands(parallel_args, python="py")] == [
        "parallel_safe_regression",
    ]
    assert build_commands(parallel_args, python="py")[0].command[-3:] == (
        "--dist",
        "loadfile",
        "--max-worker-restart=0",
    )
    assert [command.name for command in build_commands(serial_args, python="py")] == [
        "serial_regression",
    ]


def test_parallel_regression_runner_accepts_per_run_basetemp():
    args = build_parser().parse_args(["--workers", "2"])

    commands = build_commands(args, python="py", run_basetemp=Path("tmp") / "run-1")

    assert commands[0].command[-2:] == ("--basetemp", "tmp\\run-1\\parallel")
    assert commands[1].command[-2:] == ("--basetemp", "tmp\\run-1\\serial")


def test_parallel_regression_runner_dry_run_does_not_require_xdist(capsys):
    exit_code = main(["--dry-run", "--workers", "2"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "parallel_safe_regression:" in captured.out
    assert "-n 2" in captured.out
    assert "serial_regression:" in captured.out
    assert SUMMARY_PREFIX in captured.out
