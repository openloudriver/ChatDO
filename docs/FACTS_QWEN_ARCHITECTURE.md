# Facts Qwen Architecture - Implementation Summary

## Overview

The Facts system has been completely refactored to use **Qwen2.5 7B Instruct** (via Ollama) to produce JSON operations, which are then applied deterministically. This replaces the previous regex/spaCy-based extraction with a single, LLM-driven path.

## Key Principles

1. **Single Path**: Facts are derived ONLY from Qwen JSON Ops (no regex/spaCy extraction)
2. **Deterministic Apply**: All DB writes happen via `apply_facts_ops()` (single source of truth)
3. **Hard Failure**: If Qwen fails or returns invalid JSON → Facts pipeline fails with explicit error (no graceful degradation)
4. **Truthful Counts**: Facts-S and Facts-U are computed from actual DB writes only
5. **Query-to-Plan**: Facts-R uses Qwen to convert queries into deterministic retrieval plans
6. **Schema Lock**: Ranked lists always use `user.favorites.<topic>.<rank>`

## Architecture Components

### Phase 1: Facts LLM Client (`server/services/facts_llm/client.py`)

- **Function**: `run_facts_llm(prompt: str) -> str`
- **Provider**: Ollama (configurable via env vars)
- **Model**: `qwen2.5:7b-instruct` (configurable)
- **Timeout**: 12 seconds (configurable)
- **Behavior**: Hard fails on timeout, connection errors, or HTTP errors (no retries)

**Environment Variables:**
- `FACTS_LLM_PROVIDER=ollama` (default)
- `FACTS_LLM_MODEL=qwen2.5:7b-instruct` (default)
- `FACTS_LLM_URL=http://127.0.0.1:11434` (default)
- `FACTS_LLM_TIMEOUT_S=12` (default)

### Phase 2: Facts JSON Contracts (`server/contracts/facts_ops.py`)

**FactsOp** (Write Operations):
- `op`: `"set"` | `"ranked_list_set"` | `"ranked_list_clear"`
- `fact_key`: Optional (for `set` operation)
- `list_key`: Optional (for ranked list operations, e.g., `"user.favorites.crypto"`)
- `rank`: Optional (1-based rank for `ranked_list_set`)
- `value`: Optional (fact value)
- `confidence`: Optional (0.0 to 1.0)

**FactsOpsResponse**:
- `ops`: List[FactsOp]
- `needs_clarification`: List[str] (if topic is ambiguous)
- `notes`: List[str] (optional debug notes)

**FactsQueryPlan** (Read Operations):
- `intent`: `"facts_get_ranked_list"` | `"facts_get_by_prefix"` | `"facts_get_exact_key"`
- `list_key`: Optional (for ranked list queries)
- `topic`: Optional (for ranked list queries)
- `key_prefix`: Optional (for prefix queries)
- `fact_key`: Optional (for exact key queries)
- `limit`: int (default 25)
- `include_ranks`: bool (default True)

### Phase 3: Normalizers (`server/services/facts_normalize.py`)

**Total Functions** (never throw, always return sanitized values):
- `normalize_fact_key(key: str) -> Tuple[str, Optional[str]]`: Sanitizes fact keys
- `normalize_fact_value(value: str, is_ranked_list: bool) -> Tuple[str, Optional[str]]`: Sanitizes fact values
- `canonical_list_key(topic: str) -> str`: Generates `user.favorites.<topic>`
- `canonical_rank_key(topic: str, rank: int) -> str`: Generates `user.favorites.<topic>.<rank>`
- `extract_topic_from_list_key(list_key: str) -> Optional[str]`: Extracts topic from list key

### Phase 4: Apply Operations (`server/services/facts_apply.py`)

**Function**: `apply_facts_ops(project_uuid, message_uuid, ops_response) -> ApplyResult`

**Single Source of Truth** for all fact writes:
- Validates project UUID (hard fail if invalid)
- Processes each operation:
  - `ranked_list_set`: Builds `user.favorites.<topic>.<rank>`, normalizes value, stores via `db.store_project_fact()`
  - `set`: Normalizes key/value, stores via `db.store_project_fact()`
  - `ranked_list_clear`: Not yet fully implemented
- Counts based on DB `action_type`:
  - `"store"` → increments `store_count`
  - `"update"` → increments `update_count`
- Returns `ApplyResult` with counts, keys, warnings, and errors

### Phase 5: Facts Persistence (`server/services/facts_persistence.py`)

**Function**: `persist_facts_synchronously(...) -> Tuple[int, int, list, Optional[str], Optional[List[str]]]`

**New Behavior**:
1. Validates project UUID
2. Gets/creates `message_uuid`
3. Skips non-user messages
4. **Builds prompt** for Qwen (includes user message, schema rules, examples)
5. **Calls Qwen LLM** via `run_facts_llm()`
6. **Parses JSON** strictly (hard fail if invalid)
7. **Checks for clarification** (if `needs_clarification` non-empty, returns early)
8. **Applies operations** via `apply_facts_ops()`
9. **Returns counts** from apply result

**Error Handling**:
- If Qwen fails → returns `(-1, -1, [], message_uuid, None)` (negative counts indicate error)
- If JSON parse fails → returns `(-1, -1, [], message_uuid, None)`
- If clarification needed → returns `(0, 0, [], message_uuid, ambiguous_topics)`

### Phase 6: Facts-R Query Planner (`server/services/facts_query_planner.py`)

**Function**: `plan_facts_query(query_text: str) -> FactsQueryPlan`

- Converts user query (e.g., "What are my favorite cryptos?") into a deterministic query plan
- Uses Qwen to produce `FactsQueryPlan` JSON
- Hard fails if Qwen unavailable or returns invalid JSON

### Phase 6: Facts-R Retrieval (`server/services/facts_retrieval.py`)

**Function**: `execute_facts_plan(project_uuid, plan, exclude_message_uuid) -> FactsAnswer`

- Executes `FactsQueryPlan` deterministically (no LLM calls)
- For `facts_get_ranked_list`: Calls `search_facts_ranked_list()` directly
- For `facts_get_by_prefix`: Queries DB with `LIKE prefix%`
- For `facts_get_exact_key`: Queries DB for exact key
- Returns `FactsAnswer` with facts, count, and canonical keys (for Facts-R counting)

### Phase 7: Chat Integration (`server/services/chat_with_smart_search.py`)

**Hard Failure UX**:
- If `persist_facts_synchronously()` returns negative counts → sets `facts_actions["F"] = True`
- Returns explicit error message: "Facts system failed: The Facts LLM (Qwen) is unavailable..."
- Model label shows `Facts-F` (not `Facts-S/U/R`)

**Facts-R Integration**:
- Uses `plan_facts_query()` + `execute_facts_plan()` for deterministic retrieval
- Falls back to old method if new system fails (temporary, for migration)
- Counts distinct canonical keys for Facts-R

**Model Label**:
- `Facts-F`: Facts LLM failed (hard failure)
- `Facts-S(n)`: n facts stored
- `Facts-U(n)`: n facts updated
- `Facts-R(n)`: n canonical keys retrieved

### Phase 8: Old Extractor Removal

**Deprecated Functions**:
- `resolve_ranked_list_topic()`: Marked as deprecated (Qwen handles topic resolution)
- `FactExtractor.extract_facts()`: No longer called from Facts write path

**Note**: Old extractor code is still present but not used for Facts writes. It may still be used by other systems (e.g., Index).

## Data Flow

### Write Path (Facts-S/U)

```
User Message
  ↓
persist_facts_synchronously()
  ↓
build_facts_extraction_prompt()
  ↓
run_facts_llm() [Qwen]
  ↓
Parse JSON → FactsOpsResponse
  ↓
apply_facts_ops() [Deterministic]
  ↓
db.store_project_fact() [Single source of truth]
  ↓
Return (store_count, update_count, ...)
```

### Read Path (Facts-R)

```
User Query
  ↓
plan_facts_query() [Qwen]
  ↓
Parse JSON → FactsQueryPlan
  ↓
execute_facts_plan() [Deterministic DB query]
  ↓
Return FactsAnswer with canonical_keys
  ↓
Count canonical_keys → Facts-R(n)
```

## Error Handling

### Hard Failures (No Graceful Degradation)

1. **Qwen Unavailable**: Returns `Facts-F` and explicit error message
2. **Invalid JSON**: Returns `Facts-F` and explicit error message
3. **Project UUID Invalid**: Raises `ValueError` (hard fail)
4. **Missing Required Fields**: Operation skipped, error logged

### Clarification Handling

- If `needs_clarification` non-empty → returns early with clarification message
- No facts written when clarification needed
- User must re-send message with explicit topic

## Acceptance Tests

### Test 1: Update Ranked List
- **Start**: `user.favorites.crypto.1 = SOL`
- **User**: "Make BTC my #1"
- **Expected**: 
  - DB: `user.favorites.crypto.1 = BTC` (current)
  - Model label: `Facts-U(1)` (not `Facts-S(1)`)
  - Retrieval: BTC at #1

### Test 2: Multi-Update
- **User**: "BTC is my #1 favorite and SOL is actually my #7 favorite"
- **Expected**: `Facts-U(2)` and ranks updated correctly

### Test 3: Ambiguity
- **User**: "Make BTC my #1" (with multiple favorite lists)
- **Expected**: `needs_clarification: ["Which favorites list? crypto/colors/..."]`, no writes, counts = 0

### Test 4: Hard Failure
- **Action**: Stop Ollama
- **Expected**: `Facts-F` and explicit error message, no writes

### Test 5: Facts-R
- **Query**: "What are my favorite cryptos?"
- **Expected**: Qwen produces plan → deterministic DB query → correct ordered output, `Facts-R(1)` (one canonical key)

## Configuration

Add to `.env`:
```bash
FACTS_LLM_PROVIDER=ollama
FACTS_LLM_MODEL=qwen2.5:7b-instruct
FACTS_LLM_URL=http://127.0.0.1:11434
FACTS_LLM_TIMEOUT_S=12
```

## Migration Notes

- Old extractor code (`memory_service/fact_extractor.py`) is still present but not used for Facts writes
- `resolve_ranked_list_topic()` is deprecated but kept for backward compatibility
- Facts-R now uses query planner instead of embedding search (more deterministic)
- All fact writes go through `apply_facts_ops()` (single source of truth)

## Known Limitations

1. **ranked_list_clear**: Not yet fully implemented in `apply_facts_ops()`
2. **Fallback Logic**: Temporary fallback to old Facts-R method if query planner fails (for migration safety)
3. **Topic Extraction**: Qwen must infer topic from context (no explicit topic resolution fallback)

## Next Steps

1. Test with Ollama running and Qwen model installed
2. Verify hard failure behavior when Ollama is stopped
3. Test ambiguity handling with multiple favorite lists
4. Remove temporary fallback logic once stable
5. Complete `ranked_list_clear` implementation if needed

