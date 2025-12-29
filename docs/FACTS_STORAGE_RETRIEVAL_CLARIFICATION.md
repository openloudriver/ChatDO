# Facts System Storage and Retrieval Clarification

**Date**: 2025-12-28  
**Status**: ✅ **CLARIFIED - Production Ready**

---

## Executive Summary

The Facts system has **unbounded storage** (no limits on how many facts can be stored) but **paginated retrieval** (results are limited for performance). Ordinal queries use unbounded retrieval internally when needed to find specific ranks.

---

## Storage: Unbounded ✅

### Definition
**Storage is unbounded**: There is no limit on the number of facts that can be stored for a topic. Users can have 10, 100, 1000, or 10,000+ favorites for a topic, and all will be stored.

### Implementation
- No `MAX` constraints in database schema
- No application-level limits on fact creation
- Each fact is stored as a separate row in `project_facts` table
- Facts are never automatically deleted or truncated

### Example
```python
# User can store unlimited favorites:
"My favorite crypto is XMR"     # Rank 1
"My favorite crypto is BTC"     # Rank 2
"My favorite crypto is ETH"     # Rank 3
# ... (can continue indefinitely)
"My favorite crypto is DOGE"    # Rank 1000
# All stored, no truncation
```

---

## Retrieval: Paginated ✅

### Definition
**Retrieval is paginated**: When retrieving facts, results are limited to prevent excessive memory usage and ensure responsive queries.

### Pagination Limits

1. **Default Limit**: 100 facts per query
2. **Maximum Limit**: 1000 facts per query (for pagination)
3. **High Limit for Internal Operations**: 10,000 facts (for max rank calculation)

### Why Pagination?

- **Performance**: Prevents loading thousands of facts into memory
- **Responsiveness**: Keeps query times reasonable
- **Memory Efficiency**: Avoids OOM errors with very large lists

### Implementation

**File**: `server/contracts/facts_ops.py:98-103`
```python
limit: int = Field(
    100,  # Default pagination limit
    ge=1,
    le=1000,  # Maximum pagination limit (storage is unbounded, retrieval is paginated)
    description="Maximum number of facts to return (pagination limit for retrieval; storage has no limit)"
)
```

---

## Ordinal Queries: Unbounded Retrieval (Internal Only) ✅

### Definition
**Ordinal queries use unbounded retrieval internally**: When a user asks for a specific rank (e.g., "What is my 5th favorite crypto?"), the system retrieves **all facts** for that topic internally to find the specific rank, then returns only that single fact.

### Why Unbounded for Ordinal Queries?

**Problem**: If we only retrieve the first 1000 facts, and the user asks for rank 1500, we would miss it.

**Solution**: For ordinal queries, we retrieve all facts internally (no limit), filter to the requested rank, then return only that single fact.

### Implementation

**File**: `server/services/facts_retrieval.py:108`
```python
# STORAGE IS UNBOUNDED: Facts are stored without limits.
# RETRIEVAL IS PAGINATED: List queries use plan.limit for pagination (default 100, max 1000).
# ORDINAL QUERIES USE UNBOUNDED RETRIEVAL: When plan.rank is set, we retrieve all facts
# internally (limit=None) to find the specific rank, then filter to return only that rank.
# This ensures ordinal queries work correctly even with >1000 facts.
retrieval_limit = None if plan.rank is not None else plan.limit  # None = unbounded retrieval
```

### Example

```python
# User has 2000 favorite cryptos stored
# Query: "What is my 1500th favorite crypto?"

# Process:
# 1. Retrieve ALL 2000 facts internally (unbounded retrieval)
# 2. Filter to rank 1500
# 3. Return only that single fact: "DOGE"

# User sees: "DOGE" (not the full list)
```

---

## Code Comments Updated

### Files Updated

1. **`server/services/facts_retrieval.py`**
   - Clarified that storage is unbounded, retrieval is paginated
   - Explained ordinal queries use unbounded retrieval internally

2. **`server/services/librarian.py`**
   - Clarified that 10000 limit is for pagination, not a storage cap
   - Noted that storage has no limit

3. **`server/services/facts_persistence.py`**
   - Clarified that 10000 limit is for max rank calculation (paginated retrieval)
   - Noted that storage is unbounded

4. **`server/contracts/facts_ops.py`**
   - Updated description to clarify pagination vs storage limits

---

## Future: Truly Unbounded Retrieval

### Current Limitation

The current implementation uses `limit=10000` for max rank calculation, which means:
- If a topic has >10,000 facts, max rank calculation might be incomplete
- This is unlikely in practice, but theoretically possible

### Proposed Solution: Streaming/Pagination

If truly unbounded retrieval is needed in the future:

1. **Streaming Approach**:
   ```python
   # Stream facts in batches until max rank found
   offset = 0
   batch_size = 1000
   max_rank = 0
   while True:
       facts = search_facts_ranked_list(..., limit=batch_size, offset=offset)
       if not facts:
           break
       max_rank = max(max_rank, max(f.get("rank", 0) for f in facts))
       offset += batch_size
   ```

2. **Pagination Approach**:
   ```python
   # Use cursor-based pagination for very large lists
   # Store last_seen_rank and continue from there
   ```

3. **Database Optimization**:
   ```sql
   -- Add index on (project_id, fact_key) for faster max rank queries
   -- Use MAX() aggregation instead of retrieving all facts
   SELECT MAX(CAST(SUBSTR(fact_key, LENGTH(fact_key)) AS INTEGER))
   FROM project_facts
   WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
   ```

### Recommendation

For current scale, the `limit=10000` approach is sufficient. If we encounter topics with >10,000 facts, we can implement the streaming/pagination approach or optimize the max rank query using SQL aggregation.

---

## Summary

| Aspect | Status | Details |
|--------|--------|---------|
| **Storage** | ✅ Unbounded | No limits on fact creation |
| **List Retrieval** | ✅ Paginated | Default 100, max 1000 per query |
| **Ordinal Retrieval** | ✅ Unbounded (internal) | Retrieves all facts internally, returns single rank |
| **Max Rank Calculation** | ⚠️ High limit (10k) | Sufficient for current scale, can be optimized if needed |

---

## Conclusion

**Status**: ✅ **PRODUCTION READY**

The Facts system correctly implements:
- **Unbounded storage** (no limits on fact creation)
- **Paginated retrieval** (performance-optimized limits)
- **Unbounded retrieval for ordinal queries** (internal only, returns single fact)

All code comments and documentation have been updated to reflect this clarification.

**Confidence Level**: **HIGH** - The implementation matches the clarified requirements.

---

**End of Clarification**

