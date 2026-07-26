"""Shared PostgreSQL seal for exact-child Futures Cancel invocation."""

from __future__ import annotations

import re
from typing import Any
import uuid


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TABLE = "operator_futures_cancel_invocation_seal"
_GUARD = "guard_operator_futures_cancel_invocation_seal_append_only"
_TRIGGER = "operator_futures_cancel_invocation_seal_append_only"


def _table(schema: str, name: str) -> str:
    if _SCHEMA_RE.fullmatch(str(schema)) is None:
        raise ValueError("operator_futures_cancel_seal_schema_invalid")
    return f'"{schema}"."{name}"'


def ensure_futures_cancel_invocation_seal(
    cursor: Any,
    *,
    schema: str,
) -> None:
    """Install one immutable per-client-order Cancel invocation boundary."""

    table = _table(schema, _TABLE)
    guard = _table(schema, _GUARD)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            portfolio_id_sha256 CHAR(64) NOT NULL
                CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
            client_order_id VARCHAR(128) NOT NULL,
            mutation_class VARCHAR(16) NOT NULL DEFAULT 'CANCEL'
                CHECK (mutation_class = 'CANCEL'),
            exchange_order_id_sha256 CHAR(64) NOT NULL
                CHECK (
                    exchange_order_id_sha256
                    ~ '^[0-9a-f]{{64}}$'
                ),
            claim_id UUID NOT NULL UNIQUE,
            owner_ledger VARCHAR(128) NOT NULL,
            invoked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (
                portfolio_id_sha256,
                client_order_id,
                mutation_class
            )
        )
        """
    )
    cursor.execute(
        f"""
        CREATE OR REPLACE FUNCTION {guard}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '55000',
                MESSAGE =
                    'operator_futures_cancel_invocation_seal_append_only';
        END;
        $$
        """
    )
    cursor.execute(
        f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {table}"
    )
    cursor.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {guard}()
        """
    )


def seal_futures_cancel_invocation(
    cursor: Any,
    *,
    schema: str,
    owner_ledger: str,
    claim_id: str,
    portfolio_id_sha256: str,
    client_order_id: str,
    exchange_order_id_sha256: str,
) -> None:
    """Atomically consume the one exact-child Futures Cancel boundary."""

    owner = str(owner_ledger or "").strip()
    portfolio_hash = str(portfolio_id_sha256 or "").strip().lower()
    child = str(client_order_id or "").strip()
    exchange_hash = str(exchange_order_id_sha256 or "").strip().lower()
    try:
        normalized_claim_id = str(uuid.UUID(str(claim_id)))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(
            "operator_futures_cancel_invocation_binding_invalid"
        ) from None
    if (
        not owner
        or len(owner) > 128
        or _SHA256_RE.fullmatch(portfolio_hash) is None
        or not child
        or len(child) > 128
        or _SHA256_RE.fullmatch(exchange_hash) is None
    ):
        raise ValueError(
            "operator_futures_cancel_invocation_binding_invalid"
        )
    cursor.execute(
        f"""
        INSERT INTO {_table(schema, _TABLE)} (
            portfolio_id_sha256, client_order_id, mutation_class,
            exchange_order_id_sha256, claim_id, owner_ledger
        ) VALUES (%s, %s, 'CANCEL', %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            portfolio_hash,
            child,
            exchange_hash,
            normalized_claim_id,
            owner,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError(
            "operator_futures_cancel_invocation_already_sealed"
        )


def futures_cancel_invocation_is_sealed(
    cursor: Any,
    *,
    schema: str,
    portfolio_id_sha256: str,
    client_order_id: str,
) -> bool:
    """Read whether the exact Default-portfolio child already crossed Cancel."""

    portfolio_hash = str(portfolio_id_sha256 or "").strip().lower()
    child = str(client_order_id or "").strip()
    if (
        _SHA256_RE.fullmatch(portfolio_hash) is None
        or not child
        or len(child) > 128
    ):
        raise ValueError(
            "operator_futures_cancel_invocation_binding_invalid"
        )
    cursor.execute(
        f"""
        SELECT 1
          FROM {_table(schema, _TABLE)}
         WHERE portfolio_id_sha256 = %s
           AND client_order_id = %s
           AND mutation_class = 'CANCEL'
        """,
        (portfolio_hash, child),
    )
    return cursor.fetchone() is not None


__all__ = [
    "ensure_futures_cancel_invocation_seal",
    "futures_cancel_invocation_is_sealed",
    "seal_futures_cancel_invocation",
]
