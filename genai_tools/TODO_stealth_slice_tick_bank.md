# TODO: Stealth Slice Tick-Dust Bank

**Status:** proposed, not scheduled
**Origin:** 2026-04-29 conversation about Decimal vs float quantization in `quantize_to_increment`.
**Inspiration:** Perl-era "bank the leftover bits, withdraw on a later order" pattern (Kahan-style compensated summation generalized across orders in the same campaign).

## Problem

When a stealth parent (e.g. 1.7 contracts, or 0.12345678 BTC) is sliced into N reveals, each slice must be quantized to the product's `base_increment` before placement. Today every slice is independently quantized:

- `direction="down"` → cumulative shortfall (parent never fully fills)
- `direction="up"`   → over-buy (parent overshoots)
- `direction="nearest"` → drift in either direction, non-deterministic

Concrete example: 1.7 contracts split into 5 slices at `base_increment=1` →
`floor(1.7/5) = 0` per slice → parent reveals 0 contracts. Even at `base_increment=0.01` and 7 slices of size `0.01`, dust accumulates fast.

The current `quantize_to_increment` correctly snaps **each individual call** to the tick grid. It does not (and should not) carry residual across calls — that is a campaign-level concern, not a math-helper concern.

## Proposed Design: Per-Stealth Tick Bank

Track residual at the **`stealth_order_id`** scope (the natural campaign boundary).

### Data
New table `stealth_tick_bank` (or column on `stealth_order`):

| column                 | type      | notes                                           |
|------------------------|-----------|-------------------------------------------------|
| `stealth_order_id`     | text PK   | parent campaign                                 |
| `product_id`           | text      | for sanity / debug                              |
| `base_increment`       | numeric   | snapshot at create time (tick size can change)  |
| `dust_remaining`       | numeric   | unspent fractional units, ≥ 0, < base_increment |
| `total_dust_consumed`  | numeric   | audit                                           |
| `updated_at`           | timestamp |                                                 |

### API (in `business/stealth_tick_bank.py`)

```python
@dataclass(frozen=True)
class TickBankAllocation:
    requested_size: Decimal     # what the slicer asked for
    placed_size:    Decimal     # what to actually send to the exchange
    dust_added:     Decimal     # ≥ 0; pulled FROM bank into this slice
    dust_banked:    Decimal     # ≥ 0; rounded-down residual stored back
    bank_after:     Decimal

def allocate_slice(
    *,
    stealth_order_id: str,
    requested: Decimal,
    base_increment: Decimal,
    is_final_slice: bool = False,
) -> TickBankAllocation:
    """Atomically: read bank, add to requested, quantize down, store
    residual back. On final slice, dump entire bank into placed_size
    (still tick-aligned) so parent total exactly matches."""
```

### Properties (must be tested)

1. **Conservation**: for any campaign, `sum(placed_size) == quantize_down(sum(requested))` always; with `is_final_slice=True` on last slice, `sum(placed_size) == sum(requested)` exactly when `sum(requested)` is itself tick-aligned.
2. **Bank never negative.**
3. **Bank always `< base_increment`** between calls.
4. **No over-allocation**: `placed_size <= requested + bank_before`.
5. **Atomicity**: all reads + writes under a single per-`stealth_order_id` lock (use the existing per-key lock pattern, see snapshot-then-act memory note).
6. **Restart-safe**: bank is durable in DB, loaded on engine startup.

## Why NOT Just Use Decimal Everywhere

Decimal already eliminates the *math precision* bug (done — `quantize_to_increment` now uses Decimal). The bank solves a different problem: **the exchange's tick grid is coarser than the user's intent**. Even with infinite math precision, the tick floor still bites. The bank is the only honest answer that avoids both shortfall and overshoot at the campaign level.

## Why Not a Global Bank

- Cross-product dust is meaningless (BTC dust ≠ ETH dust).
- Cross-campaign dust enables theft-by-rounding bugs ("whose dust is this?").
- Per-campaign keying matches the existing `client_order_id` discipline.

## Risk / Unknowns

- Coinbase's `base_increment` can change between reveals (rare, but documented). Snapshot at campaign create and refuse to use a stale bank if increment changes mid-campaign — flush dust to a writeoff log.
- Interaction with partial fills: if a slice partial-fills, the *unfilled* portion should refund to the bank, not double-count. Probably easiest to refund only on terminal cancel, not on each partial.
- Interaction with `total_size` being already-quantized at create time (the new validator in `calculation/size_validation.py`). The bank only needs to handle dust introduced by slice arithmetic, not by the parent's own quantization.

## Out of Scope (explicitly)

- Cross-product dust accounting
- Generic "rounding bank" library — keep it stealth-specific until a second use case appears
- Predicting `base_increment` changes from product metadata refresh

## When To Build

Defer until one of:
- A live campaign demonstrably under-fills a parent by more than one tick due to slice rounding (audit `stealth_order_event` for cumulative `placed_size` vs parent `total_size`)
- A user-visible report ("parent shows 1.7 contracts, only 1.65 placed")
- Slice count grows (more slices = more dust accumulation; current 5-10 slice campaigns rarely matter, 100+ would)

## Reference

- Kahan summation: https://en.wikipedia.org/wiki/Kahan_summation_algorithm
- The Perl precedent (user, ~2010s): "store leftover bits in a bank, recall to round up other orders"
- Memory: `/memories/integrated-by-design-pattern.md` — if built, the bank should follow the dataclass-as-decision-object pattern (see `RevealExecutionPlan`).
