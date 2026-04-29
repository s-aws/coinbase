"""Regression: every exception class accepts the kwargs that real call sites use.

Bug seen 2026-04-28: production logs showed::

    OrderEngine - INFO - user_event_thread_5 [ERROR]
    {"error": "OrderPersistenceError.__init__() got an unexpected keyword
              argument 'error_type'", ...}

Root cause: ``database/order.py`` (and other modules) raise the database
exceptions with ``error_type=`` / ``stealth_order_id=`` kwargs, but the
classes' ``__init__`` did not accept them. The error-handling path itself
crashed, swallowing the original ``ForeignKeyViolation`` and dropping the
parent-order insert for at least one client_order_id.

This test pins the public construction API used by every call site so a
future refactor cannot silently re-introduce the regression.
"""
import inspect
import re
from pathlib import Path

import pytest

from core.exceptions import (
    DatabaseConnectionError,
    DatabaseTransactionError,
    OrderPersistenceError,
    WebSocketMessageError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Constructor smoke tests — every kwargs combo seen in the real call sites
# ---------------------------------------------------------------------------

class TestOrderPersistenceErrorSignature:
    def test_kwargs_signature_with_client_order_id(self):
        """database/order.py::insert_order_parent (line 740 form)."""
        exc = OrderPersistenceError(
            error_type="InsertionError",
            message="Failed to insert parent order x: y",
            client_order_id="abc-123",
        )
        assert exc.error_type == "InsertionError"
        assert exc.client_order_id == "abc-123"
        assert "abc-123" in str(exc)

    def test_kwargs_signature_with_stealth_order_id(self):
        """database/order.py::get_stealth_order (line 326 form)."""
        exc = OrderPersistenceError(
            error_type="PersistenceQueryError",
            message="Failed to fetch stealth order s-1",
            stealth_order_id="s-1",
        )
        assert exc.stealth_order_id == "s-1"
        assert "s-1" in str(exc)

    def test_legacy_positional_signature_still_works(self):
        """tests/test_exceptions.py keeps the (msg, op, table) form."""
        exc = OrderPersistenceError("test", "insert", "order_parent")
        assert exc.operation == "insert"
        assert exc.table == "order_parent"


class TestDatabaseConnectionErrorSignature:
    def test_accepts_error_type_and_client_order_id(self):
        exc = DatabaseConnectionError(
            error_type="ConnectionError",
            message="Failed to connect while inserting parent order",
            client_order_id="abc-123",
        )
        assert exc.error_type == "ConnectionError"
        assert exc.client_order_id == "abc-123"

    def test_accepts_error_type_and_stealth_order_id(self):
        exc = DatabaseConnectionError(
            error_type="ConnectionError",
            message="Failed to connect while fetching stealth order",
            stealth_order_id="s-1",
        )
        assert exc.stealth_order_id == "s-1"

    def test_legacy_positional_signature_still_works(self):
        exc = DatabaseConnectionError("Connection timeout after 30s")
        assert "timeout" in str(exc).lower()


class TestDatabaseTransactionErrorSignature:
    def test_accepts_error_type_kwarg(self):
        """database/order.py::update_parent_order_target_movement (line 904)."""
        exc = DatabaseTransactionError(
            error_type="UpdateTransactionError",
            message="Failed to update parent order target_movement",
            client_order_id="abc-123",
        )
        assert exc.error_type == "UpdateTransactionError"
        assert exc.client_order_id == "abc-123"

    def test_legacy_positional_signature_still_works(self):
        exc = DatabaseTransactionError(
            message="Transaction rolled back",
            rollback_reason="Constraint violation",
        )
        assert exc.rollback_reason == "Constraint violation"


class TestWebSocketMessageErrorSignature:
    def test_accepts_error_type_kwarg(self):
        """business/event_processor.py::hash_event (line 76)."""
        exc = WebSocketMessageError(
            error_type="EventSerializationError",
            message="Failed to serialize event for hashing",
            raw_data="{'foo': set()}",
        )
        assert exc.error_type == "EventSerializationError"
        assert exc.raw_data == "{'foo': set()}"

    def test_legacy_positional_signature_still_works(self):
        exc = WebSocketMessageError(
            message="Invalid JSON",
            raw_data='{"invalid": json}',
        )
        assert exc.raw_data == '{"invalid": json}'


# ---------------------------------------------------------------------------
# 2. Static guard — every actual raise site in the repo must round-trip
# ---------------------------------------------------------------------------

# Maps class name -> class object for the guard.
_GUARDED_CLASSES = {
    "OrderPersistenceError": OrderPersistenceError,
    "DatabaseConnectionError": DatabaseConnectionError,
    "DatabaseTransactionError": DatabaseTransactionError,
    "WebSocketMessageError": WebSocketMessageError,
}


def _iter_call_signatures():
    """Yield (path, lineno, cls, kwarg_names) for every constructor call.

    Walks the repo once and pattern-matches ``ClassName(...)`` calls,
    extracting the kwarg names so we can prove each exception's
    __init__ accepts them.
    """
    src_globs = [
        REPO_ROOT.glob("core/**/*.py"),
        REPO_ROOT.glob("business/**/*.py"),
        REPO_ROOT.glob("database/**/*.py"),
        REPO_ROOT.glob("bridges/**/*.py"),
    ]
    name_re = "|".join(re.escape(n) for n in _GUARDED_CLASSES)
    call_re = re.compile(rf"\b({name_re})\s*\(")

    for it in src_globs:
        for path in it:
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in call_re.finditer(text):
                cls_name = m.group(1)
                # Find the matching close paren (single-level scan is fine
                # for these constructor calls; nested parens are tracked).
                depth = 0
                start = m.end() - 1
                end = None
                for i in range(start, len(text)):
                    ch = text[i]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                if end is None:
                    continue
                args_blob = text[start + 1:end]
                kwargs = re.findall(r"(\w+)\s*=", args_blob)
                lineno = text.count("\n", 0, m.start()) + 1
                yield path.relative_to(REPO_ROOT).as_posix(), lineno, cls_name, kwargs


def test_every_constructor_call_in_repo_uses_supported_kwargs():
    """Static guard: walk the source tree, prove every observed kwarg exists.

    Fails loudly if a call site is added that uses a kwarg the class
    doesn't accept (which is exactly what shipped on 2026-04-28).
    """
    failures = []
    for path, lineno, cls_name, kwargs in _iter_call_signatures():
        cls = _GUARDED_CLASSES[cls_name]
        sig = inspect.signature(cls.__init__)
        param_names = set(sig.parameters)
        accepts_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        for kwarg in kwargs:
            if kwarg in param_names or accepts_kwargs:
                continue
            failures.append(
                f"{path}:{lineno}  {cls_name}({kwarg}=...) — not in __init__ signature"
            )

    assert not failures, (
        "Exception constructor calls use unsupported kwargs:\n  "
        + "\n  ".join(failures)
    )
