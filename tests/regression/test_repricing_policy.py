"""Regression: ``RepricingPolicy`` dataclass + static-source guard.

Pins:

* On-disk shape preserved \u2014
  ``RepricingPolicy.from_anchor_repricing_policy_dict({...})`` round-trips a
  fully-populated policy without changing keys or values.
* Disabled policies serialise to the minimal ``{"enabled": False}`` form
  that existing JSONB rows already use.
* The dataclass is the **single source of truth** \u2014 no consumer site in
  ``core/stealth_order_manager.py`` or ``dashboard_server.py`` should
  re-implement ``policy.get("<known_field>")`` magic-string access. New
  duplications are caught by a static-source scan.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.enums import (
    RepricingDistanceType,
    RepricingReferenceSource,
    RepricingUpdateMode,
)
from core.models import RepricingPolicy


# ---- shape / round-trip ------------------------------------------------------

def test_disabled_policy_serialises_minimally():
    p = RepricingPolicy.disabled()
    assert p.enabled is False
    assert p.to_anchor_repricing_policy_dict() == {"enabled": False}


def test_from_dict_handles_none_and_empty():
    assert RepricingPolicy.from_anchor_repricing_policy_dict(None).enabled is False
    assert RepricingPolicy.from_anchor_repricing_policy_dict({}).enabled is False
    # enabled=False explicitly \u2192 still disabled
    assert RepricingPolicy.from_anchor_repricing_policy_dict({"enabled": False}).enabled is False


def test_round_trip_preserves_on_disk_shape():
    """A fully-specified policy round-trips byte-for-byte through the dataclass."""
    raw = {
        "enabled": True,
        "reference_price_source": "midpoint",
        "distance_type": "A",
        "target_distance": 100.0,
        "max_distance": 1600.0,
        "update_mode": "adaptive",
        "fixed_interval_seconds": 60,
        "allow_revealed_reprice": True,
        "min_price_change": 0.0,
        "hysteresis_bps": 0.0,
        "min_reprice_interval_seconds": 120,
        "max_reprices_per_hour": 60,
        "post_only_required": False,
        "converge_to_target": True,
        "inherit_to_follow_ups": True,
        "slide_mode": True,
        "max_step_per_reprice": 5.0,
        "volatility_sensitivity": 1.0,
        "max_reprice_window_seconds": 600,
        "require_minimum_volume": 0.0,
        "enable_spread_monitoring": False,
        "max_spread_bps": 50.0,
        "follow_up_retreat_distance": 0.005,
        "follow_up_retreat_jitter": 0.4,
    }
    out = (
        RepricingPolicy.from_anchor_repricing_policy_dict(raw)
        .to_anchor_repricing_policy_dict()
    )
    assert out == raw


def test_round_trip_uses_opt_out_defaults_when_retreat_omitted():
    """Sanity: an enabled policy that omits retreat fields gets the
    opt-out defaults (5bps / 0.5 jitter) written back. Pinned so a
    future tweak to defaults doesn't silently change persisted shape."""
    raw = {"enabled": True, "target_distance": 0.001, "max_distance": 0.005}
    out = (
        RepricingPolicy.from_anchor_repricing_policy_dict(raw)
        .to_anchor_repricing_policy_dict()
    )
    assert out["follow_up_retreat_distance"] == 0.0005
    assert out["follow_up_retreat_jitter"] == 0.5


def test_legacy_aliases_delegate_to_canonical_methods():
    raw = {"enabled": True, "target_distance": 0.001, "max_distance": 0.005}
    policy = getattr(RepricingPolicy, "from_dict")(raw)
    assert policy == RepricingPolicy.from_anchor_repricing_policy_dict(raw)
    assert getattr(policy, "to_dict")() == policy.to_anchor_repricing_policy_dict()


def test_coerce_accepts_dataclass_dict_or_none():
    src = {"enabled": True, "target_distance": 5.0, "max_distance": 10.0}
    p = RepricingPolicy.coerce(src)
    assert isinstance(p, RepricingPolicy)
    # Idempotent on already-typed input.
    assert RepricingPolicy.coerce(p) is p
    # None is treated as disabled.
    assert RepricingPolicy.coerce(None).enabled is False


def test_unknown_enum_strings_fall_back_to_safe_defaults():
    p = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True,
        "reference_price_source": "garbage",
        "distance_type": "Z",
        "update_mode": "yolo",
        "target_distance": 1.0,
    })
    assert p.reference_price_source is RepricingReferenceSource.MIDPOINT
    assert p.distance_type is RepricingDistanceType.PERCENT
    assert p.update_mode is RepricingUpdateMode.ADAPTIVE


# ---- behaviour helpers -------------------------------------------------------

def test_compute_distance_bands_percent_buy():
    p = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True,
        "distance_type": "P",
        "target_distance": 0.001,    # 10 bps
        "max_distance": 0.002,       # 20 bps
    })
    bands = p.compute_distance_bands("BUY", 100_000.0)
    assert bands["target_price"] == pytest.approx(99_900.0)
    assert bands["max_boundary_price"] == pytest.approx(99_800.0)
    assert bands["target_distance_amount"] == pytest.approx(100.0)


def test_compute_distance_bands_absolute_sell():
    p = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True,
        "distance_type": "A",
        "target_distance": 50.0,
        "max_distance": 100.0,
    })
    bands = p.compute_distance_bands("SELL", 1_000.0)
    assert bands["target_price"] == 1_050.0
    assert bands["max_boundary_price"] == 1_100.0


def test_clamp_to_step_noop_when_slide_mode_off():
    p = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True, "target_distance": 1.0,
        "slide_mode": False, "max_step_per_reprice": 2.0,
    })
    price, clamped = p.clamp_to_step(100.0, 110.0)
    assert (price, clamped) == (110.0, False)


def test_clamp_to_step_caps_when_slide_mode_on():
    p = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True, "target_distance": 1.0,
        "slide_mode": True, "max_step_per_reprice": 3.0,
    })
    # Big up-move clamped
    assert p.clamp_to_step(100.0, 110.0) == (103.0, True)
    # Big down-move clamped
    assert p.clamp_to_step(100.0, 80.0) == (97.0, True)
    # Within step \u2192 untouched
    assert p.clamp_to_step(100.0, 102.0) == (102.0, False)


def test_should_reprice_revealed_property():
    on = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True, "target_distance": 1.0,
        "allow_revealed_reprice": True,
    })
    off = RepricingPolicy.from_anchor_repricing_policy_dict({
        "enabled": True, "target_distance": 1.0,
        "allow_revealed_reprice": False,
    })
    assert on.should_reprice_revealed is True
    assert off.should_reprice_revealed is False
    assert RepricingPolicy.disabled().should_reprice_revealed is False


# ---- integration with manager normalizer -------------------------------------

def test_manager_normalizer_collapses_meaningless_policy():
    """Storage path collapses ``enabled=True`` + missing target_distance."""
    from core.stealth_order_manager import StealthOrderManager

    mgr = StealthOrderManager.__new__(StealthOrderManager)
    out = mgr._normalize_anchor_repricing_policy({"enabled": True})
    assert out == {"enabled": False}


def test_manager_normalizer_preserves_valid_policy():
    from core.stealth_order_manager import StealthOrderManager

    mgr = StealthOrderManager.__new__(StealthOrderManager)
    out = mgr._normalize_anchor_repricing_policy({
        "enabled": True,
        "target_distance": 100.0,
        "max_distance": 200.0,
        "distance_type": "A",
    })
    assert out["enabled"] is True
    assert out["target_distance"] == 100.0
    assert out["max_distance"] == 200.0


# ---- static-source guard against duplicate-rule regression -------------------
#
# Per ``/memories/duplicated-rule-pattern.md`` (Coinbase repo, 2026-04-27): the
# same field-extraction rule open-coded across multiple sites is itself the
# bug. Once the canonical rule lives on ``RepricingPolicy``, no consumer
# should reach into the raw dict for known fields. This test enforces that
# invariant by scanning the source.

_GUARDED_FIELDS = (
    "reference_price_source",
    "distance_type",
    "target_distance",
    "max_distance",
    "update_mode",
    "fixed_interval_seconds",
    "min_price_change",
    "hysteresis_bps",
    "min_reprice_interval_seconds",
    "max_reprices_per_hour",
    "slide_mode",
    "max_step_per_reprice",
    "volatility_sensitivity",
    "max_reprice_window_seconds",
    "require_minimum_volume",
    "enable_spread_monitoring",
    "max_spread_bps",
    "allow_revealed_reprice",
    "post_only_required",
    "converge_to_target",
    "inherit_to_follow_ups",
)
# Files that are ALLOWED to read these fields by name:
#   - models.py owns the canonical normalizer
#   - test files reference them in fixtures and assertions
_ALLOWED_SUFFIXES = ("core/models.py",)


def _allowed(path: Path) -> bool:
    posix = path.as_posix()
    if "/tests/" in posix or posix.endswith("/conftest.py"):
        return True
    return any(posix.endswith(s) for s in _ALLOWED_SUFFIXES)


def test_no_inline_policy_field_access_outside_canonical_module():
    """Catch new ``policy.get(\"<field>\")`` / ``policy[\"<field>\"]`` regressions.

    Forces every new consumer through ``RepricingPolicy`` instead of
    re-introducing the magic-string duplications we just removed.
    """
    repo_root = Path(__file__).resolve().parents[2]
    pattern = re.compile(
        r'(?:policy)\s*(?:\.get\(\s*[\"\'](?P<g>{f})[\"\']|\[\s*[\"\'](?P<i>{f})[\"\'])'.format(
            f="|".join(_GUARDED_FIELDS)
        )
    )

    offenders = []
    for path in repo_root.rglob("*.py"):
        # Skip virtualenvs, generated test worktrees, artifacts, and third-party.
        relative_parts = path.relative_to(repo_root).parts
        if any(
            part
            in {
                ".venv",
                "venv",
                "site-packages",
                "__pycache__",
                ".git",
                ".pytest_cache",
                "build",
                "dist",
                "genai_tools",
                "artifacts",
                "node_modules",
            }
            for part in relative_parts
        ):
            continue
        if _allowed(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Inline RepricingPolicy field access detected. Use "
        "RepricingPolicy.coerce(...).<field> instead.\n  "
        + "\n  ".join(offenders)
    )
