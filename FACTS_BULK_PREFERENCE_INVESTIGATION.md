# Facts System Bulk Preference Statement Failure Investigation

## Executive Summary

**CRITICAL BUG IDENTIFIED:** The value parsing logic in the safety net (and LLM fallback) does NOT correctly handle comma-separated lists with "and" before the last item.

**Example:** "Spain, Greece, and Thailand" is parsed as `['spain', 'greece', 'and thailand']` instead of `['spain', 'greece', 'thailand']`.

**Root Cause:** When splitting on commas and stripping whitespace, " and thailand" becomes "and thailand" (no leading space). The code then checks for `' and '` (space-and-space) in "and thailand", which returns False.

**Impact:** This causes the safety net to fail silently, producing invalid values that likely cause canonicalization or ops creation to fail.

**Fix Required:** Update value parsing to handle parts that start with "and " (without leading space) OR check for "and" before stripping.

## Problem Statement

**User Message:** "My favorite vacation destinations are Spain, Greece, and Thailand."

**Expected Behavior:** System should treat this as an append-many operation, adding Spain, Greece, and Thailand to the existing ranked list (if any) or creating a new ranked list.

**Actual Behavior:** System returns "I couldn't extract any facts from that message. Please try rephrasing." (Facts-F error)

## System Architecture Overview

The Facts write path follows this flow:

```
User Message
  ↓
chat_with_smart_search()
  ↓
Nano Router (route_with_nano) - MANDATORY FIRST STEP
  ↓
  ├─→ If routing_plan.content_plane == "facts" AND routing_plan.operation == "write"
  │     ↓
  │   persist_facts_synchronously()
  │     ↓
  │   Multiple Paths (in order):
  │     1. Safety Net (runs FIRST, regardless of routing candidate)
  │     2. Routing Candidate Path (if routing_plan_candidate exists AND ops_response is None)
  │     3. LLM Extractor Path (if ops_response is still None)
  │     ↓
  │   apply_facts_ops() - Applies operations to database
  │     ↓
  │   Returns PersistFactsResult with store_count, update_count, etc.
  │
  └─→ If routing_plan is None OR not facts/write
        ↓
      Skip Facts persistence (goes to Index/GPT-5)
```

## Critical Failure Points Analysis

### Failure Point 1: Nano Router Not Detecting Pattern

**Location:** `server/services/nano_router.py`

**Condition:** Router must detect "My favorite vacation destinations are Spain, Greece, and Thailand." as a facts/write operation.

**Router Prompt Rules:**
- RULE 1 checks for: "favorite" + topic + "is/are" + value(s)
- Should set: `content_plane="facts"`, `operation="write"`
- Should populate: `facts_write_candidate` with topic="vacation destinations", value=["Spain", "Greece", "Thailand"], rank_ordered=true

**Potential Issues:**
1. **Router not recognizing multi-word topics:** The prompt says "extract the topic word" but "vacation destinations" is two words. The router might extract only "vacation" or "destinations" incorrectly.
2. **Router not parsing "and" correctly:** The message has "Spain, Greece, and Thailand" - router needs to handle the "and" before "Thailand".
3. **Router returning wrong content_plane/operation:** Router might route to "chat" or "index" instead of "facts/write".

**Detection:** Check logs for:
```
[NANO-ROUTING] Routing plan check: content_plane=..., operation=...
[NANO-ROUTING] ⚠️ CRITICAL: User message contains 'My favorite' pattern but router returned content_plane=..., operation=...
```

### Failure Point 2: persist_facts_synchronously Not Being Called

**Location:** `server/services/chat_with_smart_search.py:801`

**Condition:** 
```python
if thread_id and project_id and routing_plan and routing_plan.content_plane == "facts" and routing_plan.operation == "write":
```

**Potential Issues:**
1. `thread_id` is None or empty
2. `project_id` is None or empty
3. `routing_plan` is None
4. `routing_plan.content_plane != "facts"`
5. `routing_plan.operation != "write"`

**Detection:** Check logs for:
```
[NANO-ROUTING] routing_plan is None - cannot execute Facts write
[FACTS] ✅ Facts persistence enabled: thread_id=..., project_id=...
```

### Failure Point 3: Safety Net Not Running or Failing

**Location:** `server/services/facts_persistence.py:436`

**Condition:** Safety net runs FIRST, before any other path:
```python
if is_bulk_preference_without_rank(message_content):
    # Direct conversion logic
```

**is_bulk_preference_without_rank() Function:**
- Checks for explicit rank patterns (e.g., "#4", "fourth") - should return False if found
- Checks for bulk patterns:
  - `r'my\s+favorite\s+\w+(?:\s+\w+)*\s+are\s+'` - "my favorite X are ..."
  - `r'my\s+favorites\s+are\s+'` - "my favorites are ..."
  - `r'my\s+favorite\s+\w+(?:\s+\w+)*\s+is\s+[^,]+,\s+'` - "my favorite X is A, B, C"

**Potential Issues:**
1. **Regex not matching:** The pattern might not match "My favorite vacation destinations are Spain, Greece, and Thailand."
   - Pattern expects: `my favorite [topic] are [values]`
   - Message has: "My favorite vacation destinations are Spain, Greece, and Thailand."
   - Issue: Pattern `\w+(?:\s+\w+)*` should match "vacation destinations" (multi-word topic)
   - BUT: The pattern might be too greedy or not matching correctly

2. **Topic extraction failing:** The safety net uses this regex:
   ```python
   r'my\s+favorite\s+(\w+(?:\s+\w+)*?)\s+(?:are|is)\s+(.+)'
   ```
   - Should extract: topic="vacation destinations", values="Spain, Greece, and Thailand."
   - If regex doesn't match, `topic_match` is None, and safety net silently fails

3. **Value parsing failing:** After extracting values_str="Spain, Greece, and Thailand.", the parsing logic:
   ```python
   parts = [p.strip() for p in values_str.split(',')]
   for part in parts:
       if ' and ' in part:
           and_parts = [p.strip() for p in part.split(' and ', 1)]
           values.extend([p for p in and_parts if p])
   ```
   - Should produce: ["Spain", "Greece", "Thailand"]
   - If parsing fails, `values` is empty, and safety net fails

4. **Canonicalization failing:** `canonicalize_topic("vacation destinations")` might fail or return an error
   - If canonicalization throws exception, safety net logs error but continues to next path

5. **Exception during ops creation:** If any exception occurs during FactsOp creation, safety net fails silently

**Detection:** Check logs for:
```
[FACTS-PERSIST] 🔒 SAFETY NET: Bulk preference statement detected - attempting direct conversion: '...'
[FACTS-PERSIST] 🔒 SAFETY NET: Extracted topic='...', values_str='...'
[FACTS-PERSIST] 🔒 SAFETY NET: Parsed X values: [...]
[FACTS-PERSIST] 🔒 SAFETY NET: Canonicalizing topic '...'...
[FACTS-PERSIST] 🔒 SAFETY NET: Canonicalized '...' → '...', list_key='...'
[FACTS-PERSIST] ✅ SAFETY NET: Direct conversion successful - X append ops for topic '...' (values: [...])
[FACTS-PERSIST] ❌ SAFETY NET: Direct conversion failed: ...
[FACTS-PERSIST] 🔒 SAFETY NET: Regex did not match message: '...'
```

### Failure Point 4: Routing Candidate Path Failing

**Location:** `server/services/facts_persistence.py:524`

**Condition:** 
```python
if routing_plan_candidate and not ops_response:
    ops_response, canonicalization_result = _convert_routing_candidate_to_ops(...)
```

**Potential Issues:**
1. **routing_plan_candidate is None:** Router didn't create a candidate
2. **ops_response already set:** Safety net already created ops_response, so this path is skipped
3. **_convert_routing_candidate_to_ops() failing:** Exception during conversion
   - Canonicalization might fail
   - List key generation might fail
   - Ops creation might fail

**Detection:** Check logs for:
```
[FACTS-PERSIST] Using routing plan candidate (topic=..., value=..., rank_ordered=...), skipping Facts LLM call
[FACTS-PERSIST] Canonicalized topic: '...' → '...'
[FACTS-PERSIST] Failed to convert routing candidate to ops: ...
```

### Failure Point 5: LLM Extractor Path Failing

**Location:** `server/services/facts_persistence.py:551`

**Condition:** 
```python
if not ops_response:
    # LLM extractor path
```

**Potential Issues:**
1. **LLM extractor not being called:** If ops_response is already set (from safety net or routing candidate), this path is skipped
2. **LLM extractor returning empty ops:** LLM might return `{"ops": [], "needs_clarification": []}`
3. **LLM extractor throwing exception:** FactsLLMTimeoutError, FactsLLMUnavailableError, etc.
4. **JSON parsing failing:** Invalid JSON response from LLM
5. **Force-extraction retry also failing:** Even the retry with stricter prompt fails

**Detection:** Check logs for:
```
[FACTS-PERSIST] Calling Facts LLM (GPT-5 Nano) for message (message_uuid=...)
[FACTS-PERSIST] ❌ Facts LLM (GPT-5 Nano) timed out: ...
[FACTS-PERSIST] ⚠️ Write-intent message but first pass returned empty ops. Retrying with force-extraction prompt
[FACTS-PERSIST] ✅ Force-extraction retry returned X ops
```

### Failure Point 6: Operations Not Being Applied

**Location:** `server/services/facts_persistence.py:887`

**Condition:** 
```python
apply_result = apply_facts_ops(
    project_uuid=project_id,
    message_uuid=message_uuid,
    ops_response=ops_response,
    source_id=source_id
)
```

**Potential Issues:**
1. **ops_response is None or empty:** No operations to apply
2. **apply_facts_ops() returning 0 counts:** Operations are created but not applied
   - Duplicate prevention might be blocking all operations
   - Invariant validation might be failing
   - Database transaction might be rolling back
3. **Exception during apply:** apply_facts_ops() might throw exception

**Detection:** Check logs for:
```
[FACTS-APPLY] ✅ Applied operations: S=X U=Y keys=Z errors=0
[FACTS-APPLY] ❌ Ranked list invariant violation for '...': ...
[FACTS-APPLY] Duplicate blocked: '...' already exists at rank X for topic=...
```

### Failure Point 7: Response Handling in chat_with_smart_search

**Location:** `server/services/chat_with_smart_search.py:993`

**Condition:**
```python
if store_count > 0 or update_count > 0 or duplicate_blocked:
    # Return success confirmation
else:
    # Return Facts-F error
```

**Potential Issues:**
1. **store_count == 0 AND update_count == 0 AND duplicate_blocked is None/empty:** All operations failed or were blocked
2. **duplicate_blocked not being checked correctly:** The condition checks `if duplicate_blocked:` but duplicate_blocked might be an empty dict `{}` which is falsy

**Detection:** Check logs for:
```
[FACTS] ⚠️ Write-intent message but Facts-S/U returned 0 counts. This may indicate GPT-5 Nano didn't extract facts or an error occurred.
[FACTS] ⚠️ Routing plan said facts/write but Facts-S/U returned 0 counts. Returning Facts-F instead of falling through to Index/GPT-5.
```

## CRITICAL BUG FOUND: Value Parsing Issue

**Location:** `server/services/facts_persistence.py:459-466` (Safety Net) and `server/services/facts_persistence.py:574-585` (LLM Fallback)

**Problem:** The value parsing logic does NOT correctly handle "Spain, Greece, and Thailand."

**Current Logic:**
```python
parts = [p.strip() for p in values_str.split(',')]
for part in parts:
    if ' and ' in part:
        and_parts = [p.strip() for p in part.split(' and ', 1)]
        values.extend([p for p in and_parts if p])
    else:
        if part:
            values.append(part)
```

**Test Result:**
- Input: "spain, greece, and thailand"
- Output: `['spain', 'greece', 'and thailand']` ❌
- Expected: `['spain', 'greece', 'thailand']` ✅

**Root Cause:** When splitting "spain, greece, and thailand" on commas, we get:
- "spain"
- "greece"  
- " and thailand"

The code checks if `' and '` (with spaces) is in " and thailand", which it is, but the split produces `["", "thailand"]`. After filtering empty strings, we should get `["thailand"]`, but the code is not handling this correctly.

**Confirmed Bug:** 

When splitting "spain, greece, and thailand" on commas:
- Before strip: `["spain", " greece", " and thailand"]`
- After strip: `["spain", "greece", "and thailand"]` ← Leading space removed!

Then the code checks `' and ' in "and thailand"` which is **False** because there's no space before "and" after stripping.

**FIX NEEDED:** Check for `' and '` BEFORE stripping, OR also check for parts that start with `"and "` (without leading space).

**Corrected Logic:**
```python
parts = [p.strip() for p in values_str.split(',')]
for part in parts:
    if part:
        # Check for "and " at the start OR " and " anywhere
        if part.startswith('and ') or ' and ' in part:
            # Split on "and " (with or without leading space)
            if part.startswith('and '):
                and_parts = [p.strip() for p in part.split('and ', 1)]
            else:
                and_parts = [p.strip() for p in part.split(' and ', 1)]
            values.extend([p for p in and_parts if p])
        else:
            values.append(part)
```

## Most Likely Root Causes

Based on the code analysis, here are the most likely failure scenarios:

### Scenario 1: Router Not Routing to Facts/Write
**Probability: HIGH**

The Nano Router might not be recognizing "My favorite vacation destinations are Spain, Greece, and Thailand." as a facts/write operation. Possible reasons:
- Router prompt doesn't handle multi-word topics well
- Router might be extracting topic incorrectly (e.g., only "vacation" instead of "vacation destinations")
- Router might be routing to "chat" or "index" instead of "facts/write"

**If this happens:** `persist_facts_synchronously()` is never called, so all the safety nets are bypassed.

### Scenario 2: Safety Net Regex Not Matching
**Probability: MEDIUM**

The safety net regex `r'my\s+favorite\s+(\w+(?:\s+\w+)*?)\s+(?:are|is)\s+(.+)'` might not be matching the message correctly. The non-greedy `*?` might be causing issues, or the pattern might not handle the specific structure of "vacation destinations".

**If this happens:** Safety net silently fails, falls through to routing candidate or LLM extractor.

### Scenario 3: Safety Net Running But Failing Silently
**Probability: MEDIUM**

The safety net might be running, extracting topic and values correctly, but then failing during:
- Canonicalization (exception thrown, caught, logged as warning)
- Ops creation (exception thrown, caught, logged as warning)
- The exception is caught and logged, but `ops_response` remains None

**If this happens:** Check logs for `[FACTS-PERSIST] ❌ SAFETY NET: Direct conversion failed: ...`

### Scenario 4: All Operations Blocked by Duplicate Prevention
**Probability: LOW**

If all three values (Spain, Greece, Thailand) already exist in the ranked list, duplicate prevention would block all operations. However, `duplicate_blocked` should be populated, and the success condition should still trigger.

**If this happens:** Check logs for `[FACTS-APPLY] Duplicate blocked: ...`

## Debugging Steps

To identify the exact failure point, check the logs in this order:

1. **Check if router detected the pattern:**
   ```
   [NANO-ROUTING] Routing plan check: content_plane=..., operation=...
   [NANO-ROUTING] Facts write candidate: topic=..., value=..., rank_ordered=...
   ```

2. **Check if persist_facts_synchronously was called:**
   ```
   [FACTS] ✅ Facts persistence enabled: thread_id=..., project_id=...
   [FACTS-PERSIST] 🔒 SAFETY NET: Bulk preference statement detected - attempting direct conversion: '...'
   ```

3. **Check safety net execution:**
   ```
   [FACTS-PERSIST] 🔒 SAFETY NET: Extracted topic='...', values_str='...'
   [FACTS-PERSIST] 🔒 SAFETY NET: Parsed X values: [...]
   [FACTS-PERSIST] ✅ SAFETY NET: Direct conversion successful - X append ops
   ```

4. **Check routing candidate path:**
   ```
   [FACTS-PERSIST] Using routing plan candidate (topic=..., value=..., rank_ordered=...)
   ```

5. **Check LLM extractor path:**
   ```
   [FACTS-PERSIST] Calling Facts LLM (GPT-5 Nano) for message (message_uuid=...)
   ```

6. **Check apply results:**
   ```
   [FACTS-APPLY] ✅ Applied operations: S=X U=Y keys=Z errors=0
   [FACTS-PERSIST] ✅ Persisted facts: S=X U=Y keys=Z (message_uuid=...)
   ```

7. **Check final response:**
   ```
   [FACTS] ⚠️ Routing plan said facts/write but Facts-S/U returned 0 counts. Returning Facts-F instead of falling through to Index/GPT-5.
   ```

## Code Flow Diagram

```
User: "My favorite vacation destinations are Spain, Greece, and Thailand."
  ↓
chat_with_smart_search()
  ↓
route_with_nano()
  ├─→ Returns RoutingPlan
  │     ├─→ content_plane = "facts" ? ✅ or ❌
  │     ├─→ operation = "write" ? ✅ or ❌
  │     └─→ facts_write_candidate populated? ✅ or ❌
  ↓
if routing_plan.content_plane == "facts" AND routing_plan.operation == "write":
  ↓
persist_facts_synchronously()
  ↓
SAFETY NET (runs FIRST):
  ├─→ is_bulk_preference_without_rank() → True ✅ or False ❌
  ├─→ Regex match: r'my\s+favorite\s+(\w+(?:\s+\w+)*?)\s+(?:are|is)\s+(.+)'
  │     ├─→ Matches? ✅ or ❌
  │     ├─→ topic = "vacation destinations" ✅ or ❌
  │     └─→ values_str = "Spain, Greece, and Thailand." ✅ or ❌
  ├─→ Parse values: ["Spain", "Greece", "Thailand"] ✅ or ❌
  ├─→ canonicalize_topic("vacation destinations") → "vacation_destination" ✅ or ❌
  ├─→ Create FactsOp for each value (rank=None) ✅ or ❌
  └─→ ops_response = FactsOpsResponse(ops=[...]) ✅ or ❌
  ↓
if routing_plan_candidate AND not ops_response:
  ├─→ _convert_routing_candidate_to_ops() ✅ or ❌
  └─→ ops_response = ... ✅ or ❌
  ↓
if not ops_response:
  ├─→ Call Facts LLM extractor ✅ or ❌
  ├─→ Parse JSON response ✅ or ❌
  └─→ ops_response = FactsOpsResponse(...) ✅ or ❌
  ↓
if not ops_response:
  └─→ Return error (store_count=-1, update_count=-1) ❌
  ↓
apply_facts_ops(ops_response)
  ├─→ For each op:
  │     ├─→ Check duplicate (if unranked append) ✅ or ❌
  │     ├─→ Assign rank atomically (if rank=None) ✅ or ❌
  │     └─→ Insert into database ✅ or ❌
  ├─→ Validate ranked list invariants ✅ or ❌
  └─→ Return ApplyResult(store_count=X, update_count=Y) ✅ or ❌
  ↓
if store_count > 0 OR update_count > 0 OR duplicate_blocked:
  └─→ Return success confirmation ✅
else:
  └─→ Return "I couldn't extract any facts..." ❌
```

## Recommendations

1. **Add comprehensive logging at each failure point** to identify exactly where the flow breaks
2. **Test the safety net regex independently** to verify it matches the message
3. **Test the router prompt** to verify it routes bulk preference statements correctly
4. **Add defensive checks** to ensure safety net always runs, even if router fails
5. **Verify duplicate_blocked handling** - ensure empty dict `{}` is treated as falsy correctly
6. **Add telemetry** to track which path (safety net, routing candidate, LLM) actually executed

## Key Files to Inspect

1. **server/services/nano_router.py** - Router prompt and pattern matching
2. **server/services/facts_persistence.py** - Safety net, routing candidate conversion, LLM extractor
3. **server/services/facts_apply.py** - Operation application and duplicate prevention
4. **server/services/chat_with_smart_search.py** - Response handling and error messages

## Test Cases to Verify

1. **Router Detection:**
   - Input: "My favorite vacation destinations are Spain, Greece, and Thailand."
   - Expected: `content_plane="facts"`, `operation="write"`, `facts_write_candidate.topic="vacation destinations"`, `facts_write_candidate.value=["Spain", "Greece", "Thailand"]`

2. **Safety Net Regex:**
   - Input: "My favorite vacation destinations are Spain, Greece, and Thailand."
   - Expected: topic="vacation destinations", values=["Spain", "Greece", "Thailand"]

3. **Value Parsing:**
   - Input: "Spain, Greece, and Thailand."
   - Expected: ["Spain", "Greece", "Thailand"]

4. **Canonicalization:**
   - Input: "vacation destinations"
   - Expected: canonical_topic="vacation_destination" (or similar)

5. **Ops Creation:**
   - Input: topic="vacation_destination", values=["Spain", "Greece", "Thailand"]
   - Expected: 3 FactsOp objects with `rank=None`, `list_key="user.favorites.vacation_destination"`

