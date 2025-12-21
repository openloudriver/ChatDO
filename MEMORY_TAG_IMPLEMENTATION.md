# Memory Tag Implementation: Explicit Multi-Action Format

## Summary

Implemented explicit multi-action Memory tag format that shows exactly what the Memory system did per response, with counts.

## Format

**If no memory actions occurred:**
```
Model: GPT-5
```

**If any memory actions occurred:**
```
Model: Memory-S(n) + Memory-U(n) + Memory-R(n) + GPT-5
```

**Ordering (MANDATORY):**
1. Memory-S(n)
2. Memory-U(n)
3. Memory-R(n)
4. GPT-5

**Inclusion rule:**
- Render only memory tokens with count > 0
- Do not render zero-count tokens
- GPT-5 is always rendered

**Examples:**
- Store only: `Model: Memory-S(3) + GPT-5`
- Retrieve only: `Model: Memory-R(1) + GPT-5`
- Store + Retrieve: `Model: Memory-S(2) + Memory-R(1) + GPT-5`
- Store + Update + Retrieve: `Model: Memory-S(2) + Memory-U(1) + Memory-R(4) + GPT-5`

**Failure Handling:**
```
Model: Memory-F + GPT-5
```
- Memory-F overrides S/U/R
- Still render GPT-5

## Backend Changes

### 1. `store_project_fact()` - Returns action type
- **File**: `memory_service/memory_dashboard/db.py`
- **Change**: Now returns `(fact_id, action_type)` where `action_type` is "store" or "update"
- **Logic**: 
  - "store" = new fact (no existing fact with same fact_key)
  - "update" = existing fact with same fact_key but different value

### 2. Memory Action Tracking
- **File**: `server/services/chat_with_smart_search.py`
- **Tracking**:
  - **S (Store)**: Count of new facts inserted (canonical_topic_key + rank not previously present)
  - **U (Update)**: Count of existing facts updated (same canonical_topic_key + rank, different value)
  - **R (Retrieve)**: Count of distinct canonical topic keys retrieved
  - **F (Failure)**: Boolean indicating any memory pipeline error

### 3. `build_model_label()` - New signature
- **File**: `server/services/chat_with_smart_search.py`
- **New signature**: `build_model_label(used_web: bool, memory_actions: Optional[dict] = None, escalated: bool = True)`
- **Returns**: Formatted model label string

### 4. Response Objects
- All response objects now include `memory_actions` in `meta`:
  ```python
  "meta": {
      "usedWebSearch": bool,
      "usedMemory": bool,
      "memory_actions": {
          "S": int,  # Store count
          "U": int,  # Update count
          "R": int,  # Retrieve count
          "F": bool  # Failure flag
      }
  }
  ```

## Frontend

The frontend already uses `model_label` from the backend directly, so no changes needed. The new format will automatically display.

**Files using model_label:**
- `web/src/components/ChatMessages.tsx` (line 1971-1973)
- `web/src/components/ChatComposer.tsx` (line 1131)
- `web/src/store/chat.ts` (line 32)

## Counting Rules

### Memory-S (Store)
Increment for each new fact row inserted, defined as:
- A new (canonical_topic_key, rank) not previously present

**Example:**
- "My favorite colors are red, white, and blue"
- → Memory-S(3)

### Memory-U (Update)
Increment for each existing fact row whose value changed, defined as:
- Same (canonical_topic_key, rank)
- Different value_text than stored value

**Example:**
- "Actually, my favorite color is green"
- → Memory-U(1)

### Memory-R (Retrieve)
Increment per distinct canonical_topic_key retrieved to answer the question.

**Example:**
- "What are my favorite colors?" (3 ranks returned)
- → Memory-R(1)

**Example:**
- "What are my favorite colors and favorite states?"
- → Memory-R(2)

## Testing

Unit tests should be added for:
1. No memory actions → `Model: GPT-5`
2. Store only → `Model: Memory-S(3) + GPT-5`
3. Retrieve only → `Model: Memory-R(1) + GPT-5`
4. All actions → `Model: Memory-S(2) + Memory-U(1) + Memory-R(4) + GPT-5`
5. Failure → `Model: Memory-F + GPT-5`

## Status

✅ Backend implementation complete
✅ Frontend already compatible (uses model_label directly)
⏳ Unit tests pending

