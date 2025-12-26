# Facts Qwen Implementation Status

## ✅ Completed Phases

### Phase 1: Facts LLM Client ✅
- **File**: `server/services/facts_llm/client.py`
- **Status**: Complete
- **Features**:
  - Ollama client wrapper
  - Configurable via env vars (FACTS_LLM_PROVIDER, FACTS_LLM_MODEL, FACTS_LLM_URL, FACTS_LLM_TIMEOUT_S)
  - Hard failure on timeout/connection errors (no retries)
  - Proper error types (FactsLLMError, FactsLLMTimeoutError, FactsLLMUnavailableError)

### Phase 2: Facts JSON Contracts ✅
- **File**: `server/contracts/facts_ops.py`
- **Status**: Complete
- **Models**:
  - `FactsOp`: Write operations (set, ranked_list_set, ranked_list_clear)
  - `FactsOpsResponse`: Response with ops, needs_clarification, notes
  - `FactsQueryPlan`: Read operations (facts_get_ranked_list, facts_get_by_prefix, facts_get_exact_key)

### Phase 3: Normalizers ✅
- **File**: `server/services/facts_normalize.py`
- **Status**: Complete
- **Functions**:
  - `normalize_fact_key()`: Total function (never throws)
  - `normalize_fact_value()`: Total function with ranked list length limits
  - `canonical_list_key()`: Generates `user.favorites.<topic>`
  - `canonical_rank_key()`: Generates `user.favorites.<topic>.<rank>`
  - `extract_topic_from_list_key()`: Extracts topic from list key

### Phase 4: Apply Operations ✅
- **File**: `server/services/facts_apply.py`
- **Status**: Complete
- **Features**:
  - Single source of truth for all fact writes
  - Validates project UUID (hard fail if invalid)
  - Processes ranked_list_set, set operations
  - Returns truthful counts from DB writes
  - `ranked_list_clear` not yet fully implemented (logs warning)

### Phase 5: Facts Persistence with Qwen ✅
- **File**: `server/services/facts_persistence.py`
- **Status**: Complete
- **Changes**:
  - Replaced extractor-based logic with Qwen LLM call
  - Builds prompt via `build_facts_extraction_prompt()`
  - Parses JSON strictly (hard fail if invalid)
  - Returns negative counts on error (indicates failure)
  - Handles clarification requests

### Phase 6: Facts-R Query Planner ✅
- **File**: `server/services/facts_query_planner.py`
- **Status**: Complete
- **Features**:
  - Converts user queries to FactsQueryPlan via Qwen
  - Hard fails on invalid JSON
  - Supports all three intent types

### Phase 6: Facts-R Retrieval ✅
- **File**: `server/services/facts_retrieval.py`
- **Status**: Complete
- **Features**:
  - Executes FactsQueryPlan deterministically (no LLM calls)
  - Direct DB queries for all intent types
  - Returns canonical keys for Facts-R counting

### Phase 7: Chat Integration ✅
- **File**: `server/services/chat_with_smart_search.py`
- **Status**: Complete
- **Changes**:
  - Handles negative counts from persist_facts_synchronously (Facts-F)
  - Returns explicit error message on Facts failure
  - Model label shows `Facts-F` when failed
  - Facts-R uses query planner + retrieval executor
  - Temporary fallback to old method if new system fails

### Phase 8: Old Extractor Deprecation ⚠️
- **Status**: Partially Complete
- **Changes**:
  - `resolve_ranked_list_topic()` marked as deprecated (but still present)
  - Old extractor not called from Facts write path
  - **Note**: Old extractor code still exists but is not used for Facts

## 📋 Remaining Tasks

1. **Test with Ollama**: Verify Qwen model is installed and accessible
2. **Remove Temporary Fallback**: Once stable, remove fallback to old Facts-R method
3. **Complete ranked_list_clear**: Implement bulk clear operation if needed
4. **Remove Dead Code**: Consider removing old extractor functions if not used elsewhere

## 🔧 Configuration Required

Add to `.env`:
```bash
FACTS_LLM_PROVIDER=ollama
FACTS_LLM_MODEL=qwen2.5:7b-instruct
FACTS_LLM_URL=http://127.0.0.1:11434
FACTS_LLM_TIMEOUT_S=12
```

## 🧪 Testing Checklist

- [ ] Install Qwen model: `ollama pull qwen2.5:7b-instruct`
- [ ] Test Facts-S: "My favorite cryptos are BTC, ETH, SOL"
- [ ] Test Facts-U: Update existing ranked list
- [ ] Test Ambiguity: Multiple favorite lists, implicit topic
- [ ] Test Hard Failure: Stop Ollama, verify Facts-F
- [ ] Test Facts-R: "What are my favorite cryptos?"
- [ ] Verify model labels: Facts-S(n), Facts-U(n), Facts-R(n), Facts-F

## 📝 Files Created/Modified

### New Files:
- `server/services/facts_llm/__init__.py`
- `server/services/facts_llm/client.py`
- `server/services/facts_llm/prompts.py`
- `server/contracts/facts_ops.py`
- `server/services/facts_normalize.py`
- `server/services/facts_apply.py`
- `server/services/facts_query_planner.py`
- `server/services/facts_retrieval.py`
- `docs/FACTS_QWEN_ARCHITECTURE.md`
- `docs/FACTS_QWEN_IMPLEMENTATION_STATUS.md`

### Modified Files:
- `server/services/facts_persistence.py` (replaced extraction with Qwen)
- `server/services/chat_with_smart_search.py` (hard failure UX, Facts-R integration)

### Deprecated (but not removed):
- `resolve_ranked_list_topic()` in `facts_persistence.py` (marked deprecated)

