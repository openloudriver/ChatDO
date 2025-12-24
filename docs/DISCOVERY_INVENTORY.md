# Discovery System Inventory

## Current Endpoints

### 1. Facts Search

**Endpoint**: `POST /search-facts` (Memory Service)
- **Location**: `memory_service/api.py:1037`
- **Request**: `SearchFactsRequest`
  - `project_id: str`
  - `query: str`
  - `limit: int = 10`
  - `exclude_message_uuid: Optional[str] = None`
- **Response**: `SearchFactsResponse`
  - `facts: List[FactResponse]`
- **FactResponse Fields**:
  - `fact_id: str`
  - `project_id: str`
  - `fact_key: str` (e.g., "user.favorite_color")
  - `value_text: str`
  - `value_type: str`
  - `confidence: float`
  - `source_message_uuid: str` ⭐ **Deep linking field**
  - `created_at: str`
  - `effective_at: str`
  - `supersedes_fact_id: Optional[str]`
  - `is_current: bool`
- **Implementation**: Direct DB access via `db.search_current_facts()`
- **Fast Path**: Yes (DB-backed, no Memory Service dependency)

**Fast List Query Path**: `server/services/chat_with_smart_search.py:646`
- Uses `librarian.search_facts_ranked_list()` (DB-backed)
- Returns formatted list: "1) X\n2) Y\n3) Z"
- Includes `source_message_uuid` in sources meta

---

### 2. Index Search (Vector/Semantic)

**Endpoint**: `POST /search` (Memory Service)
- **Location**: `memory_service/api.py:709`
- **Request**: `SearchRequest`
  - `project_id: str` (required)
  - `query: str`
  - `source_ids: Optional[List[str]]`
  - `chat_id: Optional[str]` (deprecated)
  - `limit: int = 8`
  - `exclude_chat_ids: Optional[List[str]]`
- **Response**: `SearchResponse`
  - `results: List[SearchResult]`
- **SearchResult Fields**:
  - `source_id: str`
  - `file_path: Optional[str]`
  - `chunk_id: Optional[int]`
  - `text: str` (chunk content)
  - `score: float` (similarity score)
  - `metadata: Dict[str, Any]`
    - `message_id: Optional[str]` ⭐ **Deep linking field** (for chat messages)
    - `message_uuid: Optional[str]` ⭐ **Deep linking field** (stable UUID)
    - `chat_id: Optional[str]`
    - `role: Optional[str]` ("user" or "assistant")
    - `file_id: Optional[str]` ⭐ **Deep linking field** (for file chunks)
- **Implementation**: 
  - Uses ANN (FAISS) if available, falls back to brute-force
  - Searches both file embeddings and chat message embeddings
  - Project isolation enforced
- **Fast Path**: Partial (depends on Memory Service availability, but has fallback)

**Librarian Wrapper**: `server/services/librarian.py:276`
- `get_relevant_memory()` - wraps `/search` endpoint
- Adds fact hits from `/search-facts`
- Returns `List[MemoryHit]` with unified structure
- Used by `chat_with_smart_search.py` for GPT-5 context

---

### 3. Files Search/Browse

**Endpoints**:
1. **List Directory**: `GET /filetree/{source_id}`
   - **Location**: `memory_service/api.py:1147`
   - **Query Params**:
     - `path: str = ""` (relative path from source root)
     - `max_depth: int = 2`
     - `max_entries: int = 500`
   - **Response**: `FileTreeResponse`
     - `nodes: List[FileTreeNode]`
   - **FileTreeNode Fields**:
     - `name: str`
     - `path: str` ⭐ **Deep linking field**
     - `type: str` ("file" or "directory")
     - `size: Optional[int]`
     - `modified_at: Optional[str]`
     - `children: Optional[List[FileTreeNode]]`
   - **Implementation**: Direct filesystem access via `FileTreeManager`
   - **Fast Path**: Yes (filesystem, no indexing required)

2. **Read File**: `GET /filetree/{source_id}/file`
   - **Location**: `memory_service/api.py:1181`
   - **Query Params**:
     - `path: str` (required, relative file path)
     - `max_bytes: int = 65536`
   - **Response**: `FileReadResponse`
     - `content: str`
     - `path: str` ⭐ **Deep linking field**
     - `encoding: str`
     - `is_binary: bool`
     - `truncated: bool`
   - **Implementation**: Direct file read via `FileTreeManager`
   - **Fast Path**: Yes (filesystem, no indexing required)

**File Content Search**: Currently done via Index search (`/search`) with `source_ids` filter
- File chunks are indexed and searchable via vector search
- Returns `SearchResult` with `file_path` and `file_id` in metadata

---

## Current Sources Payload Structure

### Used by Frontend (Chat Messages)

**Location**: `server/services/chat_with_smart_search.py:1015-1039`

**Source Object Structure**:
```python
{
    "id": str,  # e.g., "memory-{source_id}-{idx}"
    "title": str,  # Generated from content or file path
    "description": str,  # Content snippet (first 150 chars)
    "sourceType": "memory",
    "citationPrefix": "M",  # For inline citations [M1], [M2], etc.
    "rank": int,  # Rank within Memory group
    "siteName": str,  # e.g., "Memory"
    "meta": {
        "kind": str,  # "chat" or "file"
        "chat_id": Optional[str],
        "message_id": Optional[str],
        "message_uuid": Optional[str],  # ⭐ Deep linking field
        "file_path": Optional[str],  # ⭐ Deep linking field (file sources)
        "file_id": Optional[str],  # ⭐ Deep linking field (file sources)
        "source_id": str,
        "source_type": str,
        "role": str,  # "user" or "assistant"
        "content": str,  # Full content for reference
    }
}
```

### Used by List Queries

**Location**: `server/services/chat_with_smart_search.py:680-688`

**Source Object Structure**:
```python
{
    "id": str,  # e.g., "fact-{message_uuid[:8]}"
    "title": str,  # e.g., "Stored Facts"
    "siteName": str,  # e.g., "Facts"
    "description": str,  # e.g., "Ranked list: {topic_key}"
    "rank": int,
    "sourceType": "memory",
    "citationPrefix": "M",
    "meta": {
        "source_message_uuid": str,  # ⭐ Deep linking field
        "topic_key": str,
        "fact_count": int,
    }
}
```

---

## Deep Linking Fields Summary

| Domain | Deep Linking Field | Location | Usage |
|--------|-------------------|---------|-------|
| **Facts** | `source_message_uuid` | `FactResponse.source_message_uuid` | Navigate to message that stored the fact |
| **Index (Chat)** | `message_uuid` | `SearchResult.metadata.message_uuid` | Navigate to specific chat message |
| **Index (Chat)** | `message_id` | `SearchResult.metadata.message_id` | Fallback for message identification |
| **Index (File)** | `file_id` | `SearchResult.metadata.file_id` | Navigate to file |
| **Index (File)** | `file_path` | `SearchResult.file_path` | Navigate to file by path |
| **Files (Metadata)** | `path` | `FileTreeNode.path` | Navigate to file/directory |
| **Files (Content)** | `path` | `FileReadResponse.path` | Navigate to file |

---

## Current Code Paths

### Facts List Query Fast Path
- **Location**: `server/services/chat_with_smart_search.py:646-738`
- **Trigger**: Regex match `\b(list|show|what are)\s+(?:my|all|your)?\s*(?:favorite|top)?`
- **Implementation**: 
  - Calls `librarian.search_facts_ranked_list()` (DB-backed)
  - Returns early (no GPT-5)
  - Format: "1) X\n2) Y\n3) Z"
- **Dependencies**: None (direct DB access)

### Index Search Path (for GPT-5 Context)
- **Location**: `server/services/chat_with_smart_search.py:763-890`
- **Trigger**: Always (for memory context)
- **Implementation**:
  - Calls `librarian.get_relevant_memory()` 
  - Which calls `/search` (Memory Service) + `/search-facts`
  - Returns `List[MemoryHit]` formatted for GPT-5
- **Dependencies**: Memory Service availability (but has fallback)

### Files Browse Path (Search UI)
- **Location**: Frontend calls `/filetree/{source_id}` directly
- **Trigger**: User browsing file tree in Search UI
- **Implementation**: Direct filesystem access
- **Dependencies**: None (filesystem only)

---

## Issues & Gaps

1. **No Unified API**: Three separate endpoints with different shapes
2. **Inconsistent Sources Structure**: Different meta fields across domains
3. **No Aggregation**: Search UI must call multiple endpoints
4. **No Degraded Status**: No indication when services are unavailable
5. **Mixed Fast/Slow Paths**: Some DB-backed, some require Memory Service
6. **No Unified Ranking**: Each domain has its own scoring/ranking

---

## Next Steps

See `DISCOVERY_CONTRACT.md` for the unified Discovery schema and implementation plan.

