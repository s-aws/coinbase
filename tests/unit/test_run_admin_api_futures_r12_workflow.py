"""Focused offline safety tests for the integrated Slice 2R12 runner."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import UUID

import pytest

from application.admin_api import futures_order_preview_r12 as r12_module
from tools import run_admin_api_futures_r12_workflow as r12_tool


def _allow_fixed_r12_aws_binding(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identities: list[tuple[int, ...]] | None = None,
) -> tuple[list[str], list[tuple[int, ...]]]:
    binding_checks: list[str] = []
    observed_identities = identities or [(1, 2, 3), (1, 2, 3)]
    identity_iterator = iter(observed_identities)
    monkeypatch.setattr(
        r12_tool,
        "_validate_r12_aws_cli_binding",
        lambda: binding_checks.append("binding") or True,
    )
    monkeypatch.setattr(
        r12_tool,
        "_r12_credential_file_identity",
        lambda: next(identity_iterator),
    )
    return binding_checks, observed_identities


def test_r12_client_factory_injects_fixed_single_attempt_secret_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def build_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        r12_tool.base_preview_tool,
        "_build_canonical_default_rest_client",
        build_client,
    )
    r12_tool._cached_canonical_default_rest_client.cache_clear()
    try:
        assert r12_tool._cached_canonical_default_rest_client() is sentinel
    finally:
        r12_tool._cached_canonical_default_rest_client.cache_clear()

    assert set(captured) == {"run_secret_lookup"}
    assert type(captured["run_secret_lookup"]) is (
        r12_tool._R12SingleUseSecretLookup
    )


def test_r12_secret_lookup_capability_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        r12_tool,
        "_lookup_fixed_r12_secret",
        lambda secret_id, region: calls.append((secret_id, region)) or "payload",
    )
    lookup = r12_tool._R12SingleUseSecretLookup()

    assert lookup("coinbase", "us-east-1") == "payload"
    with pytest.raises(
        r12_tool.FuturesPreviewR12RunnerError,
        match="R12 credential preparation failed",
    ):
        lookup("coinbase", "us-east-1")
    assert calls == [("coinbase", "us-east-1")]


def test_r12_secret_lookup_is_fixed_single_attempt_and_closed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    binding_checks, identities = _allow_fixed_r12_aws_binding(monkeypatch)
    payload = '{"SecretString":"{\\"api_key\\":\\"synthetic-key\\",\\"api_secret\\":\\"synthetic-secret\\"}"}'

    def run(argv: list[str], **kwargs: object) -> object:
        calls.append((list(argv), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(r12_tool.subprocess, "run", run)

    assert r12_tool._lookup_fixed_r12_secret("coinbase", "us-east-1") == payload
    assert binding_checks == ["binding", "binding"]
    assert identities == [(1, 2, 3), (1, 2, 3)]
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        str(r12_tool._R12_AWS_CLI_CANONICAL_PATH),
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        "coinbase",
        "--region",
        "us-east-1",
        "--endpoint-url",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "--ca-bundle",
        str(r12_tool._R12_AWS_CLI_CA_BUNDLE),
        "--output",
        "json",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "20",
    ]
    assert kwargs == {
        "cwd": r12_tool.REPO_ROOT,
        "env": {
            "AWS_CLI_AUTO_PROMPT": "off",
            "AWS_CLI_HISTORY_FILE": "/dev/null",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_PAGER": "",
            "AWS_PROFILE": "default",
            "AWS_REGION": "us-east-1",
            "AWS_RETRY_MODE": "standard",
            "AWS_SHARED_CREDENTIALS_FILE": "/home/developer/.aws/credentials",
            "HOME": "/nonexistent",
            "LC_ALL": "C",
            "PATH": str(r12_tool._R12_AWS_CLI_CANONICAL_PATH.parent),
        },
        "check": False,
        "capture_output": True,
        "text": True,
        "stdin": subprocess.DEVNULL,
        "timeout": 35,
    }


@pytest.mark.parametrize(
    ("secret_id", "region"),
    [("alternate", "us-east-1"), ("coinbase", None), ("coinbase", "us-west-2")],
)
def test_r12_secret_lookup_rejects_scope_drift_before_process_start(
    monkeypatch: pytest.MonkeyPatch,
    secret_id: str,
    region: str | None,
) -> None:
    monkeypatch.setattr(
        r12_tool.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("AWS process must not start"),
    )

    with pytest.raises(
        r12_tool.FuturesPreviewR12RunnerError,
        match="R12 credential preparation failed",
    ):
        r12_tool._lookup_fixed_r12_secret(secret_id, region)


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(
            returncode=1,
            stdout="private-secret-stdout",
            stderr="private-secret-stderr",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout="x" * (128 * 1024 + 1),
            stderr="",
        ),
    ],
)
def test_r12_secret_lookup_failures_are_bounded_and_value_blind(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> None:
    _allow_fixed_r12_aws_binding(monkeypatch)
    monkeypatch.setattr(
        r12_tool.subprocess,
        "run",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(r12_tool.FuturesPreviewR12RunnerError) as raised:
        r12_tool._lookup_fixed_r12_secret("coinbase", "us-east-1")

    assert str(raised.value) == "R12 credential preparation failed"
    assert "private" not in str(raised.value)


def test_r12_secret_lookup_timeout_is_value_blind_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    _allow_fixed_r12_aws_binding(monkeypatch)

    def timeout(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired("private-command", 35)

    monkeypatch.setattr(r12_tool.subprocess, "run", timeout)
    lookup = r12_tool._R12SingleUseSecretLookup()

    for _ in range(2):
        with pytest.raises(r12_tool.FuturesPreviewR12RunnerError) as raised:
            lookup("coinbase", "us-east-1")
        assert str(raised.value) == "R12 credential preparation failed"
        assert "private-command" not in str(raised.value)
    assert calls == 1


def test_r12_secret_lookup_rejects_unverified_binding_before_secret_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks: list[str] = []
    monkeypatch.setattr(
        r12_tool,
        "_r12_credential_file_identity",
        lambda: (1, 2, 3),
    )
    monkeypatch.setattr(
        r12_tool,
        "_validate_r12_aws_cli_binding",
        lambda: False,
    )
    monkeypatch.setattr(
        r12_tool.subprocess,
        "run",
        lambda *_args, **_kwargs: checks.append("secret-process"),
    )

    with pytest.raises(r12_tool.FuturesPreviewR12RunnerError) as raised:
        r12_tool._lookup_fixed_r12_secret("coinbase", "us-east-1")

    assert str(raised.value) == "R12 credential preparation failed"
    assert checks == []


def test_r12_secret_lookup_rejects_credential_identity_drift_after_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding_checks, _ = _allow_fixed_r12_aws_binding(
        monkeypatch,
        identities=[(1, 2, 3), (1, 2, 4)],
    )
    calls = 0

    def run(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout='{"SecretString":"private-value"}',
            stderr="",
        )

    monkeypatch.setattr(r12_tool.subprocess, "run", run)

    with pytest.raises(r12_tool.FuturesPreviewR12RunnerError) as raised:
        r12_tool._lookup_fixed_r12_secret("coinbase", "us-east-1")

    assert str(raised.value) == "R12 credential preparation failed"
    assert "private-value" not in str(raised.value)
    assert calls == 1
    assert binding_checks == ["binding", "binding"]


def test_r12_secret_lookup_rejects_post_attempt_binding_drift_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = iter((True, False))
    calls = 0
    identities = iter(((1, 2, 3), (1, 2, 3)))
    monkeypatch.setattr(
        r12_tool,
        "_validate_r12_aws_cli_binding",
        lambda: next(checks),
    )
    monkeypatch.setattr(
        r12_tool,
        "_r12_credential_file_identity",
        lambda: next(identities),
    )

    def run(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout='{"SecretString":"private-value"}',
            stderr="",
        )

    monkeypatch.setattr(r12_tool.subprocess, "run", run)

    with pytest.raises(r12_tool.FuturesPreviewR12RunnerError) as raised:
        r12_tool._lookup_fixed_r12_secret("coinbase", "us-east-1")

    assert str(raised.value) == "R12 credential preparation failed"
    assert calls == 1


def test_r12_bootstrap_read_rejects_links_and_writable_files(
    tmp_path: Path,
) -> None:
    regular = tmp_path / "regular"
    regular.write_bytes(b"bound")
    regular.chmod(0o600)
    linked = tmp_path / "linked"
    linked.symlink_to(regular)

    assert r12_tool._r12_bootstrap_read_regular(
        regular,
        maximum_bytes=16,
    ) == b"bound"
    with pytest.raises(ValueError, match="regular_file"):
        r12_tool._r12_bootstrap_read_regular(linked, maximum_bytes=16)

    regular.chmod(0o620)
    with pytest.raises(ValueError, match="regular_file"):
        r12_tool._r12_bootstrap_read_regular(regular, maximum_bytes=16)


def test_r12_credential_identity_requires_owner_only_stable_regular_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text("[default]\n", encoding="utf-8")
    credentials.chmod(0o600)
    monkeypatch.setattr(r12_tool, "_R12_AWS_CREDENTIALS_PATH", credentials)

    identity = r12_tool._r12_credential_file_identity()

    assert identity[1] == credentials.stat().st_ino
    credentials.chmod(0o640)
    with pytest.raises(ValueError, match="credential_file"):
        r12_tool._r12_credential_file_identity()


def _terminal_summary() -> dict[str, object]:
    return {
        "status": "unknown",
        "outcome": "unknown",
        "blocker": "claim_only_recovery_unknown_consumed",
        "artifact_path": str(r12_module.FUTURES_PREVIEW_R12_ARTIFACT_PATH),
        "eligibility_path": str(
            r12_module.FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
        ),
        "artifact_created": True,
        "r12_attempt_consumed": True,
        "preview_order_attempt_count": 1,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_coinbase_execution": "not_run",
    }


@pytest.mark.parametrize(
    "classification",
    [
        "product_contract_ineligible",
        "market_book_ineligible",
        "position_exposure_ineligible",
        "candidate_caps_ineligible",
    ],
)
def test_r12_runner_projects_split_value_blind_eligibility_classifications(
    classification: str,
) -> None:
    summary = r12_tool._eligibility_summary(
        {
            "status": "ineligible",
            "classification": classification,
            "cycle_number": 2,
            "r12_claim_created": False,
            "r12_idempotency_key_created": False,
            "r12_attempt_consumed": False,
        }
    )

    assert summary["classification"] == classification
    assert summary["eligibility_cycle_number"] == 2
    assert summary["artifact_created"] is False
    assert summary["r12_attempt_consumed"] is False


def test_r12_runner_rejects_legacy_combined_classification_as_new_result() -> None:
    with pytest.raises(r12_tool.FuturesPreviewR12RunnerError, match="invalid"):
        r12_tool._eligibility_summary(
            {
                "status": "ineligible",
                "classification": (
                    "product_or_market_or_position_ineligible"
                ),
                "cycle_number": 2,
                "r12_claim_created": False,
                "r12_idempotency_key_created": False,
                "r12_attempt_consumed": False,
            }
        )


def test_r12_source_release_is_closed_and_blocks_before_any_factory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []

    assert r12_tool.R12_RELEASE_READY is False

    monkeypatch.setattr(
        r12_tool,
        "_recover_existing_attempt",
        lambda _workflow: events.append("recovery") or None,
    )
    monkeypatch.setattr(
        r12_tool,
        "validate_production_futures_order_preview_r12_predecessor",
        lambda: (_ for _ in ()).throw(
            AssertionError("predecessor validation crossed disabled gate")
        ),
    )
    monkeypatch.setattr(
        r12_tool,
        "_cached_canonical_default_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Coinbase/AWS client factory crossed disabled gate")
        ),
    )

    assert r12_tool.main(["--confirm-one-r12-workflow"]) == 2

    assert events == ["recovery"]
    summary = json.loads(capsys.readouterr().err)
    assert summary == {
        "artifact_created": False,
        "artifact_path": str(r12_module.FUTURES_PREVIEW_R12_ARTIFACT_PATH),
        "blocker": "futures_preview_r12_release_gate_inactive",
        "eligibility_path": str(
            r12_module.FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
        ),
        "exchange_submission_attempt_count": 0,
        "executed_notional_usdc": "0",
        "live_coinbase_execution": "not_run",
        "preview_order_attempt_count": 0,
        "r12_attempt_consumed": False,
        "status": "blocked",
        "submitted_notional_usdc": "0",
    }


def test_r12_runner_has_no_path_or_scope_override_and_rejects_path_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_text = r12_tool.build_parser().format_help()
    for forbidden in (
        "--artifact-path",
        "--eligibility-path",
        "--product",
        "--profile",
        "--contracts",
        "--caps",
        "--cycles",
        "--preview-calls",
    ):
        assert forbidden not in help_text

    with pytest.raises(SystemExit):
        r12_tool.build_parser().parse_args(
            ["--confirm-one-r12-workflow", "--artifact-path", "/tmp/r12"]
        )

    monkeypatch.setattr(
        r12_tool,
        "FUTURES_PREVIEW_R12_ARTIFACT_PATH",
        Path("/tmp/alternate-r12.jsonl"),
    )
    with pytest.raises(
        r12_tool.FuturesPreviewR12RunnerError,
        match="R12 production singleton paths are invalid",
    ):
        r12_tool._validate_production_singleton_paths()


def test_r12_claim_only_recovery_precedes_factory_even_with_release_disabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    raw_terminal = {"private": "must-not-be-printed"}
    safe_summary = _terminal_summary()

    monkeypatch.setattr(
        r12_tool,
        "_recover_existing_attempt",
        lambda _workflow: events.append("recovery") or raw_terminal,
    )
    monkeypatch.setattr(
        r12_tool,
        "_validated_terminal_summary",
        lambda value: (
            events.append("validation")
            or safe_summary
            if value is raw_terminal
            else (_ for _ in ()).throw(AssertionError("wrong terminal"))
        ),
    )
    monkeypatch.setattr(
        r12_tool,
        "_cached_canonical_default_rest_client",
        lambda: events.append("factory")
        or (_ for _ in ()).throw(AssertionError("factory called")),
    )

    assert r12_tool.main(["--confirm-one-r12-workflow"]) == 2

    assert events == ["recovery", "validation"]
    output = capsys.readouterr()
    assert json.loads(output.err) == safe_summary
    assert "must-not-be-printed" not in output.err
    assert not output.out


def test_r12_runner_recovery_holds_the_workflow_lease() -> None:
    events: list[object] = []
    lease_nonce = object()

    class EligibilityStore:
        @contextmanager
        def workflow_lease(self):  # type: ignore[no-untyped-def]
            events.append("lease_enter")
            try:
                yield lease_nonce
            finally:
                events.append("lease_exit")

    class AttemptWorkflow:
        eligibility_store = EligibilityStore()

        def recover_claim_only(self, *, _lease_nonce: object) -> object:
            events.append(("recover", _lease_nonce))
            return {"terminal": True}

    workflow = AttemptWorkflow()

    assert r12_tool._recover_existing_attempt(workflow) == {"terminal": True}
    assert events == [
        "lease_enter",
        ("recover", lease_nonce),
        "lease_exit",
    ]


def test_r12_runner_sanitizes_unexpected_recovery_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "PRIVATE-RECOVERY-EXCEPTION-TEXT"
    monkeypatch.setattr(
        r12_tool,
        "_recover_existing_attempt",
        lambda _workflow: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    monkeypatch.setattr(
        r12_tool,
        "_cached_canonical_default_rest_client",
        lambda: (_ for _ in ()).throw(AssertionError("factory called")),
    )
    monkeypatch.setattr(r12_tool, "_artifact_present", lambda: True)

    assert r12_tool.main(["--confirm-one-r12-workflow"]) == 2

    summary_text = capsys.readouterr().err
    assert secret not in summary_text
    assert "RuntimeError" not in summary_text
    summary = json.loads(summary_text)
    assert summary["blocker"] == (
        "futures_preview_r12_recovery_blocked"
    )
    assert summary["r12_attempt_consumed"] is True
    assert summary["preview_order_attempt_count"] == 1


def test_r12_canonical_client_is_cached_and_uuid_factories_are_v4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = SimpleNamespace()
    builds = 0
    lookups: list[object] = []

    def build(*, run_secret_lookup: object) -> object:
        nonlocal builds
        builds += 1
        lookups.append(run_secret_lookup)
        return delegate

    r12_tool._cached_canonical_default_rest_client.cache_clear()
    monkeypatch.setattr(
        r12_tool.base_preview_tool,
        "_build_canonical_default_rest_client",
        build,
    )

    assert r12_tool._cached_canonical_default_rest_client() is delegate
    assert r12_tool._cached_canonical_default_rest_client() is delegate
    assert builds == 1
    assert len(lookups) == 1
    assert type(lookups[0]) is r12_tool._R12SingleUseSecretLookup

    first = UUID(r12_tool._uuid4_text())
    second = UUID(r12_tool._uuid4_text())
    assert first.version == 4
    assert second.version == 4
    assert first != second

    r12_tool._cached_canonical_default_rest_client.cache_clear()


def test_r12_active_wiring_runs_one_cycle_with_only_integrated_attempt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[object] = []

    class EligibilityWorkflow:
        def __init__(self, **kwargs: object) -> None:
            events.append(("eligibility_init", kwargs))

        def run_cycle(self, *, attempt_workflow: object) -> dict[str, object]:
            events.append(("cycle", attempt_workflow))
            return {
                "status": "unknown",
                "classification": "read_outcome_unknown",
                "cycle_number": 1,
                "r12_claim_created": False,
                "r12_idempotency_key_created": False,
                "r12_attempt_consumed": False,
            }

    monkeypatch.setattr(r12_tool, "R12_RELEASE_READY", True)
    monkeypatch.setattr(
        r12_tool,
        "_recover_existing_attempt",
        lambda _workflow: events.append("recovery") or None,
    )
    monkeypatch.setattr(
        r12_tool,
        "validate_production_futures_order_preview_r12_predecessor",
        lambda: dict(r12_tool.FUTURES_PREVIEW_R12_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        r12_tool,
        "FuturesPreviewR12EligibilityWorkflow",
        EligibilityWorkflow,
    )

    assert r12_tool.main(["--confirm-one-r12-workflow"]) == 2

    assert events[0] == "recovery"
    init_event = events[1]
    cycle_event = events[2]
    assert isinstance(init_event, tuple)
    assert init_event[0] == "eligibility_init"
    assert init_event[1]["rest_client_factory"] is (
        r12_tool._cached_canonical_default_rest_client
    )
    assert isinstance(cycle_event, tuple)
    assert cycle_event[0] == "cycle"
    assert isinstance(cycle_event[1], r12_module.FuturesPreviewR12AttemptWorkflow)
    assert (
        len(
            [
                event
                for event in events
                if isinstance(event, tuple) and event[0] == "cycle"
            ]
        )
        == 1
    )

    summary = json.loads(capsys.readouterr().err)
    assert summary["status"] == "unknown"
    assert summary["r12_attempt_consumed"] is False
