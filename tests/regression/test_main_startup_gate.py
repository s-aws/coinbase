"""Fail-closed startup ordering for stealth decision activation."""

from unittest.mock import Mock, patch

import pytest

import configuration
import main
from core import startup_reconciler


pytestmark = pytest.mark.regression


def _actors():
    return Mock(name="bridge"), Mock(name="controller"), Mock(name="engine")


def test_unavailable_reconciliation_result_blocks_activation_and_engine(
    monkeypatch,
) -> None:
    bridge, controller, engine = _actors()
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", Mock(return_value=None))
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="could not verify"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    bridge.activate_decisions.assert_not_called()
    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()


def test_reconciliation_exception_blocks_activation_and_engine(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    reconcile = Mock(side_effect=RuntimeError("REST unavailable"))
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="REST unavailable"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    bridge.activate_decisions.assert_not_called()
    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()


def test_activation_failure_blocks_periodic_reconciler_and_engine(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    bridge.activate_decisions.side_effect = RuntimeError("scheduler failed")
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="scheduler failed"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()


def test_successful_startup_crosses_each_gate_in_order(monkeypatch) -> None:
    events = []
    bridge, controller, engine = _actors()
    periodic_reconciler = Mock(name="periodic_reconciler")
    periodic_factory = Mock(
        name="PeriodicReconciler",
        return_value=periodic_reconciler,
    )
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(side_effect=lambda **_kwargs: events.append("reconcile") or object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)
    bridge.activate_decisions.side_effect = lambda: events.append("activate")
    controller.register_stop_hook.side_effect = (
        lambda *_args: events.append("register_periodic_stop")
    )
    periodic_reconciler.start.side_effect = lambda: events.append("periodic_start")
    engine.run_forever.side_effect = lambda: events.append("engine")

    main._run_reconciled_engine(
        reconciler_disabled=False,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    assert events == [
        "reconcile",
        "activate",
        "register_periodic_stop",
        "periodic_start",
        "engine",
    ]
    periodic_factory.assert_called_once_with(auto_heal=True, audit_fills=True)
    controller.register_stop_hook.assert_called_once_with(
        "periodic_reconciler",
        periodic_reconciler.stop,
    )


def test_explicit_reconciler_disable_is_the_only_bypass(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    reconcile = Mock(name="run_startup_reconciliation")
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    main._run_reconciled_engine(
        reconciler_disabled=True,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    reconcile.assert_not_called()
    bridge.activate_decisions.assert_called_once_with()
    periodic_factory.assert_not_called()
    controller.register_stop_hook.assert_not_called()
    engine.run_forever.assert_called_once_with()


class _QueryDB:
    def __init__(self, rows=None, error=None):
        self.rows = rows
        self.error = error

    def execute_query(self, _sql, _params=None):
        if self.error is not None:
            raise self.error
        return list(self.rows or ())

    def disconnect(self):
        return None


def test_local_open_query_failure_makes_reconciliation_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        startup_reconciler,
        "_fetch_exchange_open_client_order_ids",
        lambda: {"exchange-coid"},
    )
    with patch(
        "database.database.PostgresDB",
        return_value=_QueryDB(error=RuntimeError("local DB unavailable")),
    ):
        report = startup_reconciler.run_startup_reconciliation()

    assert report is None


def test_all_local_id_query_failure_makes_reconciliation_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        startup_reconciler,
        "_fetch_exchange_open_client_order_ids",
        lambda: {"known-coid"},
    )
    with patch(
        "database.database.PostgresDB",
        side_effect=(
            _QueryDB(rows=[{"client_order_id": "known-coid", "status": "OPEN"}]),
            _QueryDB(error=RuntimeError("all-local query unavailable")),
        ),
    ):
        report = startup_reconciler.run_startup_reconciliation()

    assert report is None


class _RestClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def list_orders(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.response


@pytest.mark.parametrize(
    "response",
    (
        None,
        {},
        {"success": False, "orders": []},
    ),
)
def test_malformed_exchange_response_cannot_be_treated_as_zero_open_orders(
    monkeypatch,
    response,
) -> None:
    monkeypatch.setattr(configuration, "REST_CLIENT", _RestClient(response))
    auto_heal = Mock(name="apply_auto_heal")
    monkeypatch.setattr(startup_reconciler, "apply_auto_heal", auto_heal)

    report = startup_reconciler.run_startup_reconciliation(auto_heal=True)

    assert report is None
    auto_heal.assert_not_called()


def test_explicit_empty_exchange_orders_list_is_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        configuration,
        "REST_CLIENT",
        _RestClient({"orders": []}),
    )

    assert startup_reconciler._fetch_exchange_open_client_order_ids() == set()


def test_exchange_open_orders_are_exhaustively_paginated(monkeypatch) -> None:
    class PagedRestClient:
        def __init__(self):
            self.calls = []
            self.pages = iter(
                (
                    {
                        "orders": [{"client_order_id": "coid-a"}],
                        "has_next": True,
                        "cursor": "cursor-1",
                    },
                    {
                        "orders": [{"client_order_id": "coid-b"}],
                        "has_next": False,
                        "cursor": None,
                    },
                )
            )

        def list_orders(self, **kwargs):
            self.calls.append(dict(kwargs))
            return next(self.pages)

    rest_client = PagedRestClient()
    monkeypatch.setattr(configuration, "REST_CLIENT", rest_client)

    assert startup_reconciler._fetch_exchange_open_client_order_ids() == {
        "coid-a",
        "coid-b",
    }
    assert rest_client.calls == [
        {"order_status": ["OPEN"]},
        {"order_status": ["OPEN"], "cursor": "cursor-1"},
    ]


@pytest.mark.parametrize(
    "response",
    (
        {"orders": [], "has_next": True, "cursor": None},
        {"orders": [], "has_next": "true", "cursor": "cursor-1"},
    ),
)
def test_malformed_exchange_pagination_fails_closed(
    monkeypatch,
    response,
) -> None:
    monkeypatch.setattr(configuration, "REST_CLIENT", _RestClient(response))

    with pytest.raises(RuntimeError):
        startup_reconciler._fetch_exchange_open_client_order_ids()
