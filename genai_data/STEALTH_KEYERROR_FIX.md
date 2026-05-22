# Fix: Stealth Order KeyError and Target Movement Inheritance

**Date:** 2026-04-20  
**Status:** ✅ FIXED

## Problem

Users encountered a KeyError for `'side'` during stealth order follow-up creation:

```json
{
  "error": "'side'",
  "event": "stealth_follow_up_creation_exception",
  "filled_order_id": "5f948910-b5a0-4c75-a518-979006f375ad"
}
```

Despite this error, child stealth orders were still being created successfully by a fallback code path, but:
1. The error was being logged (noise in logs)
2. Target_movement was NOT being passed to child orders (they weren't inheriting parent's profit targets)

## Root Cause

The codebase had TWO separate code paths attempting to handle stealth order follow-ups:

1. **Early path (lines ~1509-1573)** - NEW code added for stealth follow-up detection
   - Attempted to detect and handle stealth reveals immediately
   - Threw KeyError for 'side' in certain conditions
   - Was redundant and conflicting with existing logic

2. **Existing path (lines ~1628-1650)** - Original working code
   - Properly detected stealth orders and created children
   - Did NOT pass target_movement parameters to children
   - Was being reached as a fallback after the early path threw an exception

## Solution

### 1. Removed Redundant Early Code Path
Deleted the redundant stealth follow-up creation code (lines 1509-1573) that was causing the KeyError. The existing code path was already handling all the stealth order logic correctly.

### 2. Enhanced Target Movement Inheritance
Updated the EXISTING stealth follow-up code to properly pass target_movement parameters:

```python
# Get target_movement from parent stealth order for inheritance
parent_target_movement = original_stealth_order.get("target_movement")
parent_target_movement_type = original_stealth_order.get("target_movement_type", "P")

# Pass to child creation
stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(
    ...,
    target_movement=parent_target_movement,
    target_movement_type=parent_target_movement_type
)
```

### 3. Improved Logging
Updated the stealth_follow_up_created event logging to include the proper target_movement dict structure:

```json
{
  "event": "stealth_follow_up_created",
  "parent_target_movement": {
    "movement": 0.004,
    "type": "P"
  },
  ...
}
```

## Files Modified

- **core/order_engine.py**
  - Removed redundant stealth follow-up creation code (lines ~1509-1573)
  - Added target_movement extraction and passing (lines ~1613-1625)
  - Updated logging to show target_movement dict structure (lines ~1628-1642)

## Results

✅ **No more KeyError logs** - Removed the problematic early code path

✅ **Target movement inherited properly** - Child stealth orders now receive parent's target_movement

✅ **Clean logging** - Events logged with correct structure matching actual values

✅ **All tests pass** - Both unit and integration tests verify functionality

## Code Architecture

### Before (Broken)
```
filled_stealth_order
  ↓
  try: early_stealth_path() → KeyError('side')
  except: log error
  ↓ fall through
  → existing_stealth_path() → creates child WITHOUT target_movement ❌
```

### After (Fixed)
```
filled_stealth_order
  ↓
  → existing_stealth_path() → creates child WITH inherited target_movement ✅
```

## Verification

**Test Suite Results:**
- `test_stealth_follow_up.py` ✅ PASSED (16 assertions)
- `test_stealth_integration.py` ✅ PASSED (all scenarios)

**Key Features Verified:**
- ✅ No KeyError exceptions logged
- ✅ Child stealth orders created successfully
- ✅ Target_movement inherited to children
- ✅ Transitive inheritance through chain (Child → Grandchild)
- ✅ Database persistence verified
- ✅ Parent-child relationships properly established

## Impact

**Positive:**
- Eliminates spurious error logs
- Ensures target_movement inheritance throughout order chain
- Cleaner, simpler code path
- Better maintainability (single stealth path vs two competing paths)

**No Breaking Changes:**
- Stealth orders still created correctly
- Parent-child relationships unaffected
- Logging format matches user expectations
- All existing functionality preserved

---

**Summary:** Removed conflicting early stealth order code path and enhanced the existing path to properly inherit target_movement. Tests confirm all functionality works correctly and error logs are eliminated.
