# Historical Memory Service Features - Summary

## Overview
This document summarizes the three Memory Service upgrades that existed in the `backup-orchestrator-main` tag and commit `969f27b` / `9019be9`.

---

## 1. BGE 1024-D Embedding Engine

**Source**: Commit `969f27b` - "Restore 1024-dimension BGE embeddings and hybrid search"

**Configuration** (`memory_service/config.py`):
- `EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"`
- `EMBEDDING_DIM = 1024`

**Implementation** (`memory_service/embeddings.py`):
- Uses `SentenceTransformer("BAAI/bge-large-en-v1.5")`
- Returns embeddings of shape `[N, 1024]` for batch, `[1024]` for single query
- No explicit normalization in embeddings.py (normalization handled in ANN layer)
- Logs: `"Loading embedding model: {EMBEDDING_MODEL}"` and `"Embedding model loaded successfully"`

**Key Differences from Current**:
- Current: `all-MiniLM-L6-v2` (384 dimensions)
- Historical: `BAAI/bge-large-en-v1.5` (1024 dimensions)

---

## 2. Vector Cache for Query Embeddings

**Source**: Commit `9019be9` - "Add in-memory vector cache for query embeddings (Phase 1)"

**File**: `memory_service/vector_cache.py` (~150 lines)

**Key Features**:
- **Cache Size**: `MAX_CACHE_SIZE = 512` entries
- **Cache Key**: `(normalized_query, model_name)` tuple
- **Query Normalization**:
  - Strip leading/trailing whitespace
  - Convert to lowercase
  - Collapse multiple whitespace into single spaces
- **LRU Eviction**: Manual LRU using `_cache_dict` and `_cache_order` list
- **Public API**:
  - `get_query_embedding(query: str) -> np.ndarray` - Main entry point
  - `clear_query_embedding_cache() -> None` - Clear cache
  - `get_cache_stats() -> dict` - Get cache statistics
- **Logging**:
  - `[CACHE] Query embedding cache HIT (model=%s)`
  - `[CACHE] Query embedding cache MISS (model=%s)`
- **Integration**: 
  - Replaces direct `embed_query()` calls in `memory_service/api.py`
  - Uses `from memory_service.vector_cache import get_query_embedding`

**Implementation Details**:
- Uses manual dict + list for LRU (numpy arrays aren't hashable for `functools.lru_cache`)
- Calls `_embed_query_uncached()` on cache miss (imported from `memory_service.embeddings`)
- Stores normalized embeddings (ready for cosine similarity)

---

## 3. FAISS ANN Index (IndexFlatIP)

**Source**: `backup-orchestrator-main` tag

**File**: `memory_service/ann_index.py` (~400+ lines)

**Key Features**:
- **Index Type**: `faiss.IndexFlatIP(dimension=1024)` (brute-force inner product)
- **Normalization**: All vectors L2-normalized before add/search (enables cosine similarity via inner product)
- **Dependencies**: `faiss-cpu` (in requirements.txt)
- **Class**: `AnnIndexManager(dimension: int = 1024)`

**Methods**:
- `__init__(dimension: int)` - Initialize FAISS IndexFlatIP
- `is_available() -> bool` - Check if FAISS is ready
- `add_embeddings(vectors: np.ndarray, metadata_list: List[Dict])` - Add embeddings with metadata
- `remove_embeddings(embedding_ids: List[int])` - Soft delete (marks inactive)
- `search(query_vector, top_k, filter_source_ids=None)` - Search and return results
- `_normalize_vector(vector)` - L2-normalize vectors
- `get_index_size()`, `get_active_count()`, `get_embedding_metadata()` - Utility methods

**Metadata Structure**:
Each embedding has metadata dict with:
- `embedding_id`, `chunk_id`, `file_id`, `file_path`, `chunk_text`
- `source_id`, `project_id`, `filetype`
- `chunk_index`, `start_char`, `end_char`
- `chat_id`, `message_id` (for chat messages)

**Integration Points**:

1. **`memory_service/api.py`**:
   - Module-level: `ann_index_manager = AnnIndexManager(dimension=EMBEDDING_DIM)`
   - Startup: `_build_ann_index()` function runs in background thread
   - Search: Replaces brute-force similarity with `ann_index_manager.search()`
   - Logs: `[ANN] Building FAISS IndexFlatIP index...`, `[ANN] FAISS index ready`, `[ANN] Using FAISS IndexFlatIP for vector search`

2. **`memory_service/indexer.py`**:
   - After `index_file()`: Calls `ann_index_manager.add_embeddings()` for new file embeddings
   - After `index_chat_message()`: Calls `ann_index_manager.add_embeddings()` for new chat embeddings
   - After `delete_file()`: Calls `ann_index_manager.remove_embeddings()` for deleted file embeddings
   - Logs: `[ANN] Added %d embeddings`, `[ANN] Removed %d embeddings`

**Background Index Building**:
- `_build_ann_index()` runs in `threading.Thread` during FastAPI startup
- Loads all embeddings from all sources (files + chats)
- Batches additions to avoid overwhelming system
- Logs progress: `[ANN] Building FAISS IndexFlatIP index...`, `[ANN] FAISS index ready (dim=1024, size=%d)`

**Fallback Behavior**:
- If FAISS unavailable: Falls back to brute-force search
- Logs: `[ANN] FAISS not available, skipping ANN index build` or `[ANN] ANN unavailable, falling back to brute-force`

**Requirements**:
- `faiss-cpu` package must be installed

---

## Integration Summary

**Files Modified in Historical Version**:
1. `memory_service/config.py` - EMBEDDING_MODEL and EMBEDDING_DIM
2. `memory_service/embeddings.py` - Model loading (BGE)
3. `memory_service/vector_cache.py` - **NEW FILE** - Query embedding cache
4. `memory_service/ann_index.py` - **NEW FILE** - FAISS ANN manager
5. `memory_service/api.py` - Integration: vector_cache import, ann_index_manager, _build_ann_index(), search() uses ANN
6. `memory_service/indexer.py` - Integration: ann_index_manager.add_embeddings() and remove_embeddings()
7. `memory_service/requirements.txt` - Added `faiss-cpu`

**Files NOT Modified** (Guardrails):
- `server/ws.py` - ✅ Not touched
- `server/services/chat_with_smart_search.py` - ✅ Not touched
- `server/services/orchestrator*.py` - ✅ Not touched
- Frontend files - ✅ Not touched

---

## Next Steps

After approval, restore in this order:
1. BGE 1024-D embedding engine (config + embeddings.py)
2. Vector cache (new file + api.py integration)
3. FAISS ANN (new file + api.py + indexer.py integration)

**Important**: User will manually reindex through UI after restoration.

