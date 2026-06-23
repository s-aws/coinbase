import re
import json
import pytest
from pathlib import Path

from tools.run_parallel_regression import (
    DEFAULT_MAX_COMMIT_GB,
    MEMORY_ABORT_EXIT_CODE,
    PYTEST_TRACEBACK_STYLE,
    SERIAL_SAFE_COMMENT,
    SUMMARY_PREFIX,
    MemorySnapshot,
    ProcessMemorySnapshot,
    RegressionCommand,
    RegressionRunResult,
    build_commands,
    build_parser,
    find_serial_classification_findings,
    main,
    run_regression_command,
)


pytestmark = pytest.mark.regression


REGRESSION_POLICY_DOCS = (
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/public-agent-checks.yml",
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

PRIMARY_REGRESSION_POLICY_DOCS = (
    "README.md",
    "AGENTS.md",
    "agent.md",
    "docs/agents/README.md",
    "docs/agents/INVARIANTS.md",
    "docs/agents/AGENT_ADMIN_API_CONTRACT.md",
    "tests/README.md",
    "tests/DEPLOYMENT_CHECKLIST.md",
)

REQUIRED_FULL_REGRESSION_TRIGGERS = (
    "durable milestone closeout",
    "public/release-candidate handoff",
    "deployment approval/closeout",
    "release-hardening closeout",
    "Admin API/backend association closeout",
    "explicit user request",
)


def test_regression_policy_docs_make_parallel_runner_canonical():
    root = Path(__file__).resolve().parents[2]
    canonical_command = "python tools/run_parallel_regression.py --workers 4"
    stale_default_markers = (
        "Default full Bash regression command",
        "python3 -m pytest tests/regression/ -v",
        "Regression suite passes.",
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


def test_primary_regression_policy_docs_name_required_closeout_triggers():
    root = Path(__file__).resolve().parents[2]

    for relative_path in PRIMARY_REGRESSION_POLICY_DOCS:
        text = (root / relative_path).read_text(encoding="utf-8")
        normalized_text = " ".join(text.split())
        for trigger in REQUIRED_FULL_REGRESSION_TRIGGERS:
            assert trigger in normalized_text, (
                f"{relative_path} missing full regression trigger: {trigger}"
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
        f"--tb={PYTEST_TRACEBACK_STYLE}",
    )
    assert commands[1].command == (
        "python",
        "-m",
        "pytest",
        "tests/regression",
        "-m",
        "serial",
        f"--tb={PYTEST_TRACEBACK_STYLE}",
    )


def test_parallel_regression_runner_lane_switches():
    parallel_args = build_parser().parse_args(["--parallel-only", "--workers", "2"])
    serial_args = build_parser().parse_args(["--serial-only"])

    assert [command.name for command in build_commands(parallel_args, python="py")] == [
        "parallel_safe_regression",
    ]
    assert build_commands(parallel_args, python="py")[0].command[-2:] == (
        "--max-worker-restart=0",
        f"--tb={PYTEST_TRACEBACK_STYLE}",
    )
    assert [command.name for command in build_commands(serial_args, python="py")] == [
        "serial_regression",
    ]


def test_parallel_regression_runner_rejects_unbounded_worker_counts():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--workers", "auto"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--workers", "5"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--max-commit-percent", "101"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--max-commit-gb", "0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--max-physical-percent", "101"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--min-available-physical-gb", "0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--memory-sample-seconds", "0"])


def test_parallel_regression_runner_defaults_to_bounded_memory_watch():
    args = build_parser().parse_args([])

    assert args.disable_memory_watch is False
    assert args.max_commit_gb == DEFAULT_MAX_COMMIT_GB
    assert args.max_commit_percent == 85.0
    assert args.max_physical_percent == 75.0
    assert args.min_available_physical_gb == 24.0
    assert args.memory_sample_seconds == 5


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


def test_serial_classification_detects_default_db_cursor_without_marker(tmp_path):
    test_file = tmp_path / "test_needs_serial.py"
    test_file.write_text(
        "\n".join(
            [
                "from database.database import PostgresDB",
                "",
                "def test_cursor_path():",
                "    db = PostgresDB()",
                "    with db.get_cursor():",
                "        pass",
            ]
        ),
        encoding="utf-8",
    )

    findings = find_serial_classification_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == test_file
    assert "default PostgresDB cursor" in findings[0].reason


def test_serial_classification_detects_full_fastapi_app_import_without_marker(
    tmp_path,
):
    test_file = tmp_path / "test_imports_app.py"
    test_file.write_text(
        "\n".join(
            [
                "from api.v1.app import create_app",
                "",
                "def test_app_factory():",
                "    assert create_app",
            ]
        ),
        encoding="utf-8",
    )

    findings = find_serial_classification_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == test_file
    assert "FastAPI app/route graph" in findings[0].reason


def test_serial_classification_accepts_serial_marker(tmp_path):
    test_file = tmp_path / "test_serial_marker.py"
    test_file.write_text(
        "\n".join(
            [
                "import pytest",
                "from database.database import PostgresDB",
                "",
                "pytestmark = [pytest.mark.regression, pytest.mark.serial]",
                "",
                "def test_cursor_path():",
                "    db = PostgresDB()",
                "    with db.get_cursor():",
                "        pass",
            ]
        ),
        encoding="utf-8",
    )

    assert find_serial_classification_findings(tmp_path) == []


def test_serial_classification_accepts_documented_safe_comment(tmp_path):
    test_file = tmp_path / "test_documented_safe.py"
    test_file.write_text(
        "\n".join(
            [
                f"# {SERIAL_SAFE_COMMENT}: binds only an ephemeral mock socket.",
                "import socket",
                "",
                "def test_ephemeral_socket():",
                "    sock = socket.socket()",
                "    sock.bind(('127.0.0.1', 0))",
            ]
        ),
        encoding="utf-8",
    )

    assert find_serial_classification_findings(tmp_path) == []


def test_parallel_regression_runner_creates_lane_basetemp_dirs(
    monkeypatch, tmp_path, capsys
):
    seen_basetemps = []
    peak = MemorySnapshot(
        commit_used_gb=47.0,
        commit_limit_gb=128.0,
        commit_percent=36.72,
        total_physical_gb=128.0,
        used_physical_gb=39.0,
        physical_percent=30.47,
        available_physical_gb=89.0,
    )

    def fake_run_regression_command(command, **kwargs):
        basetemp = Path(command.command[command.command.index("--basetemp") + 1])
        assert basetemp.exists()
        seen_basetemps.append(basetemp)
        assert kwargs["memory_sample_seconds"] == 5
        assert kwargs["max_commit_gb"] == DEFAULT_MAX_COMMIT_GB
        return RegressionRunResult(returncode=0, peak_memory_snapshot=peak)

    monkeypatch.setattr(
        "tools.run_parallel_regression.is_xdist_available", lambda: True
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.run_regression_command",
        fake_run_regression_command,
    )

    exit_code = main(
        [
            "--workers",
            "2",
            "--basetemp-root",
            str(tmp_path / "parallel-regression"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(seen_basetemps) == 2
    assert {path.name for path in seen_basetemps} == {"parallel", "serial"}
    assert SUMMARY_PREFIX in captured.out
    summary_line = next(
        line for line in captured.out.splitlines() if line.startswith(SUMMARY_PREFIX)
    )
    summary = json.loads(summary_line.removeprefix(SUMMARY_PREFIX))
    assert summary["max_commit_gb"] == DEFAULT_MAX_COMMIT_GB
    assert summary["memory_peak_snapshots"] == [
        {
            "available_physical_gb": 89.0,
            "command": "parallel_safe_regression",
            "commit_limit_gb": 128.0,
            "commit_percent": 36.72,
            "commit_used_gb": 47.0,
            "physical_percent": 30.47,
            "total_physical_gb": 128.0,
            "used_physical_gb": 39.0,
        },
        {
            "available_physical_gb": 89.0,
            "command": "serial_regression",
            "commit_limit_gb": 128.0,
            "commit_percent": 36.72,
            "commit_used_gb": 47.0,
            "physical_percent": 30.47,
            "total_physical_gb": 128.0,
            "used_physical_gb": 39.0,
        },
    ]


def test_run_regression_command_aborts_on_memory_pressure(monkeypatch, capsys):
    terminated = []
    process_snapshots = (
        ProcessMemorySnapshot(
            process_id=4321,
            parent_process_id=1234,
            name="python.exe",
            private_mb=8192.0,
            working_set_mb=4096.0,
            command_line="python -m pytest tests/regression",
        ),
    )

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

    monkeypatch.setattr(
        "tools.run_parallel_regression.subprocess.Popen",
        lambda _command: FakeProcess(),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.read_system_memory_snapshot",
        lambda: MemorySnapshot(
            commit_used_gb=90.0,
            commit_limit_gb=100.0,
            commit_percent=90.0,
            total_physical_gb=128.0,
            used_physical_gb=120.0,
            physical_percent=93.75,
            available_physical_gb=8.0,
        ),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression._terminate_process_tree",
        lambda process: terminated.append(process.pid),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.read_top_process_memory_snapshots",
        lambda: process_snapshots,
    )
    monkeypatch.setattr("tools.run_parallel_regression.time.sleep", lambda _seconds: None)

    result = run_regression_command(
        RegressionCommand("probe", ("python", "-m", "pytest")),
        memory_watch_enabled=True,
        memory_sample_seconds=5,
        max_commit_gb=96.0,
        max_commit_percent=85.0,
        max_physical_percent=75.0,
        min_available_physical_gb=24.0,
    )

    captured = capsys.readouterr()
    assert result.returncode == MEMORY_ABORT_EXIT_CODE
    assert terminated == [1234]
    assert "Memory guard aborting probe" in captured.err
    assert "max_commit_gb=96.00" in captured.err
    assert result.peak_memory_snapshot is not None
    assert result.peak_memory_snapshot.commit_used_gb == 90.0
    assert result.process_memory_snapshots == process_snapshots


def test_run_regression_command_aborts_on_absolute_commit_pressure(
    monkeypatch, capsys
):
    terminated = []

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

    monkeypatch.setattr(
        "tools.run_parallel_regression.subprocess.Popen",
        lambda _command: FakeProcess(),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.read_system_memory_snapshot",
        lambda: MemorySnapshot(
            commit_used_gb=97.0,
            commit_limit_gb=180.0,
            commit_percent=53.89,
            total_physical_gb=128.0,
            used_physical_gb=60.0,
            physical_percent=46.88,
            available_physical_gb=68.0,
        ),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression._terminate_process_tree",
        lambda process: terminated.append(process.pid),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.read_top_process_memory_snapshots",
        lambda: (),
    )
    monkeypatch.setattr("tools.run_parallel_regression.time.sleep", lambda _seconds: None)

    result = run_regression_command(
        RegressionCommand("probe", ("python", "-m", "pytest")),
        memory_watch_enabled=True,
        memory_sample_seconds=5,
        max_commit_gb=96.0,
        max_commit_percent=85.0,
        max_physical_percent=75.0,
        min_available_physical_gb=24.0,
    )

    captured = capsys.readouterr()
    assert result.returncode == MEMORY_ABORT_EXIT_CODE
    assert terminated == [1234]
    assert "commit=97.00GiB/180.00GiB (53.89%)" in captured.err


def test_run_regression_command_reports_peak_memory_without_abort(monkeypatch):
    poll_results = iter([None, None, 0])
    monotonic_values = [0.0, 0.0, 0.0, 6.0, 6.0]
    samples = iter(
        [
            MemorySnapshot(
                commit_used_gb=45.0,
                commit_limit_gb=180.0,
                commit_percent=25.0,
                total_physical_gb=128.0,
                used_physical_gb=36.0,
                physical_percent=28.13,
                available_physical_gb=92.0,
            ),
            MemorySnapshot(
                commit_used_gb=48.5,
                commit_limit_gb=180.0,
                commit_percent=26.94,
                total_physical_gb=128.0,
                used_physical_gb=39.0,
                physical_percent=30.47,
                available_physical_gb=89.0,
            ),
        ]
    )

    class FakeProcess:
        pid = 1234

        def poll(self):
            return next(poll_results)

    monkeypatch.setattr(
        "tools.run_parallel_regression.subprocess.Popen",
        lambda _command: FakeProcess(),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.read_system_memory_snapshot",
        lambda: next(samples),
    )
    monkeypatch.setattr(
        "tools.run_parallel_regression.time.monotonic",
        lambda: monotonic_values.pop(0) if monotonic_values else 6.0,
    )
    monkeypatch.setattr("tools.run_parallel_regression.time.sleep", lambda _seconds: None)

    result = run_regression_command(
        RegressionCommand("probe", ("python", "-m", "pytest")),
        memory_watch_enabled=True,
        memory_sample_seconds=5,
        max_commit_gb=96.0,
        max_commit_percent=85.0,
        max_physical_percent=75.0,
        min_available_physical_gb=24.0,
    )

    assert result.returncode == 0
    assert result.peak_memory_snapshot is not None
    assert result.peak_memory_snapshot.commit_used_gb == 48.5
