"""Regression: keep reveal_pricing_policy stable across DB persistence.

Background (2026-05-02)
========================

UI create flow selected TOP_OF_BOOK, but loaded/evaluated stealth orders
resolved to CONFIGURED_LIMIT because DB save/load paths dropped the
reveal_pricing_policy field.

This guard ensures the schema and persistence code keep the field end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_STEALTH_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


_ORDER_DB_SRC = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "order.py"
).read_text(encoding="utf-8")


@pytest.mark.regression
def test_schema_has_reveal_pricing_policy_column():
    assert "reveal_pricing_policy VARCHAR(32) NOT NULL DEFAULT 'configured_limit'" in _ORDER_DB_SRC
    assert "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS reveal_pricing_policy" in _ORDER_DB_SRC
    assert "follow_up_reveal_direction VARCHAR(16) NOT NULL DEFAULT 'opposite'" in _ORDER_DB_SRC
    assert "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS follow_up_reveal_direction" in _ORDER_DB_SRC


@pytest.mark.regression
def test_save_path_persists_reveal_pricing_policy():
    assert "INSERT INTO stealth_orders" in _STEALTH_MANAGER_SRC
    assert "reveal_pricing_policy" in _STEALTH_MANAGER_SRC
    assert "follow_up_reveal_direction" in _STEALTH_MANAGER_SRC


@pytest.mark.regression
def test_update_path_persists_reveal_pricing_policy():
    assert "UPDATE stealth_orders" in _STEALTH_MANAGER_SRC
    assert "reveal_pricing_policy = %s" in _STEALTH_MANAGER_SRC
    assert "follow_up_reveal_direction = %s" in _STEALTH_MANAGER_SRC


@pytest.mark.regression
def test_load_paths_rehydrate_reveal_pricing_policy():
    assert "'reveal_pricing_policy': reveal_pricing_policy" in _STEALTH_MANAGER_SRC
    # Two loaders must both carry the field.
    assert _STEALTH_MANAGER_SRC.count("'reveal_pricing_policy': reveal_pricing_policy") >= 2


@pytest.mark.regression
def test_load_paths_rehydrate_follow_up_direction():
    assert "'follow_up_reveal_direction': row.get('follow_up_reveal_direction')" in _STEALTH_MANAGER_SRC
    assert _STEALTH_MANAGER_SRC.count("'follow_up_reveal_direction': row.get('follow_up_reveal_direction')") >= 2


@pytest.mark.regression
def test_load_paths_hydrate_parent_backed_runtime_fields():
    assert "def _hydrate_parent_runtime_fields(" in _STEALTH_MANAGER_SRC
    assert "order_data[\"max_order_replacements\"] = max_replacements" in _STEALTH_MANAGER_SRC
    assert "order_data[\"allow_partial_fills\"] = allow_partial_fills" in _STEALTH_MANAGER_SRC
