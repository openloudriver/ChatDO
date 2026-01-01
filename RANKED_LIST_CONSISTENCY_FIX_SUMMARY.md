# Ranked-List Consistency Fix Summary

## Bug Fixed
"Breakfast Burritos" appearing at multiple ranks and not respecting "#2 favorite" directive. Item stayed at #5, then mysteriously moved to #1, then wasn't at #1 anymore.

## Root Causes
1. **Duplicate items not removed**: When inserting/moving an item, only the FIRST duplicate was found and removed, not ALL duplicates.
2. **Rank not extracted correctly**: When using Facts LLM path (routing_plan_candidate=None), rank extraction from user message (#2) wasn't being applied if LLM didn't extract it.

## Fixes Applied

### 1. Canonical Normalizer (`normalize_rank_item`)
- Created `normalize_rank_item()` as the single source of truth for ranked item normalization
- Shared by write + apply operations
- Handles: Unicode normalization, smart quotes, whitespace collapse, punctuation stripping, lowercase

### 2. Remove ALL Duplicates Before Mutation
- Updated `_apply_ranked_mutation()` to find ALL occurrences of normalized value (not just first)
- Removes ALL duplicates before inserting/moving
- Prevents "Breakfast Burritos" from appearing at multiple ranks
- Updated shift logic to exclude removed duplicates

### 3. Rank Parsing Fix
- Added fallback rank detection in Facts LLM path
- If user specifies "#2" but LLM extracts rank=1, detect and fix it
- Uses `detect_ordinal_rank()` to extract rank from user message
- Ensures "#2 favorite" inserts at rank 2, not rank 1

### 4. Defensive Deduplication in Facts-R
- Added deduplication in `execute_facts_plan()` retrieval path
- Removes duplicates by normalized form (keeps earliest occurrence)
- Safety net in case duplicates somehow exist in DB

### 5. Debug Logging
- Added comprehensive logging in `_apply_ranked_mutation()`:
  - Before state: current list, desired rank, value
  - Duplicate detection: count and ranks of duplicates
  - After state: final list, action taken
- Logs do not spam (INFO level for mutations, DEBUG for details)

## Tests Added

### `test_breakfast_burritos_duplicate_prevention`
- Seeds: [Pancakes, Omelets, French Toast, Bagels, Breakfast Burritos]
- Mutation: "My #2 favorite weekend breakfast is breakfast burritos."
- Asserts:
  - No duplicates by normalized form
  - Breakfast Burritos appears exactly once
  - Breakfast Burritos is at rank 2
  - Final list: [Pancakes, Breakfast Burritos, Omelets, French Toast, Bagels]

### `test_rank_directive_respects_user_request`
- Seeds: [Pancakes, Omelets, French Toast]
- Mutation: "My #2 favorite weekend breakfast is Waffles."
- Asserts: Waffles is at rank 2 (NOT rank 1)

### `test_case_insensitive_duplicate_prevention`
- Seeds with "Breakfast Burritos" (capitalized)
- Mutates with "breakfast burritos" (lowercase)
- Asserts: No duplicate created, item moved correctly

## Files Modified
- `server/services/facts_apply.py`: Duplicate removal, canonical normalizer, debug logging
- `server/services/facts_retrieval.py`: Defensive deduplication
- `server/services/facts_persistence.py`: Rank extraction fallback in LLM path
- `server/tests/test_facts_ranked_list_consistency.py`: Regression tests

## Done Criteria
- ✅ "insert/move" operations never produce duplicates
- ✅ Rank directives (#N) are respected deterministically
- ✅ Breakfast burritos reproduction no longer shows duplicates or "teleporting"
- ✅ All regression tests pass
- ✅ Existing rank mutation tests still pass

## Manual Verification Steps

1. **Seed list:**
   - "My favorite weekend breakfasts are Pancakes, Omelets, French Toast, Bagels, Breakfast Burritos."

2. **Move to #2:**
   - "My #2 favorite weekend breakfast is breakfast burritos."
   - Should see: "Moved breakfast burritos to #2 (was #5)."
   - Verify list shows Breakfast Burritos at rank 2

3. **Check for duplicates:**
   - "List my favorite weekend breakfasts"
   - Verify Breakfast Burritos appears exactly once at rank 2
   - Verify no duplicates in the list

4. **Check logs:**
   - Backend logs should show:
     - `[FACTS-APPLY] Found N duplicate(s) of 'breakfast burritos'... Removing all duplicates before mutation.`
     - `[FACTS-APPLY] Rank mutation MOVE: 'breakfast burritos' from rank 5 to 2...`

