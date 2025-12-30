# Facts System Deep Analysis Report

**Date:** December 30, 2025  
**Status:** After Reverting to Last Working Commit (a0199e7)  
**Issue:** Bulk preference statements failing with "I couldn't extract any facts" error

## Executive Summary

The Facts system has a **fundamental architectural conflict** between two design goals:

1. **Ranked-Mode Protection**: Once a ranked list exists, unranked bulk writes are rejected to prevent accidental overwrites
2. **Append-Many Semantics**: Users expect bulk statements like "My favorite book genres are Sci-Fi, Fantasy, and History" to append items, not replace

**Current Behavior:** When a ranked list already exists, bulk preference statements are **rejected** and should return a clarification message, but instead return "I couldn't extract any facts" (Facts-F error).

## System Architecture

### Flow Diagram

```
User Message: "My favorite book genres are Sci-Fi, Fantasy, and History"
  ↓
chat_with_smart_search()
  ↓
Nano Router (route_with_nano)
  ├─→ Detects: content_plane="facts", operation="write"
  ├─→ Extracts: topic="book genres", value=["Sci-Fi", "Fantasy", "History"]
  └─→ Sets: rank_ordered=true (because multiple values)
  ↓
persist_facts_synchronously()
  ├─→ routing_plan_candidate exists? YES
  │     ↓
  │   _convert_routing_candidate_to_ops()
  │     ├─→ Canonicalize topic: "book genres" → "book_genre"
  │     ├─→ Build list_key: "user.favorites.book_genre"
  │     ├─→ Check: ranked_list_exists? 
  │     │     ├─→ YES: Return FactsOpsResponse(ops=[], needs_clarification=[...])
  │     │     └─→ NO: Create ops with ranks 1, 2, 3...
  │     └─→ Return ops_response
  │
  └─→ routing_plan_candidate missing? (fallback)
        ↓
      Facts LLM Extractor
        └─→ May also fail or return empty ops
  ↓
if ops_response.needs_clarification:
  └─→ Return clarification message ✅
else if ops_response.ops is empty:
  └─→ Return "I couldn't extract any facts" ❌
  ↓
apply_facts_ops() (if ops exist)
  └─→ Apply operations to database
```

## Critical Code Paths

### 1. Nano Router (`server/services/nano_router.py`)

**Function:** `route_with_nano()`

**Behavior:**
- Detects "My favorite X are Y, Z" pattern
- Sets `rank_ordered=true` for multiple values
- Extracts topic and values correctly
- **Status:** ✅ Working as designed

**Example Output:**
```json
{
  "content_plane": "facts",
  "operation": "write",
  "facts_write_candidate": {
    "topic": "book genres",
    "value": ["Sci-Fi", "Fantasy", "History"],
    "rank_ordered": true,
    "rank": null
  }
}
```

### 2. Routing Candidate Conversion (`server/services/facts_persistence.py`)

**Function:** `_convert_routing_candidate_to_ops()` (lines 124-288)

**Critical Logic (lines 214-263):**

```python
elif candidate.rank_ordered:
    # RANKED-MODE PROTECTION: Check if ranked list already exists
    ranked_list_exists = _check_ranked_list_exists(conn, project_id, list_key)
    
    if ranked_list_exists:
        # Ranked list exists - reject unranked bulk write
        return FactsOpsResponse(
            ops=[],
            needs_clarification=[
                f"You already have a ranked list for {canonical_topic}. "
                f"To update it, please specify explicit ranks..."
            ]
        )
    
    # No ranked list exists - allow bulk write with sequential ranks
    start_rank = 1
    for offset, value in enumerate(values):
        rank = start_rank + offset
        ops.append(FactsOp(..., rank=rank, ...))
```

**Problem Identified:**
- When `ranked_list_exists=True`, the function returns `ops=[]` with `needs_clarification`
- This should trigger clarification handling in `chat_with_smart_search.py`
- **But:** If the clarification handling fails or is bypassed, the system falls through to "I couldn't extract any facts"

### 3. Clarification Handling (`server/services/chat_with_smart_search.py`)

**Location:** Lines 893-953

**Current Logic:**
```python
if ambiguous_topics:
    # Check if this is a ranked-list protection message
    is_ranked_list_protection = (
        len(ambiguous_topics) == 1 and 
        ambiguous_topics[0].startswith("You already have a ranked list")
    )
    
    if is_ranked_list_protection:
        clarification_message = ambiguous_topics[0]
        return {
            "response": clarification_message,
            "model": "Facts",
            ...
        }
```

**Potential Issues:**
1. **String Matching:** The check `ambiguous_topics[0].startswith("You already have a ranked list")` may not match the exact message format
2. **Empty Ops Check:** If `ops=[]` and `needs_clarification` is set, but the clarification check fails, the system falls through to the error path
3. **Retrieval Query Check:** There's logic to ignore ambiguity for retrieval queries, which might interfere

### 4. Facts LLM Extractor (Fallback Path)

**Location:** `server/services/facts_persistence.py` lines 416-530

**Behavior:**
- Only called if `routing_plan_candidate` is None or conversion fails
- May also fail to extract facts for bulk statements
- Returns empty ops if extraction fails

## Root Cause Analysis

### PRIMARY ROOT CAUSE: Missing Clarification Message Handler

**Critical Finding:** The clarification message from `_convert_routing_candidate_to_ops()` is **NOT being handled** in `chat_with_smart_search.py`.

**Evidence:**

1. **In `persist_facts_synchronously()` (line 574-593):**
   ```python
   if ops_response and ops_response.needs_clarification:
       ambiguous_topics = ops_response.needs_clarification
       result.ambiguous_topics = ambiguous_topics
       return result  # Returns early with ambiguous_topics set
   ```
   ✅ Correctly sets `result.ambiguous_topics`

2. **In `chat_with_smart_search.py` (line 896-940):**
   ```python
   if ambiguous_topics:
       # Only handles topic ambiguity (multiple candidate topics)
       # Format: "Which favorites list is this for? (topic1 / topic2)"
       topic_display = " / ".join(ambiguous_topics)
       clarification_message = (
           f"Which favorites list is this for? ({topic_display})\n\n"
           f"Please specify the topic..."
       )
   ```
   ❌ **DOES NOT handle ranked-list protection messages!**

3. **The ranked-list protection message format:**
   ```python
   "You already have a ranked list for {canonical_topic}. "
   "To update it, please specify explicit ranks..."
   ```
   This message is **NOT recognized** by the current code, so it falls through to the error path.

**Result:** When a ranked list exists and a bulk write is attempted:
- `_convert_routing_candidate_to_ops()` correctly returns `needs_clarification`
- `persist_facts_synchronously()` correctly sets `ambiguous_topics`
- `chat_with_smart_search.py` checks `if ambiguous_topics:` ✅
- But the clarification message doesn't match the expected format ❌
- Falls through to line 1277: "I couldn't extract any facts" ❌

### Secondary Issue: Ranked-Mode Protection Conflict

The system has **conflicting requirements**:

1. **Requirement A (Ranked-Mode Protection):** Once a ranked list exists, reject unranked bulk writes to prevent accidental overwrites
2. **Requirement B (User Expectation):** Bulk statements like "My favorite book genres are Sci-Fi, Fantasy, and History" should append items, not be rejected

**Current Implementation:**
- Implements Requirement A (rejects bulk writes when ranked list exists)
- Returns `needs_clarification` message
- **But:** Clarification message is not handled, causing fallthrough to error

## Failure Scenarios

### Scenario 1: Ranked List Exists, Bulk Write Attempted

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"  
**State:** Ranked list already exists for "book genres"

**Expected Flow:**
1. Router detects pattern ✅
2. `_convert_routing_candidate_to_ops()` checks for existing ranked list ✅
3. Returns `ops=[], needs_clarification=[...]` ✅
4. `chat_with_smart_search.py` detects clarification ✅
5. Returns clarification message to user ✅

**Actual Flow (Hypothesis):**
1. Router detects pattern ✅
2. `_convert_routing_candidate_to_ops()` checks for existing ranked list ✅
3. Returns `ops=[], needs_clarification=[...]` ✅
4. **Clarification check fails or is bypassed** ❌
5. Falls through to "I couldn't extract any facts" ❌

### Scenario 2: No Ranked List, Bulk Write (First Time)

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"  
**State:** No ranked list exists for "book genres"

**Expected Flow:**
1. Router detects pattern ✅
2. `_convert_routing_candidate_to_ops()` checks for existing ranked list ✅
3. No ranked list exists, creates ops with ranks 1, 2, 3 ✅
4. `apply_facts_ops()` applies operations ✅
5. Returns success confirmation ✅

**Status:** ✅ Should work correctly

### Scenario 3: Router Fails to Detect Pattern

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"  
**State:** Router doesn't detect pattern

**Flow:**
1. Router returns `content_plane="chat"` or `operation="none"` ❌
2. `persist_facts_synchronously()` is never called ❌
3. Falls through to GPT-5 chat response ❌

**Status:** ❌ Would fail silently (no Facts extraction)

## Code Inspection Findings

### 1. Ranked-Mode Protection Logic

**File:** `server/services/facts_persistence.py` lines 214-249

**Issue:** The protection logic is **too strict**. It rejects ALL unranked bulk writes when a ranked list exists, even though the user's intent is to append.

**Current Behavior:**
- If ranked list exists → Reject with clarification
- If no ranked list → Create with ranks 1, 2, 3...

**Problem:** This prevents the append-many semantics that users expect.

### 2. Clarification Message Format

**File:** `server/services/facts_persistence.py` lines 241-248

**Message:**
```
"You already have a ranked list for {canonical_topic}. 
To update it, please specify explicit ranks (e.g., 'My #1 favorite {canonical_topic} is X', 
'My #2 favorite {canonical_topic} is Y'). 
Bulk updates like 'My favorite {canonical_topic} are X, Y, Z' are not allowed once a ranked list exists."
```

**Check in chat_with_smart_search.py:**
```python
is_ranked_list_protection = (
    len(ambiguous_topics) == 1 and 
    ambiguous_topics[0].startswith("You already have a ranked list")
)
```

**Status:** ✅ Should match, but verification needed

### 3. Empty Ops Handling

**File:** `server/services/chat_with_smart_search.py` lines 1312-1364

**Logic:**
```python
if store_count > 0 or update_count > 0 or duplicate_blocked:
    # Return success
else:
    # Check for duplicate_blocked
    if duplicate_blocked:
        # Return duplicate message
    else:
        # Return "I couldn't extract any facts"
```

**Issue:** If `needs_clarification` is set but `ambiguous_topics` check fails, the system falls through to the error path.

## Recommendations

### Immediate Fixes (CRITICAL)

1. **Fix Clarification Message Handler** ⚠️ **REQUIRED**
   - **Location:** `server/services/chat_with_smart_search.py` line 896-940
   - **Problem:** Only handles topic ambiguity, not ranked-list protection messages
   - **Fix:** Add check for ranked-list protection message format:
     ```python
     if ambiguous_topics:
         # Check if this is a ranked-list protection message
         is_ranked_list_protection = (
             len(ambiguous_topics) == 1 and 
             ambiguous_topics[0].startswith("You already have a ranked list")
         )
         
         if is_ranked_list_protection:
             # Return ranked-list protection message directly
             return {
                 "response": ambiguous_topics[0],
                 "model": "Facts",
                 ...
             }
         else:
             # Handle topic ambiguity (existing logic)
             ...
     ```

2. **Add Comprehensive Logging**
   - Log when ranked list exists check is performed
   - Log when clarification is returned
   - Log when clarification check passes/fails
   - Log the exact `ambiguous_topics` value to verify propagation

### Architectural Changes

1. **Re-evaluate Ranked-Mode Protection**
   - Current implementation rejects ALL unranked bulk writes
   - Consider allowing append-many semantics (treat as append, not replace)
   - Only reject if user explicitly tries to replace (e.g., "Replace my favorites with...")

2. **Implement Append-Many Semantics**
   - When `rank_ordered=True` and ranked list exists:
     - Parse values: ["Sci-Fi", "Fantasy", "History"]
     - For each value: check if exists, if not append with rank=max_rank+1
     - Return mixed message: "Added X (#N), Y (#M). Z is already at #K"

3. **Unify Rank Assignment Logic**
   - Currently split between `_convert_routing_candidate_to_ops()` and `apply_facts_ops()`
   - Centralize in `apply_facts_ops()` for consistency
   - Use `rank=None` for all unranked writes, let `apply_facts_ops()` assign atomically

## Test Cases

### Test 1: Bulk Write to Existing Ranked List

**Setup:**
- Existing ranked list: 1. Mystery, 2. Thriller

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"

**Expected (Current):**
- Clarification message: "You already have a ranked list for book genres..."

**Expected (Proposed):**
- Append-many: Add Sci-Fi (#3), Fantasy (#4), History (#5)
- Response: "Added Sci-Fi (#3), Fantasy (#4), History (#5)."

### Test 2: Bulk Write to New Topic

**Setup:**
- No existing ranked list for "book genres"

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"

**Expected:**
- Create ranked list with ranks 1, 2, 3
- Response: "Saved: favorite book genres = [Sci-Fi, Fantasy, History]"

### Test 3: Router Failure

**Input:** "My favorite book genres are Sci-Fi, Fantasy, and History"  
**Router Output:** `content_plane="chat"` (incorrect)

**Expected:**
- Facts LLM extractor should catch this
- Or: Safety net should detect and convert directly

## Conclusion

The Facts system has a **fundamental design conflict** between ranked-mode protection and append-many semantics. The current implementation rejects bulk writes when a ranked list exists, but the clarification message may not be properly propagated to the user, resulting in "I couldn't extract any facts" errors.

**Immediate Action:** Verify clarification message propagation and add comprehensive logging to trace the exact failure point.

**Long-term Solution:** Re-evaluate the ranked-mode protection logic to support append-many semantics while still preventing accidental overwrites.

