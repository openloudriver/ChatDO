# Facts System Rank Assignment Cleanup

**Date**: 2025-12-28  
**Status**: ✅ **COMPLETE - Production Ready**

---

## Executive Summary

Rank assignment logic has been centralized in `apply_facts_ops()`, eliminating pre-check rank guessing in `_convert_routing_candidate_to_ops()`. Unranked appends now emit `rank=None` operations, and `apply_facts_ops()` is the **single source of truth** for rank assignment. Telemetry tracks where each rank came from.

---

## Problem Statement

**Before**: `_convert_routing_candidate_to_ops()` tried to guess the next rank for unranked appends by querying existing facts with `limit=10000`. This:
- Created edge cases for topics with >10,000 facts
- Duplicated rank assignment logic
- Made telemetry confusing (where did the rank come from?)

**After**: `_convert_routing_candidate_to_ops()` emits `rank=None` for unranked appends. `apply_facts_ops()` is the **single source of truth** for rank assignment, using atomic `_get_max_rank_atomic()` within `BEGIN IMMEDIATE` transaction.

---

## Implementation

### 1. Schema Update ✅

**File**: `server/contracts/facts_ops.py:31-35`

```python
rank: Optional[int] = Field(
    None,
    ge=1,
    description="Rank number (1-based) for ranked_list_set operation. Use None for unranked appends (rank will be assigned atomically in apply_facts_ops)."
)
```

**Verification**: ✅ Pydantic correctly allows `rank=None` while enforcing `ge=1` when rank is not None.

---

### 2. _convert_routing_candidate_to_ops() Cleanup ✅

**File**: `server/services/facts_persistence.py:158-183`

**Before**: Queried existing facts with `limit=10000` to guess next rank.

**After**: Emits `rank=None` for unranked appends:

```python
if candidate.rank_ordered:
    # Explicit ordering: use ranks 1, 2, 3...
    for offset, value in enumerate(values):
        rank = start_rank + offset
        ops.append(FactsOp(..., rank=rank, ...))
else:
    # Unranked/FIFO append: emit operations with rank=None
    for value in values:
        ops.append(FactsOp(..., rank=None, ...))  # Rank assigned atomically in apply_facts_ops()
```

**Benefits**:
- ✅ No pre-check limits (avoids edge cases)
- ✅ Centralized rank assignment logic
- ✅ Cleaner code

---

### 3. apply_facts_ops() - Single Source of Truth ✅

**File**: `server/services/facts_apply.py:200-222`

**Implementation**:
```python
# RANK ASSIGNMENT: This is the SINGLE SOURCE OF TRUTH for rank assignment
if op.rank is None:
    # Unranked append: assign rank atomically using _get_max_rank_atomic()
    max_rank = _get_max_rank_atomic(conn, project_uuid, canonical_topic, list_key_for_check)
    assigned_rank = max_rank + 1
    fact_key = canonical_rank_key(canonical_topic, assigned_rank)
    rank_assignment_source = "atomic_append"
else:
    # Explicit rank provided: use it as-is
    assigned_rank = op.rank
    fact_key = canonical_rank_key(canonical_topic, assigned_rank)
    rank_assignment_source = "explicit"

# Store rank assignment source for telemetry
result.rank_assignment_source[fact_key] = rank_assignment_source
```

**Benefits**:
- ✅ All rank assignment happens in one place
- ✅ Atomic within `BEGIN IMMEDIATE` transaction
- ✅ Unbounded max rank query (no limits)
- ✅ Telemetry tracks source

---

### 4. Rank Assignment Source Telemetry ✅

**File**: `server/services/facts_apply.py:86, 96-97, 222`

**ApplyResult Dataclass**:
```python
@dataclass
class ApplyResult:
    rank_assignment_source: Dict[str, str] = None  # Maps fact_key -> "explicit" | "atomic_append"
    
    def __post_init__(self):
        if self.rank_assignment_source is None:
            self.rank_assignment_source = {}
```

**Propagation**:
- ✅ Populated in `apply_facts_ops()` (line 222)
- ✅ Returned from `persist_facts_synchronously()` (7th element of tuple)
- ✅ Included in response meta in `chat_with_smart_search()` (line 1128)

**Example Telemetry**:
```json
{
  "rank_assignment_source": {
    "user.favorites.crypto.1": "explicit",
    "user.favorites.crypto.5": "atomic_append"
  }
}
```

---

### 5. Facts LLM Post-Processing Update ✅

**File**: `server/services/facts_persistence.py:393-409`

**Before**: Detected unranked writes and calculated new rank.

**After**: Detects unranked writes and sets `rank=None`:

```python
# POST-PROCESS: Detect unranked writes and set rank=None for atomic assignment
if op.op == "ranked_list_set" and op.rank == 1 and op.list_key and not has_explicit_rank:
    # This is likely an unranked write - set rank=None for atomic assignment
    op.rank = None
```

**Benefits**:
- ✅ Consistent with routing candidate path
- ✅ All unranked appends go through atomic assignment

---

## Verification

### Schema Validation ✅
- ✅ `rank=None` is valid (for unranked appends)
- ✅ `rank=1` is valid (explicit rank)
- ✅ `rank=0` is rejected (correctly enforces `ge=1`)

### Code Flow ✅
1. ✅ `_convert_routing_candidate_to_ops()` emits `rank=None` for unranked appends
2. ✅ `apply_facts_ops()` handles `rank=None` and assigns ranks atomically
3. ✅ `rank_assignment_source` telemetry populated and propagated
4. ✅ All return statements updated (7-element tuple)

### Compilation ✅
- ✅ All files compile without errors
- ✅ No linter errors

---

## Benefits

1. **Cleaner Architecture**: Single source of truth for rank assignment
2. **No Edge Cases**: Removed pre-check limits that could miss ranks >10,000
3. **Atomic Assignment**: All rank assignment happens within `BEGIN IMMEDIATE` transaction
4. **Clear Telemetry**: Can prove where each rank came from ("explicit" vs "atomic_append")
5. **Simpler Code**: Removed duplicate rank calculation logic

---

## Summary

**Status**: ✅ **COMPLETE**

Rank assignment is now centralized in `apply_facts_ops()`, eliminating pre-check guessing and edge cases. Unranked appends emit `rank=None` operations, and ranks are assigned atomically within transactions. Telemetry tracks the source of each rank assignment.

**Confidence Level**: **HIGH** - All tests pass, code compiles, telemetry complete.

---

**End of Cleanup**

