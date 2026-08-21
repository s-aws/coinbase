"""Generate a ladder of stealth orders from a single template.

Usage::

    python -m genai_tools.generate_order_ladder input.json count=10 \
        limit_price=+100 \
        reveal_condition.price_threshold=+100 \
        anchor_repricing_policy.max_distance=+100 \
        target_distance=+100 \
        [--out ladder.json] [--seed N]

* ``input.json`` is either a single stealth-order dict or the dashboard
  backup format (``{"orders": [...]}``). When multiple orders are present
  the **first** is used as the template.
* ``count=N`` (required) is how many orders to emit.
* Each remaining argument is ``key=value`` where ``key`` is a dotted path
  into the order dict and ``value`` is one of:

    +N / -N    treat as a per-step delta; output[i] = base + i*delta
    N          absolute literal (every output gets the same value)
    r(N)       random INT in [0, N] inclusive, substituted ONCE before
               sign/delta parsing. Use ``-r(N)`` / ``+r(N)`` for a
               random-magnitude delta. Each ``r(...)`` token is rolled
               independently. Use ``--seed`` for reproducible output.
    rr(N)      per-RUNG jitter: a random INT noise added on top of
               whatever value the field would otherwise have on each
               rung. ``+rr(N)`` adds [0, N], ``-rr(N)`` subtracts [0, N].
               Bare ``rr(N)`` is also additive in [0, N]. Unlike a delta,
               jitter is NOT multiplied by the rung index — it is a
               fresh per-rung noise term applied once. Honors ``--seed``.

  Numeric values may be int or float; the type of the existing field is
  preserved (so an int field stays int).

* Bare keys (no dot) are first looked up at the top level; if missing, the
  template is searched one level deep into nested dicts. Found in exactly
  one place \u2192 used; ambiguous \u2192 error. This is a convenience for things
  like ``target_distance`` which lives under ``anchor_repricing_policy``.

* Each emitted order gets a fresh ``stealth_order_id`` (uuid4) so the file
  is importable without colliding with the source.

Output is written to stdout (pretty JSON) or to ``--out FILE`` if given.

Examples
--------

One-shot ``r(N)`` — pick ONE random drift step for the whole ladder.
The same step (e.g. ``-7``) is then applied as a per-rung delta, so all
10 rungs are evenly spaced::

    python -m genai_tools.generate_order_ladder \
        ui_order_span/BIP-20DEC30-CDE-buy-input.json count=10 \
        "limit_price=-r(15)" \
        target_distance=+50 max_distance=+50 \
        --seed 1 --out ui_order_span/output.json

    # rolled once: r(15) -> 7
    # rung 0  limit_price = base
    # rung 1  limit_price = base - 7
    # rung 2  limit_price = base - 14
    # ...
    # rung 9  limit_price = base - 63

Per-rung ``rr(N)`` — small random noise added FRESH on every rung.
Useful for breaking up uniform spacing without changing the overall
ladder shape. Combine with a static delta to get drift + jitter::

    python -m genai_tools.generate_order_ladder \
        ui_order_span/BIP-20DEC30-CDE-buy-input.json count=5 \
        limit_price=-10 "limit_price=-rr(3)" \
        target_distance=+50 max_distance=+50 \
        --seed 1 --out ui_order_span/output.json

    # template limit_price = 76145
    # rung 0  76145 - 10*0 - jitter_0 = 76144  (jitter_0 = 1)
    # rung 1  76145 - 10*1 - jitter_1 = 76135  (jitter_1 = 0)
    # rung 2  76145 - 10*2 - jitter_2 = 76123  (jitter_2 = 2)
    # rung 3  76145 - 10*3 - jitter_3 = 76115  (jitter_3 = 0)
    # rung 4  76145 - 10*4 - jitter_4 = 76102  (jitter_4 = 3)

PowerShell quoting note: bare parens are PowerShell metacharacters,
so any argument containing ``r(...)`` or ``rr(...)`` must be wrapped
in double-quotes — e.g. ``"limit_price=-r(15)"``.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def _load_template(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "orders" in data and isinstance(data["orders"], list):
        if not data["orders"]:
            raise ValueError(f"{path}: 'orders' list is empty")
        return deepcopy(data["orders"][0])
    if isinstance(data, dict):
        return deepcopy(data)
    raise ValueError(f"{path}: expected a dict or a backup with 'orders'")


def _resolve_path(order: Dict[str, Any], key: str) -> List[str]:
    """Return the dotted path to ``key`` inside ``order``.

    * If ``key`` already contains a dot, it's used verbatim and must exist.
    * Otherwise, top-level wins; if absent, search exactly one level deep
      into nested dicts. Multiple matches \u2192 raise.
    """
    if "." in key:
        parts = key.split(".")
        node: Any = order
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                raise KeyError(f"path not found in template: {key}")
            node = node[p]
        return parts

    if key in order:
        return [key]

    matches: List[List[str]] = []
    for top, val in order.items():
        if isinstance(val, dict) and key in val:
            matches.append([top, key])
    if not matches:
        raise KeyError(f"key not found in template (top or one level deep): {key}")
    if len(matches) > 1:
        joined = ", ".join(".".join(m) for m in matches)
        raise KeyError(f"ambiguous key {key!r}; matches: {joined}")
    return matches[0]


def _set_path(order: Dict[str, Any], path: List[str], value: Any) -> None:
    node: Any = order
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


def _get_path(order: Dict[str, Any], path: List[str]) -> Any:
    node: Any = order
    for p in path:
        node = node[p]
    return node


def _parse_number(raw: str) -> Tuple[float, bool]:
    """Return ``(value, is_delta)``. ``+`` / ``-`` prefix \u2192 delta."""
    is_delta = raw.startswith("+") or raw.startswith("-")
    try:
        return float(raw), is_delta
    except ValueError as exc:
        raise ValueError(f"not a number: {raw!r}") from exc


_ONE_SHOT_TOKEN_RE = re.compile(r"(?<!r)r\(\s*(-?\d+)\s*\)")
_PER_RUNG_TOKEN_RE = re.compile(r"rr\(\s*(-?\d+)\s*\)")


def _roll_int(upper: int, raw: str, rng: random.Random) -> int:
    if upper < 0:
        raise ValueError(
            f"random token requires N >= 0, got upper={upper} in {raw!r}"
        )
    return rng.randint(0, upper)


def _expand_random_tokens(raw: str, rng: random.Random) -> str:
    """Substitute every ``r(N)`` token with a random INT in ``[0, N]``.

    ``rr(N)`` tokens (per-rung jitter) are intentionally NOT touched here;
    they are deferred and resolved at ladder-build time.
    Each token is rolled independently. Tokens are rolled BEFORE
    sign/delta parsing, so ``-r(15)`` first becomes e.g. ``-7`` and is
    then parsed as a delta.
    """

    def _sub(match: "re.Match[str]") -> str:
        return str(_roll_int(int(match.group(1)), raw, rng))

    return _ONE_SHOT_TOKEN_RE.sub(_sub, raw)


def _expand_per_rung_tokens(raw: str, rng: random.Random) -> str:
    """Substitute every ``rr(N)`` token. Called once per emitted rung."""

    def _sub(match: "re.Match[str]") -> str:
        return str(_roll_int(int(match.group(1)), raw, rng))

    return _PER_RUNG_TOKEN_RE.sub(_sub, raw)


def _has_per_rung_token(raw: str) -> bool:
    return _PER_RUNG_TOKEN_RE.search(raw) is not None


def _coerce_to_field_type(current: Any, value: float) -> Any:
    """Preserve the field's existing numeric type (int stays int)."""
    if isinstance(current, bool):
        # bool is a subclass of int \u2014 don't silently flip booleans here.
        raise TypeError("refusing to apply numeric delta to a bool field")
    if isinstance(current, int):
        if value != int(value):
            raise ValueError(
                f"non-integer result {value} for int field; "
                "use a different step or change the source field"
            )
        return int(value)
    return float(value)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate_order_ladder",
        description="Generate a ladder of stealth orders from a template.",
    )
    parser.add_argument("input", help="Path to source order JSON or backup file")
    parser.add_argument("--out", default=None, help="Write to file instead of stdout")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for r(N) random substitution (omit for non-deterministic).",
    )
    parser.add_argument(
        "assignments",
        nargs="+",
        help="key=value pairs; one must be count=N",
    )
    return parser.parse_args(argv)


def build_ladder(
    template: Dict[str, Any],
    count: int,
    deltas: Dict[str, Tuple[List[str], float, bool]],
    *,
    rung_jitter: Dict[str, Tuple[List[str], str]] | None = None,
    rng: random.Random | None = None,
) -> List[Dict[str, Any]]:
    """Emit ``count`` orders by applying deltas/absolutes to the template.

    ``deltas[arg_key] = (resolved_path, value, is_delta)`` — values are
    fixed for the whole ladder (already-resolved literals or one-shot
    ``r(N)`` rolls).

    ``rung_jitter[arg_key] = (resolved_path, raw_with_rr_tokens)`` —
    re-rolled per rung. The raw string is parsed for sign:
    ``+`` / ``-`` / no-prefix → jitter sign. The rolled magnitude is
    ADDED to whatever the field already holds on that rung (so any
    static delta on the same key is honored first, and the jitter
    sits on top as small per-rung noise). ``rng`` must be supplied
    when ``rung_jitter`` is non-empty.
    """
    rung_jitter = rung_jitter or {}
    if rung_jitter and rng is None:
        raise ValueError("rng is required when rung_jitter is non-empty")
    out: List[Dict[str, Any]] = []
    for i in range(count):
        order = deepcopy(template)
        # Static deltas / one-shot randoms first.
        for key, (path, value, is_delta) in deltas.items():
            current = _get_path(order, path)
            if is_delta:
                new_val = float(current) + value * i
            else:
                new_val = value
            _set_path(order, path, _coerce_to_field_type(current, new_val))
        # Per-rung jitter applied on top of whatever the field now
        # holds (NOT multiplied by i — this is noise, not drift).
        for path, raw in rung_jitter.values():
            sign = -1.0 if raw.startswith("-") else 1.0
            body = raw.lstrip("+-")
            expanded = _expand_per_rung_tokens(body, rng)  # type: ignore[arg-type]
            try:
                magnitude = float(expanded)
            except ValueError as exc:
                raise ValueError(
                    f"per-rung jitter expression did not resolve to a number: "
                    f"{raw!r} -> {expanded!r}"
                ) from exc
            current = _get_path(order, path)
            new_val = float(current) + sign * magnitude
            _set_path(order, path, _coerce_to_field_type(current, new_val))
        order["stealth_order_id"] = str(uuid.uuid4())
        out.append(order)
    return out


def main(argv: List[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # Split assignments \u2192 count + per-field deltas.
    count: int | None = None
    raw_assignments: List[Tuple[str, str]] = []
    for a in args.assignments:
        if "=" not in a:
            print(f"error: bad assignment {a!r}; expected key=value", file=sys.stderr)
            return 2
        k, v = a.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "count":
            try:
                count = int(v)
            except ValueError:
                print(f"error: count must be an integer, got {v!r}", file=sys.stderr)
                return 2
        else:
            raw_assignments.append((k, v))

    if count is None or count <= 0:
        print("error: count=N (positive integer) is required", file=sys.stderr)
        return 2

    template = _load_template(args.input)

    rng = random.Random(args.seed)

    deltas: Dict[str, Tuple[List[str], float, bool]] = {}
    rung_jitter: Dict[str, Tuple[List[str], str]] = {}
    for k, v in raw_assignments:
        try:
            path = _resolve_path(template, k)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if _has_per_rung_token(v):
            # Per-rung jitter — defer resolution to build_ladder. Any
            # one-shot r(N) tokens in the same string are still rolled
            # ONCE here, so a string like ``-r(15)+rr(2)`` resolves the
            # outer drift now and jitters the rr part each rung.
            try:
                pre = _expand_random_tokens(v, rng)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            rung_jitter[k] = (path, pre)
        else:
            try:
                expanded = _expand_random_tokens(v, rng)
                value, is_delta = _parse_number(expanded)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            deltas[k] = (path, value, is_delta)

    orders = build_ladder(template, count, deltas, rung_jitter=rung_jitter, rng=rng)

    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(orders),
        "orders": orders,
    }
    text = json.dumps(payload, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {len(orders)} orders to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
