# Directory Restructure Plan

## Current Problems

1. **`memory/`** uses project **names** (`default_target`) as folder names
2. **`memory_service/store/chat-*`** uses project **IDs** (UUIDs or slugs) as folder names
3. **Naming confusion**: `chat-*` suggests individual chats, but they're actually project-level databases
4. **Split storage**: Chat data is in two places (`memory/` for UI, `memory_service/store/` for indexing)
5. **Scattered structure**: Memory-related data is split between root and `memory_service/`

## Proposed Fix (Consolidated)

### Step 1: Move `memory/` → `memory_service/projects/`
- **Why**: Consolidate all memory-related data under `memory_service/`
- **Impact**: Update `chatdo/memory/store.py` to use `memory_service/projects/` instead of `memory/`
- **Structure**: `memory_service/projects/<project_name>/threads/<thread_id>/history.json`

### Step 2: Rename `chat-*` → `project-*` in `memory_service/store/`
- **Why**: Makes it clear these are project-level chat message databases (not individual chats)
- **Impact**: Update `memory_service/indexer.py` to use `project-{project_id}` instead of `chat-{project_id}`
- **Structure**: `memory_service/store/project-<project_id>/index.sqlite`

### Step 3: Keep `memory_service/store/` as-is
- **Why**: This is the correct location for all Memory Service databases
- **Contains**:
  - `tracking.sqlite` - Global tracking + facts
  - `project-<project_id>/index.sqlite` - Project chat message indexes
  - `<source_id>/index.sqlite` - File source indexes (e.g., `coin-dir`, `drr-repo`)

## Final Structure (Consolidated)

```
ChatDO/
└── memory_service/                    # ALL memory-related data in one place
    ├── api.py                         # Memory Service code
    ├── indexer.py
    ├── embeddings.py
    ├── [other code files...]
    │
    ├── projects/                       # UI replay data (moved from root memory/)
    │   ├── general/
    │   │   └── threads/
    │   │       └── <thread_id>/
    │   │           └── history.json
    │   ├── drr/
    │   │   └── threads/
    │   │       └── <thread_id>/
    │   │           └── history.json
    │   └── ...
    │
    └── store/                          # Memory Service databases
        ├── tracking.sqlite             # Global tracking + facts
        ├── project-general/            # Project chat indexes (renamed from chat-*)
        │   └── index.sqlite
        ├── project-<uuid>/             # Project chat indexes
        │   └── index.sqlite
        ├── coin-dir/                   # File source indexes
        │   └── index.sqlite
        └── ...
```

## Benefits

1. **Single location**: All memory-related data under `memory_service/`
2. **Clear naming**: `projects/` = project chat threads, `project-*` = project chat indexes
3. **Consistent purpose**: `memory_service/store/` = all Memory Service databases
4. **No confusion**: `project-*` clearly indicates project-level, not individual chats
5. **Better organization**: Everything memory-related is in one place

## Migration Steps

1. **Move `memory/` → `memory_service/projects/`** (file system)
   ```bash
   mv memory memory_service/projects
   ```

2. **Update `chatdo/memory/store.py`**:
   - Change `BASE_DIR_NAME = "memory"` → `BASE_DIR_NAME = "memory_service/projects"`
   - Update `memory_root()` to point to `memory_service/projects/`

3. **Update `memory_service/indexer.py`**:
   - Change `source_id = f"chat-{project_id}"` → `source_id = f"project-{project_id}"`

4. **Update `memory_service/ann_index.py`**:
   - Change `source_id.startswith("chat-")` → `source_id.startswith("project-")`

5. **Rename existing `chat-*` folders to `project-*`** in `memory_service/store/`:
   ```bash
   cd memory_service/store
   for dir in chat-*; do
     mv "$dir" "project-${dir#chat-}"
   done
   ```

6. **Update any other references** to `chat-` pattern in codebase:
   - `memory_service/api.py`
   - `memory_service/store/db.py`
   - `server/services/memory_service_client.py`
   - `server/services/chat_with_smart_search.py`
   - `server/main.py`

## Files That Need Updates

1. `chatdo/memory/store.py` - Update `memory_root()` path
2. `memory_service/indexer.py` - Change `chat-` to `project-`
3. `memory_service/ann_index.py` - Change `chat-` check to `project-`
4. `memory_service/api.py` - Update any `chat-` references
5. `memory_service/store/db.py` - Update any `chat-` references
6. `server/services/memory_service_client.py` - Update any `chat-` references
7. `server/services/chat_with_smart_search.py` - Update any `chat-` references
8. `server/main.py` - Update any `chat-` references
9. Documentation files (README.md, etc.)

## Rollback Plan

If something goes wrong:
1. Move `memory_service/projects/` back to `memory/`
2. Rename `project-*` back to `chat-*` in `memory_service/store/`
3. Revert code changes
