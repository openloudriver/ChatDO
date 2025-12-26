# Facts, Index, and Files Systems - Comprehensive Technical Documentation

## Overview

ChatDO implements three distinct but interconnected systems for managing user data and memory:

1. **Facts System**: Synchronous, deterministic extraction and storage of structured facts from user messages
2. **Index System**: Asynchronous, best-effort semantic indexing of chat messages and files for LLM recall
3. **Files System**: File content extraction, chunking, and embedding for searchable file knowledge

This document provides a thorough technical explanation of each system, their interactions, and current known issues.

---

## 1. Facts System

### 1.1 Architecture Overview

The Facts system is designed to be **synchronous, deterministic, and independent** of the Index system. Facts are extracted and stored immediately when a user message is received, ensuring that fact counts (`Facts-S(n)`, `Facts-U(n)`, `Facts-R(n)`) are always truthful and reflect actual database writes/reads.

**Key Principles:**
- Facts are stored **synchronously** in the backend (fast, deterministic)
- Facts persistence is **decoupled** from the Indexing pipeline
- Facts counts reflect **actual DB writes/reads**, not optimistic guesses
- Facts use a **canonical schema**: `user.favorites.<topic>.<rank>` for ranked lists
- Facts DB contract: `project_facts.project_id` must **always be a UUID**, never a project name/slug

### 1.2 Data Flow

#### 1.2.1 Fact Extraction (`memory_service/fact_extractor.py`)

**Entry Point:** `FactExtractor.extract_facts(content: str, role: str)`

**Process:**
1. **Only extracts from user messages** (`role == "user"`)
2. **Extracts ranked lists FIRST** (to avoid double-counting entities)
3. **Extracts explicit facts** (emails, URLs, dates, quantities)
4. **Extracts named entities** via spaCy (PERSON, ORG, GPE) - but **skips entities already in ranked lists**
5. **Returns two lists:**
   - `facts`: Fully-formed facts with resolved topics (e.g., `user.favorites.crypto.1 = BTC`)
   - `ranked_list_candidates`: Ranked items without resolved topics (e.g., rank=1, value="BTC", topic=None)

**Ranked List Extraction Patterns:**
- Pattern 1: Explicit ranks `"1) Blue, 2) Green"`
- Pattern 2a: Value before rank `"BTC is my #1 favorite"`
- Pattern 2a-alt: `"Make BTC my #1"`
- Pattern 2a-alt2: `"my #1 favorite crypto is BTC"`
- Pattern 2a-alt3: `"My favorite #1 is BTC"`
- Pattern 2a-alt4: `"my #1 is BTC"` (handles `"my #4 is actually FIL"` by skipping "actually")
- Pattern 2b: Hash-prefixed `"#1 XMR"` (restricted to ticker-like values only)
- Pattern 3: Ordinal words `"first: Blue, second: Green"`
- Pattern 4: Comma-separated list `"My favorite cryptos are XMR, BTC, XLM"` (implicit ranks 1, 2, 3...)
- Pattern 4b: Singular form `"My favorite crypto is XMR, BTC"` (implicit ranks)

**Topic Extraction:**
- Looks for `"favorite X"` pattern in context (up to 200 chars before the ranked item)
- Falls back to keyword matching (`crypto`, `colors`, `candies`, etc.)
- **Never infers topic from value shape** (no crypto-ticker guessing)

**Known Issues:**
- Pattern 2b can still capture malformed values like `"is actually FIL"` if the value doesn't match ticker pattern
- Topic extraction can fail for implicit-topic mutations (e.g., `"Make BTC my #1"` without mentioning "crypto")

#### 1.2.2 Topic Resolution (`server/services/facts_persistence.py`)

**Entry Point:** `resolve_ranked_list_topic(message_content, retrieved_facts, project_id, candidate)`

**Strict Inference Order:**
1. **Explicit topic** in user message OR `candidate.explicit_topic`
2. **Schema-hint anchoring** (from retrieved facts with `schema_hint.domain == "ranked_list"`)
3. **DB-backed recency fallback** (`get_recent_ranked_list_keys` - most recently updated list)
4. **Optional keyword map** (only for obvious nouns: `crypto`, `colors`, `candies`, `pies`, `tv`, `food`, `textiles`)

**Returns:**
- `(resolved_topic, None)` if topic is unambiguous
- `(None, [candidate_topics])` if ambiguous (user must choose)
- `(None, None)` if unresolvable

**Known Issues:**
- If multiple ranked lists exist (e.g., both `user.favorites.crypto` and `user.favorites.colors`), recency fallback can be ambiguous
- Keyword map is limited and may not cover all topics

#### 1.2.3 Facts Persistence (`server/services/facts_persistence.py`)

**Entry Point:** `persist_facts_synchronously(project_id, message_content, role, ...)`

**Process:**
1. **Validates `project_id` is UUID** (enforces Facts DB contract)
2. **Gets or creates `message_uuid`** (required for fact storage and Facts-R exclusion)
3. **Extracts facts and ranked-list candidates** via `FactExtractor.extract_facts()`
4. **Resolves topics for ranked-list candidates** via `resolve_ranked_list_topic()`
5. **If topic is ambiguous**, returns early with `ambiguous_topics` (no facts persisted)
6. **If topic is resolved**, converts candidates to full facts with `user.favorites.<topic>.<rank>` schema
7. **Stores each fact synchronously** via `db.store_project_fact()`
8. **Returns actual counts:**
   - `store_count`: Number of facts actually stored (new facts)
   - `update_count`: Number of facts actually updated (existing facts with changed values)
   - `stored_fact_keys`: List of fact keys that were stored/updated
   - `message_uuid`: The message_uuid used for fact storage (for exclusion in Facts-R)
   - `ambiguous_topics`: List of candidate topics if ambiguous, None otherwise

**Database Storage (`memory_service/memory_dashboard/db.py`):**

**Table:** `project_facts`
```sql
CREATE TABLE project_facts (
    fact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,  -- MUST be UUID (enforced by validate_project_uuid)
    fact_key TEXT NOT NULL,     -- e.g., "user.favorites.crypto.1"
    value_text TEXT NOT NULL,   -- e.g., "BTC"
    value_type TEXT NOT NULL,   -- 'string', 'number', 'bool', 'date', 'json'
    confidence REAL DEFAULT 1.0,
    source_message_uuid TEXT NOT NULL,  -- Links to chat_messages.message_uuid
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    effective_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    supersedes_fact_id TEXT,    -- Points to previous fact with same fact_key
    is_current INTEGER DEFAULT 1  -- 1 = current, 0 = superseded
)
```

**Storage Semantics (`store_project_fact`):**
- **"Latest wins"**: When a new fact with the same `fact_key` is stored, all previous facts with that key are marked as `is_current=0`
- **Action Type Detection:**
  - `"store"`: New fact (no previous fact with same key, OR previous fact had different value)
  - `"update"`: Existing fact updated (previous fact with same key AND same value → still counts as "store" for new fact row)
- **Returns:** `(fact_id, action_type)` where `action_type` is `"store"` or `"update"`

**Known Issues:**
- If `project_id` is not a UUID (e.g., project name "v14"), facts are stored under a different partition, causing updates to be treated as stores and list queries to return stale data
- This is why `validate_project_uuid()` is enforced at all entry points

#### 1.2.4 Facts Retrieval (`server/services/librarian.py`)

**Entry Point:** `search_facts_ranked_list(project_id, topic_key, limit, exclude_message_uuid)`

**Process:**
1. **Validates `project_id` is UUID**
2. **Queries `project_facts` table directly** (fast, deterministic, no Memory Service dependency)
3. **Filters by:**
   - `project_id = ?` (must be UUID)
   - `fact_key LIKE 'user.favorites.{topic_key}.%'` (matches ranked list schema)
   - `is_current = 1` (only current facts)
   - `exclude_message_uuid != ?` (excludes facts from current message for Facts-R counting)
4. **Extracts rank from `fact_key`** (e.g., `user.favorites.crypto.1` → rank=1)
5. **Sorts by rank** (ascending)
6. **Returns list of fact dicts** with:
   - `fact_key`: Full fact key (e.g., `user.favorites.crypto.1`)
   - `value_text`: Fact value (e.g., `BTC`)
   - `source_message_uuid`: UUID of message that stored this fact (for deep linking)
   - `rank`: Rank number extracted from fact_key
   - `schema_hint`: Schema hint metadata for topic resolution

**Facts-R Counting (`server/services/chat_with_smart_search.py`):**

**Process:**
1. **Retrieves facts** via `librarian.get_relevant_memory()` (which calls `search_current_facts()`)
2. **Filters facts for relevance** to current query:
   - Extracts main topic noun from query (e.g., `"crypto"` from `"What are my favorite cryptos?"`)
   - Only counts facts where `main_topic` appears in `canonical_key` OR at least 2 `topic_keywords` match
3. **Excludes facts from current message** via `exclude_message_uuid=current_message_uuid`
4. **Counts distinct canonical topic keys** (e.g., `user.favorites.crypto` counts as 1, regardless of how many ranks exist)

**Known Issues:**
- Facts-R counting can still include irrelevant facts if topic extraction is imprecise
- The relevance filtering logic is complex and may need refinement

### 1.3 Model Labels

**Facts-S(n)**: Number of facts **stored** (new facts)
- Set from `store_count` returned by `persist_facts_synchronously()`
- Reflects actual DB writes

**Facts-U(n)**: Number of facts **updated** (existing facts with changed values)
- Set from `update_count` returned by `persist_facts_synchronously()`
- Reflects actual DB updates (when `action_type == "update"`)

**Facts-R(n)**: Number of facts **retrieved** (relevant facts from memory)
- Counts distinct canonical topic keys from retrieved facts
- Excludes facts from current message via `exclude_message_uuid`
- Only counts facts relevant to current query (topic/keyword matching)

**Known Issues:**
- Facts-U may not trigger if `project_id` mismatch causes updates to be treated as stores
- Facts-R may overcount if relevance filtering is too loose

---

## 2. Index System

### 2.1 Architecture Overview

The Index system is designed to be **asynchronous, best-effort, and non-blocking**. It handles semantic indexing of chat messages and files for LLM recall, but failures do not block user responses.

**Key Principles:**
- Indexing is **asynchronous** (enqueued, processed in background)
- Indexing is **best-effort** (failures don't block responses)
- Indexing handles **chunking, embeddings, and ANN updates**
- Indexing **does NOT store facts** (facts are stored synchronously before indexing)

### 2.2 Chat Message Indexing

#### 2.2.1 Enqueueing (`server/services/chat_with_smart_search.py`)

**Process:**
1. After facts are persisted synchronously, user message is **enqueued for async indexing**
2. Calls `memory_client.index_chat_message()` which sends HTTP request to Memory Service
3. Memory Service endpoint `/index-chat-message` **creates `message_uuid` early** (before enqueueing)
4. Job is **enqueued** in `IndexingQueue` for background processing
5. Returns immediately with `job_id` and `message_uuid`

**Index-P/Index-F Semantics:**
- **Index-P**: Pipeline operational, job accepted/queued successfully
- **Index-F**: Pipeline failed to accept/queue job (Memory Service unavailable, timeout, etc.)
- **Note:** Index-P does NOT mean indexing completed, only that the job was enqueued

#### 2.2.2 Processing (`memory_service/indexer.py`)

**Entry Point:** `index_chat_message(project_id, chat_id, message_id, role, content, timestamp, message_index)`

**Process:**
1. **Uses special `source_id` format:** `f"project-{project_id}"` (all chat messages for a project in one source)
2. **Upserts chat message** (generates `message_uuid` if not exists)
3. **Chunks content** via `chunk_chat_message()`:
   - If content < ~1000 tokens → single chunk
   - If longer → split into overlapping chunks (512 tokens with 64-token overlap)
   - Uses character approximation (~4 chars per token)
4. **Inserts chunks** into `chunks` table (linked to `chat_message_id`)
5. **Generates embeddings** via `embed_texts()` (uses `EMBEDDING_MODEL`)
6. **Stores embeddings** in `embeddings` table
7. **Adds to ANN index** (if available) for fast similarity search
8. **Returns:** `(success: bool, message_uuid: Optional[str])`

**Key Point:** **Facts are NOT extracted or stored here** - that happens synchronously before indexing

### 2.3 File Indexing

#### 2.3.1 File Content Extraction (`memory_service/indexer.py`)

**Entry Point:** `extract_text_with_unstructured(path: Path)`

**Process:**
1. **Uses local Unstructured Python package** (`unstructured.partition.auto.partition`)
2. **Tries `strategy="hi_res"` first** (best quality, uses poppler, tesseract if available)
3. **Falls back to `strategy="fast"`** if hi_res fails (timeout or missing dependencies)
4. **Extracts text from:**
   - Text files (`.txt`, `.md`, `.json`, code files, etc.)
   - PDFs (`.pdf`) - with OCR for images
   - Documents (`.docx`, `.doc`, `.rtf`, `.odt`)
   - Spreadsheets (`.xlsx`, `.xls`, `.csv`, `.ods`)
   - Presentations (`.pptx`, `.ppt`, `.odp`)
   - Images (`.png`, `.jpg`, etc.) - with OCR
   - Emails (`.eml`, `.msg`)
   - E-books (`.epub`, `.mobi`)
5. **Returns:** Single normalized string

**Supported Extensions:**
- Text: `.txt`, `.md`, `.json`, `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.yml`, `.yaml`, etc.
- Documents: `.pdf`, `.docx`, `.doc`, `.rtf`, `.odt`
- Spreadsheets: `.xlsx`, `.xls`, `.csv`, `.ods`
- Presentations: `.pptx`, `.ppt`, `.odp`
- Images: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.webp`, `.heic`
- Emails: `.eml`, `.msg`
- E-books: `.epub`, `.mobi`

**Excluded Extensions:**
- Video: `.mp4`, `.mov`, `.avi`, `.mkv`, etc.
- Audio: `.mp3`, `.wav`, `.flac`, etc.
- Archives: `.zip`, `.rar`, `.7z`, etc.
- Binary: `.iso`, `.img`, `.dmg`, `.exe`, `.dll`, etc.

#### 2.3.2 File Indexing Process (`memory_service/indexer.py`)

**Entry Point:** `index_file(path, source_db_id, source_id)`

**Process:**
1. **Checks if file already indexed** (by `modified_at` and `size_bytes`)
2. **Extracts text** via `extract_text_with_unstructured()`
3. **Computes content hash** (SHA256) to avoid re-embedding if only metadata changed
4. **Chunks text** via `chunk_text()`:
   - Chunk size: `CHUNK_SIZE_CHARS` (default: ~2048 chars)
   - Overlap: `CHUNK_OVERLAP_CHARS` (default: ~256 chars)
   - Tries to break at paragraph/sentence boundaries
5. **Upserts file record** in `files` table
6. **Inserts chunks** into `chunks` table (linked to `file_id`)
7. **Generates embeddings** via `embed_texts()`
8. **Stores embeddings** in `embeddings` table
9. **Adds to ANN index** (if available)
10. **Returns:** `True` if successful, `False` otherwise

### 2.4 Database Schema

**Table: `sources`**
```sql
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT UNIQUE NOT NULL,  -- e.g., "project-{project_id}" for chats
    project_id TEXT NOT NULL,
    root_path TEXT NOT NULL,  -- Empty string for chat messages
    include_glob TEXT,
    exclude_glob TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**Table: `chat_messages`**
```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    project_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    message_uuid TEXT NOT NULL,  -- Stable UUID for deep linking
    role TEXT NOT NULL,  -- "user" or "assistant"
    content TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    message_index INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id),
    UNIQUE(chat_id, message_id),
    UNIQUE(message_uuid)
)
```

**Table: `files`**
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    filetype TEXT NOT NULL,
    modified_at TIMESTAMP NOT NULL,
    size_bytes INTEGER NOT NULL,
    hash TEXT,  -- Content hash (SHA256)
    FOREIGN KEY (source_id) REFERENCES sources(id),
    UNIQUE(source_id, path)
)
```

**Table: `chunks`**
```sql
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    file_id INTEGER,  -- NULL for chat message chunks
    chat_message_id INTEGER,  -- NULL for file chunks
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id),
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (chat_message_id) REFERENCES chat_messages(id)
)
```

**Table: `embeddings`**
```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL,
    embedding BLOB NOT NULL,  -- NumPy array serialized as bytes
    model TEXT NOT NULL,  -- e.g., "text-embedding-3-small"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
)
```

### 2.5 ANN Index (Approximate Nearest Neighbor)

**Purpose:** Fast similarity search for embeddings

**Implementation:** Uses external ANN library (e.g., FAISS, HNSW) for approximate nearest neighbor search

**Process:**
1. **Add embeddings** to ANN index when chunks are indexed
2. **Query ANN index** for similar embeddings when searching
3. **Returns top-K similar chunks** for LLM recall

**Known Issues:**
- ANN index may be unavailable if Memory Service is down
- ANN index updates are best-effort (failures don't block indexing)

---

## 3. Files System

### 3.1 Architecture Overview

The Files system handles file content extraction, chunking, and embedding for searchable file knowledge. It is part of the Index system but has specific file-handling logic.

### 3.2 File Source Management

**Source Configuration:**
- Each file source has a `source_id` (e.g., `"source-1"`, `"Downloads"`)
- Sources have `root_path` (directory to index), `include_glob`, `exclude_glob` patterns
- Sources are stored in `sources` table

**Indexing Process:**
1. **Scans directory tree** recursively (`rglob('*')`)
2. **Filters files** by:
   - File extension (must be in `ALL_SUPPORTED`)
   - `include_glob` pattern (if specified)
   - `exclude_glob` pattern (if specified)
3. **For each file:**
   - Checks if already indexed (by `modified_at` and `size_bytes`)
   - Extracts text via `extract_text_with_unstructured()`
   - Computes content hash
   - Chunks, embeds, and stores (same as chat message indexing)

### 3.3 File Content Search

**Entry Point:** `memory_service/memory_dashboard/db.py` → `get_chat_embeddings_for_project()`

**Process:**
1. **Queries `embeddings` table** joined with `chunks`, `files`, `sources`
2. **Filters by:**
   - `project_id` (for project isolation)
   - `exclude_chat_ids` (excludes archived/trashed chats)
   - File type, path patterns (if specified)
3. **Returns chunks** with similarity scores for LLM recall

**Known Issues:**
- File content search is slower than facts search (requires embedding similarity)
- Large files may timeout during extraction

---

## 4. System Interactions

### 4.1 Facts + Index Interaction

**Key Point:** Facts and Index are **decoupled** - Facts are stored synchronously, Index is async/best-effort.

**Flow:**
1. User sends message
2. **Facts are extracted and stored synchronously** (fast, deterministic)
3. **Message is enqueued for async indexing** (best-effort, non-blocking)
4. **Indexing happens in background** (chunking, embeddings, ANN updates)
5. **Facts counts are set from actual DB writes** (not from indexing)

**Benefits:**
- Facts persist even if indexing fails
- Facts counts are truthful (reflect actual DB state)
- User responses are not blocked by slow indexing

### 4.2 Facts + Files Interaction

**Key Point:** Facts and Files are **independent** - Facts are from chat messages, Files are from file content.

**No Direct Interaction:**
- Facts are extracted from user messages only
- Files are indexed separately (no fact extraction from files)
- Both can be searched independently via Discovery API

### 4.3 Index + Files Interaction

**Key Point:** Index handles both chat messages and files - same chunking/embedding pipeline.

**Shared Components:**
- Same `chunk_text()` / `chunk_chat_message()` logic
- Same `embed_texts()` function
- Same `embeddings` table and ANN index
- Different `source_id` formats:
  - Chat messages: `f"project-{project_id}"`
  - Files: `source_id` from source configuration

---

## 5. Known Issues and Problems

### 5.1 Facts System Issues

1. **Project ID Mismatch:**
   - **Problem:** Facts are stored under project UUID, but some code paths use project name (e.g., "v14")
   - **Symptom:** Updates are treated as stores, list queries return stale data
   - **Fix:** `validate_project_uuid()` enforced at all entry points, `resolve_project_uuid()` normalizes to UUID

2. **Malformed Fact Values:**
   - **Problem:** Pattern 2b can capture phrases like `"is actually FIL"` instead of just `"FIL"`
   - **Symptom:** Stored values are garbage (e.g., `"is actually FIL"`, `"and FIL at"`)
   - **Fix:** Pattern 2b now skips values starting with "is"/"are" and only accepts ticker-like values

3. **Topic Resolution Ambiguity:**
   - **Problem:** If multiple ranked lists exist, recency fallback can be ambiguous
   - **Symptom:** Facts not persisted when topic is ambiguous
   - **Fix:** Returns `ambiguous_topics` and user must clarify

4. **Facts-U Not Triggering:**
   - **Problem:** Updates to existing ranked lists may not trigger Facts-U if project_id mismatch
   - **Symptom:** Model label shows `Facts-S(1)` instead of `Facts-U(1)` for updates
   - **Fix:** Project UUID enforcement ensures updates are detected correctly

5. **Facts-R Overcounting:**
   - **Problem:** Relevance filtering may be too loose, counting irrelevant facts
   - **Symptom:** `Facts-R(n)` shows higher count than expected
   - **Status:** Needs refinement of relevance filtering logic

### 5.2 Index System Issues

1. **Index-F Failures:**
   - **Problem:** Memory Service may be slow/unavailable, causing enqueue failures
   - **Symptom:** Model label shows `Index-F` (pipeline failed)
   - **Fix:** Increased timeout to 5s, added 2 retries with 0.5s delay

2. **Indexing Not Completing:**
   - **Problem:** Indexing jobs may fail silently or timeout
   - **Symptom:** Messages not searchable via semantic search
   - **Status:** Indexing is best-effort, failures don't block responses

### 5.3 Files System Issues

1. **Large File Timeouts:**
   - **Problem:** Very large files (>100MB non-PDF) may timeout during extraction
   - **Symptom:** Files not indexed
   - **Fix:** Files >100MB (non-PDF) are skipped

2. **OCR Dependencies:**
   - **Problem:** OCR requires system dependencies (tesseract, poppler, etc.)
   - **Symptom:** Image/PDF extraction may fail
   - **Fix:** Falls back to `strategy="fast"` if hi_res fails

---

## 6. Current State Summary

### 6.1 Facts System
- ✅ **Working:** Synchronous persistence, truthful counts, project UUID enforcement
- ⚠️ **Issues:** Malformed values (partially fixed), Facts-R overcounting, topic resolution ambiguity

### 6.2 Index System
- ✅ **Working:** Async indexing, best-effort processing, graceful degradation
- ⚠️ **Issues:** Index-F failures (partially fixed), silent failures

### 6.3 Files System
- ✅ **Working:** File extraction, chunking, embedding, search
- ⚠️ **Issues:** Large file timeouts, OCR dependencies

---

## 7. Recommendations for ChatGPT Review

1. **Review fact extraction patterns** - ensure all edge cases are handled (e.g., `"my #4 is actually FIL"`)
2. **Review topic resolution logic** - ensure strict inference order is correct
3. **Review Facts-R counting** - ensure relevance filtering is precise
4. **Review project UUID enforcement** - ensure all entry points validate UUID
5. **Review malformed value fixes** - ensure Pattern 2b restrictions are correct
6. **Suggest improvements** for topic resolution ambiguity handling
7. **Suggest improvements** for Facts-R relevance filtering

---

## 8. Key Files Reference

- **Fact Extraction:** `memory_service/fact_extractor.py`
- **Facts Persistence:** `server/services/facts_persistence.py`
- **Facts Retrieval:** `server/services/librarian.py` → `search_facts_ranked_list()`
- **Indexing:** `memory_service/indexer.py`
- **Database:** `memory_service/memory_dashboard/db.py`
- **Chat Integration:** `server/services/chat_with_smart_search.py`
- **Project Resolver:** `server/services/projects/project_resolver.py`

---

**Last Updated:** 2025-12-25
**Status:** Facts system has known issues with malformed values and Facts-R counting. Index and Files systems are generally working but may have silent failures.

