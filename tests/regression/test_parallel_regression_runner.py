import pytest
from pathlib import Path

from tools.run_parallel_regression import (
    SUMMARY_PREFIX,
    build_commands,
    build_parser,
    main,
)


pytestmark = pytest.mark.regression


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
