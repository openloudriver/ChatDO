# How the Memory Service Works

## Overview

The Memory Service is a **local-only** semantic search and structured facts storage system for ChatDO. It runs as a FastAPI service on `http://127.0.0.1:5858` and provides two main capabilities:

1. **Semantic Search**: Vector-based search over chat messages and indexed files
2. **Structured Facts**: Deterministic storage and retrieval of ranked lists and preferences

---

## Architecture

### 1. **Three-Tier Storage System**

#### **A. Per-Source Databases** (`memory_service/store/<source_id>/index.sqlite`)
- **Purpose**: Stores file-based memory (documents, code, etc.)
- **Tables**:
  - `sources`: Source metadata (root_path, project_id, etc.)
  - `files`: Indexed file records (path, filetype, modified_at, hash)
  - `chunks`: Text chunks extracted from files (with start/end character positions)
  - `embeddings`: Vector embeddings for chunks (serialized numpy arrays)
  - `chat_messages`: Chat messages indexed for cross-chat memory

#### **B. Global Tracking Database** (`memory_service/store/tracking.sqlite`)
- **Purpose**: Tracks source status, indexing jobs, and **structured facts**
- **Tables**:
  - `source_status`: Status and stats for each memory source
  - `index_jobs`: Individual indexing job progress
  - **`facts`**: **Structured facts table** (ranked lists, preferences)
    - Fields: `project_id`, `chat_id`, `topic_key`, `kind` (ranked/single), `rank`, `value`, `source_message_id`, `created_at`
    - Unique constraint: `(project_id, chat_id, topic_key, kind, rank)`

#### **C. Chat History Storage** (`memory/<project_name>/threads/<thread_id>/history.json`)
- **Purpose**: UI replay data (what was said, when)
- **Note**: This is **NOT** used for facts retrieval - facts come from `tracking.sqlite`

---

## How It Works: Two Retrieval Modes

### **Mode 1: Structured Facts (Deterministic, No LLM)**

**When**: Ordinal queries ("second favorite color") or list queries ("list my favorite colors")

**Flow**:
1. User message arrives in `chat_with_smart_search.py`
2. **Hard Pre-Route** checks if query is ordinal/list query
3. Extracts `topic_key` deterministically (only canonical keys: `favorite_colors`, `favorite_cryptos`, `favorite_tv`, `favorite_candies`)
4. Queries `facts` table in `tracking.sqlite`:
   - For ordinal: `get_fact_by_rank(project_id, chat_id, topic_key, rank)`
   - For list: `get_facts(project_id, chat_id, topic_key)` sorted by rank
5. If found → returns answer directly (no Llama call)
6. If not found → returns "I don't have that stored yet" (no Llama call)

**Key Features**:
- **No topic bleed**: "tv show" queries never return "colors" facts
- **No LLM guessing**: If fact doesn't exist, says so clearly
- **Chat-scoped**: Uses `chat_id` to scope facts to current chat (with fallback to most recent topic in chat)

### **Mode 2: Semantic Vector Search (LLM-Powered)**

**When**: Fuzzy questions, summaries, reasoning queries

**Flow**:
1. User message arrives in `chat_with_smart_search.py`
2. Pre-route determines it's NOT an ordinal/list query
3. Calls Memory Service `/search` endpoint with `project_id` and query
4. Memory Service:
   - Generates query embedding using `all-MiniLM-L6-v2` model
   - Searches FAISS index (or brute-force) for similar chunks
   - **Filters by `project_id`** (strict isolation)
   - Returns top-N chunks with similarity scores
5. Chunks are formatted with `[M#]` citations
6. Context is prepended to system prompt
7. Llama (or GPT-5) generates answer using memory context

**Key Features**:
- **Project isolation**: All results filtered by `project_id`
- **Cross-chat memory**: Searches all chat messages in project (not just current chat)
- **Citation support**: Each chunk gets `[M#]` citation marker

---

## Data Flow: Storing Facts

### **When User Provides Ranked List** (e.g., "My favorite colors are 1) Blue, 2) Green, 3) Black")

1. **Extraction** (`server/services/facts.py`):
   - `extract_ranked_facts()` parses text, removes junk tokens (`[M1]`, `##`, markdown headings)
   - Returns list of `(rank, value)` tuples: `[(1, "Blue"), (2, "Green"), (3, "Black")]`

2. **Topic Normalization** (`server/services/facts.py`):
   - `normalize_topic_key()` matches explicit nouns (colors/cryptos/tv/candies)
   - Returns canonical key: `"favorite_colors"`

3. **Storage** (`chat_with_smart_search.py`):
   - Only stores if **both** `topic_key` and `ranked_facts` are valid
   - For each `(rank, value)`, calls `memory_client.store_fact()`:
     ```python
     store_fact(
         project_id=project_id,
         topic_key="favorite_colors",
         kind="ranked",
         value="Blue",
         source_message_id=user_message_id,
         chat_id=thread_id,
         rank=1
     )
     ```

4. **Database Write** (`memory_service/store/db.py`):
   - Inserts into `facts` table in `tracking.sqlite`
   - Uses upsert logic: if fact exists (same `project_id`, `chat_id`, `topic_key`, `kind`, `rank`), updates value only if new `created_at` is newer

---

## Data Flow: Indexing Chat Messages

### **When User Sends a Message**

1. **Early Indexing** (`chat_with_smart_search.py`):
   - Message is indexed **BEFORE** memory search (avoids race condition)
   - Calls `memory_client.index_chat_message()` → Memory Service `/index-chat-message` endpoint

2. **Processing** (`memory_service/indexer.py`):
   - Creates `chat_messages` record in per-source database (`project-<project_id>/index.sqlite`)
   - Chunks message text (if long)
   - Generates embeddings for each chunk
   - Stores chunks and embeddings in database

3. **ANN Index Update** (`memory_service/ann_index.py`):
   - Adds embeddings to FAISS index for fast similarity search
   - Index is built in background thread on startup

---

## Key Components

### **Files & Responsibilities**

- **`api.py`**: FastAPI endpoints (`/search`, `/index-chat-message`, `/facts/store`, `/facts/get`, etc.)
- **`indexer.py`**: Processes files and chat messages, generates embeddings
- **`embeddings.py`**: Wraps sentence-transformers model (`all-MiniLM-L6-v2`)
- **`ann_index.py`**: Manages FAISS index for fast vector search
- **`store/db.py`**: SQLite database operations (CRUD for sources, files, chunks, embeddings, facts)
- **`vector_cache.py`**: Caches query embeddings (LRU cache) for performance
- **`watcher.py`**: File system watchers for automatic re-indexing
- **`filetree.py`**: Read-only file system browsing API

### **Client Integration** (`server/services/memory_service_client.py`)

- Wraps Memory Service HTTP API
- Provides methods: `search()`, `index_chat_message()`, `store_fact()`, `get_facts()`, `get_fact_by_rank()`
- Handles service availability checks and error handling

---

## Project Isolation

**Critical**: All operations are **project-scoped**:

- **Facts**: Filtered by `project_id` (and optionally `chat_id`)
- **Search**: Results filtered by `project_id` before returning
- **Indexing**: Chat messages tagged with `project_id`
- **Sources**: Each source has a `project_id` field

This ensures facts and memory from one project never bleed into another.

---

## Summary

**Memory Service = Two Systems in One**:

1. **Structured Facts DB** (`tracking.sqlite` facts table):
   - Deterministic storage/retrieval
   - No LLM needed for ordinal/list queries
   - Prevents topic bleed and hallucinations

2. **Semantic Vector Search** (FAISS + embeddings):
   - Fuzzy search over chat history and files
   - LLM-powered answers with memory context
   - Cross-chat memory within a project

Both systems are project-isolated and work together to provide ChatDO's memory capabilities.
