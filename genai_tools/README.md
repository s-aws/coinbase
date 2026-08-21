# GenAI Tools Directory

## Purpose

This directory contains debugging and utility source created to understand
system state during investigation and debugging.

Reviewed source is tracked so changes to investigative methods are visible and
revertible. Generated output, browser profiles, database/schema dumps, test
temporary files, captured account data, and credential helpers are ignored.

**Key Point**: These are not production code or design authority. A tracked
file may be historical, stale, destructive, or capable of live exchange or
database mutation. Read the specific file before running it; being tracked is
not approval to execute it.

## When to Create Tools Here

Create debugging tools in this directory when you need to:
- Inspect database state
- Trace data through the system
- Monitor WebSocket messages
- Verify calculations and math
- Check condition evaluation logic
- Validate data integrity

## Example: Debugging Revealed Orders

Scenario: You're investigating why dashboard shows "Avg Reveal %" = 0%

```python
# genai_tools/debug_revealed_orders.py
import sqlite3

conn = sqlite3.connect('coinbase.db')
cursor = conn.cursor()

# Query REVEALED orders
cursor.execute("""
    SELECT
        stealth_order_id,
        product_id,
        total_size,
        revealed_size,
        status
    FROM stealth_orders
    WHERE status = 'REVEALED'
""")

print("REVEALED Orders:")
for row in cursor.fetchall():
    reveal_pct = (row[3] / row[2]) * 100 if row[2] > 0 else 0
    print(f"  {row[0]}: {row[1]} - {row[3]}/{row[2]} units ({reveal_pct:.1f}%)")

conn.close()
```

Run it: `python genai_tools/debug_revealed_orders.py`

This helps you understand:
- ✓ Are there REVEALED orders in the database?
- ✓ What are their revealed_size values?
- ✓ Is the math correct?
- ✓ Does this match what the dashboard shows?

## What NOT to Do

**Don't**:
- Add permanent debugging code to main codebase
- Create tools just to show output (use database queries directly)
- Leave tools here permanently if not needed
- Commit generated output, database dumps, browser profiles, captured account data, or credentials

**Do**:
- Use tools to gather facts
- Document findings in your solution
- Delete tools when no longer needed
- Create new ones freely for each investigation

## File Naming

Name tools clearly so you remember what they do:

```
genai_tools/debug_order_state.py      # Inspect order data
genai_tools/trace_reveal_conditions.py  # Step through condition logic
genai_tools/check_websocket_messages.py # Monitor WebSocket traffic
genai_tools/verify_database_integrity.py # Check DB consistency
```

## Recommended Audit Tool

Use this script when you need to correlate internal order tracking IDs with
exchange IDs during incident response or reveal audits:

`genai_tools/inspect_order_id_correlation.py`

Examples:

```bash
python genai_tools/inspect_order_id_correlation.py --limit 20
python genai_tools/inspect_order_id_correlation.py --client-order-id <uuid>
python genai_tools/inspect_order_id_correlation.py --exchange-order-id <uuid>
python genai_tools/inspect_order_id_correlation.py --json
```

### Reveal Timing Correlation

Use this companion script when auditing whether reveal timing aligns with
recorded market context:

`genai_tools/inspect_reveal_timing_correlation.py`

Examples:

```bash
python genai_tools/inspect_reveal_timing_correlation.py --limit 10
python genai_tools/inspect_reveal_timing_correlation.py --client-order-id <uuid>
python genai_tools/inspect_reveal_timing_correlation.py --exchange-order-id <uuid> --json
```

Note: If no persisted ticker tick table is available, the script uses the best
available evidence: reveal trigger payload, lifecycle event timestamps, and
nearest fill ledger timestamps/prices.

### Focused Lineage Timeline Audit (Chart/Animation Feed)

Use this DB-only script to generate a focused audit pass with:
- A root-to-child lineage map
- Relationship classification per child (`root`, `move_replacement`, `move`, `child_follow_up`)
- A unified event timeline across parent rows, event stream, lifecycle history,
  reveal history, and fill ledger
- Sequence and timestamp deltas for charting/animation

`genai_tools/__order_lineage_timeline_audit__.py`

Examples:

```bash
python genai_tools/__order_lineage_timeline_audit__.py --client-order-id <uuid>
python genai_tools/__order_lineage_timeline_audit__.py --stealth-order-id <uuid>
python genai_tools/__order_lineage_timeline_audit__.py
python genai_tools/__order_lineage_timeline_audit__.py --human
```

Default output mode is JSON for downstream charting/animation pipelines.

## Integration with Debugging Strategy

See [../genai_data/DEBUGGING_STRATEGY.md](../genai_data/DEBUGGING_STRATEGY.md) for how to use these tools as part of the debugging process:

1. Create hypothesis
2. **Write tool to test it** ← You are here
3. Run tool and compare to hypothesis
4. Identify real root cause
5. Implement fix
6. Create regression test
7. Delete or keep the tool (won't hurt either way)

## Examples You Can Use as Templates

### Query Database Pattern
```python
import sqlite3

conn = sqlite3.connect('coinbase.db')
cursor = conn.cursor()

# Your query here
cursor.execute("""SELECT * FROM stealth_orders WHERE ...""")

for row in cursor.fetchall():
    print(row)

conn.close()
```

### Inspect JSON Data Pattern
```python
import json

with open('some_data.json', 'r') as f:
    data = json.load(f)

# Inspect and print
for item in data:
    print(json.dumps(item, indent=2))
```

### Monitor WebSocket Pattern
```python
# Connect to WebSocket and print messages
# See external/coinbase_websocket.py for connection pattern
```

## When You're Done

**Option 1: Delete the tool**
```bash
rm genai_tools/debug_order_state.py
```

**Option 2: Keep it for future use**
- If it's genuinely useful for repeated debugging
- Leave it in `genai_tools/`
- Review it and commit the source; keep its generated output ignored

**Option 3: Generalize it**
- If it's useful enough, move it to proper location
- Add error handling
- Document it properly
- Make it permanent

Most of the time, Option 1 is best: debug, understand, fix, delete.

## Important

Remember: **Facts trump theories.**

When investigating, use these tools to gather facts:
- What's actually in the database?
- What messages are flowing through WebSocket?
- What are the actual values?
- Does this match my hypothesis?

Only implement fixes after facts confirm your understanding.
