"""Shared PostgreSQL lock namespace for product-scoped fill-ledger writes."""

from __future__ import annotations


FILL_LEDGER_PRODUCT_LOCK_NAMESPACE = "operator-fill-inventory:"


def fill_ledger_product_lock_key(product_id: str) -> str:
    """Return the exact advisory-lock key used by every fill writer."""

    return f"{FILL_LEDGER_PRODUCT_LOCK_NAMESPACE}{product_id}"
