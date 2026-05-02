> Documentation status (2026-05-02): **Archival (historical implementation note)**
> This file records point-in-time analysis or implementation history and may not match current runtime behavior.
> Canonical living docs: genai_data/README.md, genai_data/ARCHITECTURE.md, genai_data/ORDER_ID_HANDLING.md, genai_data/TESTING_STRATEGY.md.
#!/usr/bin/env python3
"""
PARTIAL FILLS - TWO CRITICAL FIXES APPLIED

This document summarizes the fixes for errors encountered after implementing partial fills.

========================================================================================
FIX #1: Schema Migration for Anchor Repricing Columns
========================================================================================

ERROR:
  column "anchor_repricing_policy_json" of relation "stealth_orders" does not exist

LOCATION:
  File: core/stealth_order_manager.py
  Method: __init__ (line ~150)
  Additional method: _ensure_schema_migrations (line ~165)

ROOT CAUSE:
  - Columns `anchor_repricing_policy_json` and `anchor_repricing_state_json` are referenced
    in stealth order UPDATE statements
  - Migration code in database/order.py::create_stealth_orders_table() adds these columns
  - BUT this migration function was only called by __dangerous_delete_all_tables__.py
  - During normal startup, StealthOrderManager didn't trigger the migration

SOLUTION:
  - Added _ensure_schema_migrations() method to StealthOrderManager
  - Called from __init__ to automatically run migrations when manager initializes
  - Uses safe SQL: ALTER TABLE ... ADD COLUMN IF NOT EXISTS (idempotent, can run multiple times)
  - No database reset required

CODE ADDED:
  ```python
  def __init__(self, db_client, ...):
      # ... existing initialization code ...
      self.order_placement_hooks = order_placement_hooks
      
      # Ensure database schema is up to date with all migrations
      self._ensure_schema_migrations()
  
  def _ensure_schema_migrations(self):
      """Ensure stealth_orders table has all required columns including recent migrations."""
      if not self.db_client:
          return
      
      try:
          from database.order import create_stealth_orders_table
          create_stealth_orders_table()
          self.logger.debug("✓ Stealth order schema migration completed")
      except Exception as e:
          self.logger.warning(f"✗ Failed to run schema migration: {type(e).__name__}: {e}")
  ```

IMPACT:
  ✓ Migrations run automatically on startup
  ✓ Safe to deploy - IF NOT EXISTS prevents errors on re-run
  ✓ Fixes missing columns for partial fill anchor repricing

========================================================================================
FIX #2: Duplicate Reveal Event Recording (UPSERT)
========================================================================================

ERROR:
  UniqueViolation: duplicate key value violates unique constraint
  "stealth_order_reveal_history_stealth_order_id_reveal_number_key"
  Key (stealth_order_id, reveal_number)=(42ec9eeb..., 1) already exists.

LOCATION:
  File: core/stealth_order_manager.py
  Method: _record_reveal_event (line ~2176)

ROOT CAUSE:
  - stealth_order_reveal_history table has UNIQUE constraint on (stealth_order_id, reveal_number)
  - _record_reveal_event() used simple INSERT statement
  - In partial fills or race conditions, same reveal event could be processed twice
  - Second attempt failed due to UNIQUE constraint violation

SCENARIOS WHERE DUPLICATES OCCUR:
  1. Race condition: Two threads call reveal_order_slice simultaneously
  2. Retry logic: Order placement retried after temporary failure
  3. Concurrent evaluation: StealthOrderBridge evaluation loop processes same order twice
  4. Database transaction lag: Order reloaded before previous insert committed

SOLUTION:
  - Changed INSERT to UPSERT (INSERT ... ON CONFLICT ... DO UPDATE)
  - PostgreSQL upsert syntax: detects constraint violation and updates instead
  - If same reveal recorded twice, updates record with new data
  - Makes reveal event recording idempotent - safe to retry

CODE CHANGED FROM:
  ```python
  self.db_client.execute_update(
      """INSERT INTO stealth_order_reveal_history
         (stealth_order_id, reveal_number, ..., reveal_trigger_data)
         VALUES (%s, %s, ..., %s)""",
      (stealth_order_id, reveal_number, ..., trigger_data)
  )
  ```

CODE CHANGED TO:
  ```python
  self.db_client.execute_update(
      """INSERT INTO stealth_order_reveal_history
         (stealth_order_id, reveal_number, ..., reveal_trigger_data)
         VALUES (%s, %s, ..., %s)
         ON CONFLICT (stealth_order_id, reveal_number) DO UPDATE SET
             revealed_size = EXCLUDED.revealed_size,
             placement_price = EXCLUDED.placement_price,
             placed_order_id = EXCLUDED.placed_order_id,
             exchange_order_id = EXCLUDED.exchange_order_id,
             market_price = EXCLUDED.market_price,
             market_bid = EXCLUDED.market_bid,
             market_ask = EXCLUDED.market_ask,
             market_spread = EXCLUDED.market_spread,
             market_volume_1m = EXCLUDED.market_volume_1m,
             reveal_trigger_reason = EXCLUDED.reveal_trigger_reason,
             reveal_trigger_data = EXCLUDED.reveal_trigger_data""",
      (stealth_order_id, reveal_number, ..., trigger_data)
  )
  ```

IMPACT:
  ✓ Duplicate reveals no longer cause errors
  ✓ Idempotent recording - safe to retry
  ✓ Handles race conditions gracefully
  ✓ Updates record with latest market data if duplicate occurs

========================================================================================
TESTING
========================================================================================

Two test scripts created to verify the fixes:

1. genai_tools/test_schema_migration_fix.py
   - Verifies anchor repricing columns exist
   - Tests StealthOrderManager initialization
   - Tests order updates with new columns

2. genai_tools/test_reveal_event_upsert_fix.py
   - Tests duplicate reveal event recording
   - Verifies UPSERT updates existing record
   - Confirms no duplicate key errors

RUN TESTS:
  cd e:\coinbase
  python genai_tools/test_schema_migration_fix.py
  python genai_tools/test_reveal_event_upsert_fix.py

========================================================================================
DEPLOYMENT NOTES
========================================================================================

✓ Both fixes are backward compatible
✓ No database reset required
✓ Schema migrations are idempotent (safe to run multiple times)
✓ UPSERT syntax is PostgreSQL standard (supported in all modern versions)
✓ Changes are minimal and focused on the specific issues

NEXT STEPS:
1. Test the fixes with partial fill orders
2. Monitor logs for "stealth_reveal_event_recording_failed" errors
3. Verify stealth_order_reveal_history has correct data

========================================================================================

