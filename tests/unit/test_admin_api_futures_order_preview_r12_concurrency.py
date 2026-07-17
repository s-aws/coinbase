"""Cross-process safety tests for Slice 2R12 recovery serialization."""

from __future__ import annotations

from datetime import datetime, timezone
import multiprocessing
from pathlib import Path

import pytest

from application.admin_api.futures_order_preview_r12 import (
    FuturesPreviewR12ArtifactStore,
    FuturesPreviewR12AttemptWorkflow,
    FuturesPreviewR12EligibilityError,
    FuturesPreviewR12EligibilityStore,
    FuturesPreviewR12EligibilityWorkflow,
)
from tests.unit.test_admin_api_futures_order_preview_r12 import (
    TEST_R12_PREDECESSOR_BINDING,
    _AttemptDelegate,
    _ReadyDelegate,
)
from tools import run_admin_api_futures_r12_workflow as r12_tool


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def test_r12_startup_recovery_cannot_terminalize_an_active_preview(
    tmp_path: Path,
) -> None:
    """A second process cannot recover while the first owns the lease."""

    context = multiprocessing.get_context("fork")
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    preview_entered = context.Queue()
    child_outcome = context.Queue()
    release_preview = context.Event()
    preview_calls = context.Value("i", 0)

    def run_first_workflow() -> None:
        eligibility_store = FuturesPreviewR12EligibilityStore(
            eligibility_path
        )
        artifact_store = FuturesPreviewR12ArtifactStore(attempt_path)
        delegate = _AttemptDelegate(artifact_path=attempt_path)
        original_preview = delegate.preview_order

        def blocking_preview(**kwargs: object) -> object:
            with preview_calls.get_lock():
                preview_calls.value += 1
            preview_entered.put("entered")
            if not release_preview.wait(timeout=10):
                raise AssertionError("parent did not release Preview")
            return original_preview(**kwargs)

        delegate.preview_order = blocking_preview  # type: ignore[method-assign]
        attempt = FuturesPreviewR12AttemptWorkflow(
            eligibility_store=eligibility_store,
            store=artifact_store,
            predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
            predecessor_validator=lambda: dict(
                TEST_R12_PREDECESSOR_BINDING
            ),
            now=lambda: NOW,
            correlation_id_factory=(
                lambda: "a5fcaac6-3480-4608-9aae-e3a24a17458f"
            ),
            idempotency_key_factory=(
                lambda: "fe527dd7-d110-4372-b09f-9799f7356347"
            ),
        )
        eligibility = FuturesPreviewR12EligibilityWorkflow(
            store=eligibility_store,
            attempt_artifact_path=attempt_path,
            rest_client_factory=lambda: _ReadyDelegate(
                store_path=eligibility_path,
                attempt_delegate=delegate,
            ),
            now=lambda: NOW,
            correlation_id_factory=(
                lambda: "071551b6-fc21-4440-a741-7d11231e001c"
            ),
        )
        try:
            result = eligibility.run_cycle(attempt_workflow=attempt)
        except BaseException as exc:  # pragma: no cover - asserted by queue
            child_outcome.put(("error", type(exc).__name__))
            raise
        child_outcome.put(("ok", result["outcome"]))

    process = context.Process(target=run_first_workflow)
    process.start()
    assert preview_entered.get(timeout=10) == "entered"
    try:
        assert len(attempt_path.read_text(encoding="utf-8").splitlines()) == 1
        recovery_store = FuturesPreviewR12EligibilityStore(eligibility_path)
        recovery = FuturesPreviewR12AttemptWorkflow(
            eligibility_store=recovery_store,
            store=FuturesPreviewR12ArtifactStore(attempt_path),
            predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
            predecessor_validator=lambda: dict(
                TEST_R12_PREDECESSOR_BINDING
            ),
            now=lambda: NOW,
            correlation_id_factory=lambda: "unused",
            idempotency_key_factory=lambda: "unused",
        )

        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="already active",
        ):
            r12_tool._recover_existing_attempt(recovery)

        assert len(attempt_path.read_text(encoding="utf-8").splitlines()) == 1
        assert preview_calls.value == 1
    finally:
        release_preview.set()
        process.join(timeout=15)

    assert process.exitcode == 0
    assert child_outcome.get(timeout=5) == ("ok", "accepted")
    rows = FuturesPreviewR12ArtifactStore(attempt_path)._read_rows()  # noqa: SLF001
    assert len(rows) == 2
    assert [row["record_type"] for row in rows] == ["claim", "result"]
    assert preview_calls.value == 1
