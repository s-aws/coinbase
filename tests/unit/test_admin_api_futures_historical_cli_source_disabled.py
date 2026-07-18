"""Terminal guards for historical Futures CLI entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest

from core.coinbase_execution_authority import (
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from tools import run_admin_api_futures_live_fill_readback as fill_readback_tool
from tools import run_admin_api_futures_no_live_preview as r4_tool
from tools import run_admin_api_futures_no_live_preview_r5 as r5_tool
from tools import run_admin_api_futures_no_live_preview_r6 as r6_tool


def _bomb(label: str, calls: list[str]) -> Callable[..., object]:
    def fail(*_args: object, **_kwargs: object) -> object:
        calls.append(label)
        raise AssertionError(f"source-disabled CLI reached {label}")

    return fail


@pytest.mark.parametrize(
    ("tool", "argv"),
    (
        (r4_tool, ["--confirm-one-r4-preview"]),
        (r4_tool, ["--preflight"]),
        (r5_tool, ["--confirm-one-r5-preview"]),
        (r5_tool, ["--preflight"]),
        (r6_tool, ["--confirm-one-r6-preview"]),
        (r6_tool, ["--preflight"]),
    ),
)
def test_historical_preview_main_is_source_disabled_before_any_access(
    tool: ModuleType,
    argv: Sequence[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_root = tmp_path / "empty-artifact-root"
    artifact_root.mkdir()
    calls: list[str] = []

    def artifact_path() -> Path:
        calls.append("artifact_path")
        return artifact_root / "missing-historical-preview.jsonl"

    monkeypatch.setattr(tool, "production_artifact_path", artifact_path)
    monkeypatch.setattr(
        tool,
        "validate_production_predecessor",
        _bomb("predecessor_artifact_read", calls),
    )
    monkeypatch.setattr(tool, "build_rest_client", _bomb("client_factory", calls))
    monkeypatch.setattr(
        tool,
        "FuturesOrderPreviewArtifactStore",
        _bomb("artifact_store", calls),
    )
    monkeypatch.setattr(
        tool,
        "FuturesOrderPreviewProducer",
        _bomb("preview_producer", calls),
    )
    monkeypatch.setattr(
        r4_tool,
        "ensure_live_coinbase_credentials",
        _bomb("credential_hydration", calls),
    )

    assert tool.main(argv) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{SOURCE_DISABLED_COINBASE_EXECUTION_ERROR}\n"
    assert calls == []
    assert list(artifact_root.iterdir()) == []


def test_historical_fill_readback_main_is_source_disabled_before_any_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_root = tmp_path / "empty-artifact-root"
    artifact_root.mkdir()
    submission_path = artifact_root / "missing-submission.json"
    output_path = artifact_root / "must-not-be-created.json"
    calls: list[str] = []

    monkeypatch.setattr(
        fill_readback_tool,
        "config_from_args",
        _bomb("artifact_configuration", calls),
    )
    monkeypatch.setattr(
        fill_readback_tool,
        "read_optional_json_object",
        _bomb("artifact_read", calls),
    )
    monkeypatch.setattr(
        fill_readback_tool,
        "assert_live_read_credentials_present",
        _bomb("credential_hydration", calls),
    )
    monkeypatch.setattr(
        fill_readback_tool,
        "get_admin_mvp_service",
        _bomb("client_factory", calls),
    )
    monkeypatch.setattr(
        fill_readback_tool,
        "run_futures_live_fill_readback",
        _bomb("coinbase_order_or_fill_read", calls),
    )
    monkeypatch.setattr(
        fill_readback_tool,
        "write_json",
        _bomb("artifact_write", calls),
    )

    assert fill_readback_tool.main(
        [
            "--submission-artifact",
            str(submission_path),
            "--summary-output",
            str(output_path),
            "--client-order-id",
            "private-operator-value-must-not-echo",
        ]
    ) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{SOURCE_DISABLED_COINBASE_EXECUTION_ERROR}\n"
    assert "private-operator-value" not in captured.err
    assert calls == []
    assert list(artifact_root.iterdir()) == []


@pytest.mark.parametrize(
    "tool",
    (r4_tool, r5_tool, r6_tool, fill_readback_tool),
)
def test_historical_futures_cli_help_remains_local_and_call_free(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    for name in (
        "config_from_args",
        "production_artifact_path",
        "validate_production_predecessor",
        "build_rest_client",
        "assert_live_read_credentials_present",
        "get_admin_mvp_service",
        "run_futures_live_fill_readback",
        "write_json",
    ):
        if hasattr(tool, name):
            monkeypatch.setattr(tool, name, _bomb(name, calls))

    with pytest.raises(SystemExit) as exc_info:
        tool.main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "source-disabled" in captured.out.lower()
    assert captured.err == ""
    assert calls == []
