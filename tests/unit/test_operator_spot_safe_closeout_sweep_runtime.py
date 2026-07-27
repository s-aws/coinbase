from __future__ import annotations

from types import SimpleNamespace

from application.admin_api import (
    operator_spot_safe_closeout_sweep_runtime as runtime,
)


def test_default_service_installs_schema_and_recovers_once(
    monkeypatch,
) -> None:
    calls: list[str] = []
    repository = SimpleNamespace(
        configured_portfolio_scope_sha256="a" * 64,
        ensure_schema=lambda: calls.append("ensure_schema"),
        recover_stranded_work=lambda: calls.append(
            "recover_stranded_work"
        ),
    )
    monkeypatch.setattr(
        runtime,
        "get_default_operator_spot_safe_closeout_sweep_repository",
        lambda: repository,
    )
    runtime.get_default_operator_spot_safe_closeout_sweep_service.cache_clear()

    first = runtime.get_default_operator_spot_safe_closeout_sweep_service()
    second = runtime.get_default_operator_spot_safe_closeout_sweep_service()

    assert first is second
    assert calls == ["ensure_schema", "recover_stranded_work"]
    runtime.get_default_operator_spot_safe_closeout_sweep_service.cache_clear()
