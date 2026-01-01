# Alias Matching and Rank Override Fix Summary

## Bugs Fixed
1. **Partial/alias values not matching**: "rogue one" didn't match existing "Star Wars: Rogue One", causing duplicates or failed moves
2. **Rank directives ignored**: "#2 favorite" was defaulting to rank 1 or being ignored by router/LLM

## Root Causes
1. **No fuzzy/alias matching**: Only exact normalized matches were checked, so partial values like "rogue one" couldn't find "Star Wars: Rogue One"
2. **Rank extraction not honored**: Router/LLM could override user's explicit rank directive (#2), defaulting to rank 1

## Fixes Applied

### 1. Alias/Fuzzy Matching (`resolve_ranked_item_target`)
- Created `resolve_ranked_item_target()` function for fuzzy/alias matching
- **Token-based matching**:
  - Normalizes both new value and existing items
  - Tokenizes into word sets (excludes stop words and very short words)
  - Computes subset score: `|intersection| / |tokens_new|` (all tokens from new value found in existing = perfect match)
  - Uses Jaccard similarity as tie-breaker
  - Threshold: subset score == 1.0 (perfect) OR score >= 0.85 (good match)
- **Examples**:
  - "rogue one" → matches "Star Wars: Rogue One" (all tokens found)
  - "breath of the wild" → matches "The Legend of Zelda: Breath of the Wild"
  - "matrix" → matches "The Matrix" (subset score = 1.0)

### 2. Updated Mutation Logic
- `_apply_ranked_mutation()` now uses `resolve_ranked_item_target()` to find matches
- If fuzzy match found, treats as MOVE of existing item (not INSERT)
- Uses canonical value from matched item for storage (preserves full title)
- Removes ALL duplicates before mutation (prevents duplicates)

### 3. Rank Override Enforcement
- **Enhanced rank extraction**: `detect_ordinal_rank()` now:
  - Removed 10 limit (allows ranks 1-1000 for mutations)
  - Verifies "#N" is in "favorite" context to avoid false positives
- **Final override in facts_persistence.py**:
  - Extracts rank from user text (#N) as final override
  - Router/LLM cannot break it - user text is source of truth
  - Logs warning when override happens: "RANK OVERRIDE: LLM/router extracted rank=X but user text specifies rank=Y. OVERRIDING to user-specified rank."
- **Defensive check in apply path**: Logs if rank=1 is used in mutation context (should only happen if user explicitly said "#1")

### 4. Enhanced Logging
- Alias matches logged: `[FACTS-APPLY] Alias/fuzzy match: 'rogue one' → 'Star Wars: Rogue One' (rank 8, score=1.234)`
- Rank overrides logged: `[FACTS-PERSIST] RANK OVERRIDE: LLM/router extracted rank=1 but user text specifies rank=2. OVERRIDING...`

## Tests Added

### `test_alias_move_star_wars_rogue_one`
- Seeds: [Interstellar, The Matrix, Arrival, Blade Runner 2049, Dune (2021), Alien, Ex Machina, Star Wars: Rogue One, Edge of Tomorrow]
- Mutation: "My #2 favorite sci-fi movies is rogue one."
- Asserts:
  - Action is MOVE (not INSERT) - alias matching worked
  - Old rank = 8, new rank = 2 - rank directive honored
  - No duplicates created
  - Final list has "Star Wars: Rogue One" at rank 2

### `test_rank_override_from_user_text`
- Seeds: [Item1, Item2, Item3]
- Mutation: "My #2 favorite test item is NewItem."
- Asserts:
  - NewItem is at rank 2 (NOT rank 1)
  - Final list: [Item1, NewItem, Item2, Item3]
  - Rank directive (#2) is honored

### `test_alias_move_breath_of_the_wild`
- Seeds list with "The Legend of Zelda: Breath of the Wild" at rank 5
- Mutation: "My #1 favorite game is breath of the wild."
- Asserts: Zelda game moved to rank 1, no duplicate

### `test_resolve_ranked_item_target_unit`
- Unit test for alias matching function
- Tests exact match, partial match, case-insensitive, no match

## Files Modified
- `server/services/facts_apply.py`: Added `resolve_ranked_item_target()`, `_tokenize_normalized()`, updated `_apply_ranked_mutation()`
- `server/services/facts_persistence.py`: Enhanced rank override with warning logs
- `server/services/ordinal_detection.py`: Removed 10 limit, added context verification for "#N" patterns
- `server/tests/test_facts_alias_matching.py`: Regression tests

## Done Criteria
- ✅ Partial/alias values (e.g., "rogue one") match full canonical items (e.g., "Star Wars: Rogue One")
- ✅ Rank directives (#N) are ALWAYS honored - router/LLM cannot override
- ✅ "#2 favorite" never becomes rank 1
- ✅ All regression tests pass
- ✅ Existing rank mutation tests still pass

## Manual Verification Steps

1. **Test alias matching:**
   - Seed: "My favorite sci-fi movies are Interstellar, The Matrix, Arrival, Blade Runner 2049, Dune (2021), Alien, Ex Machina, Star Wars: Rogue One, Edge of Tomorrow."
   - Mutate: "My #2 favorite sci-fi movies is rogue one."
   - Should see: "Moved Star Wars: Rogue One to #2 (was #8)."
   - Verify: "Star Wars: Rogue One" is at rank 2, no duplicate

2. **Test rank override:**
   - Seed: "My favorite test items are Item1, Item2, Item3."
   - Mutate: "My #2 favorite test item is NewItem."
   - Should see: "Inserted NewItem at #2." (NOT rank 1)
   - Verify: NewItem is at rank 2, list is [Item1, NewItem, Item2, Item3]

3. **Check logs:**
   - Backend logs should show:
     - `[FACTS-APPLY] Alias/fuzzy match: 'rogue one' → 'Star Wars: Rogue One'...`
     - `[FACTS-PERSIST] RANK OVERRIDE: LLM/router extracted rank=1 but user text specifies rank=2. OVERRIDING...`

