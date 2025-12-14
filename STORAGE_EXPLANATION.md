# Storage Structure Explanation

## The Confusion

You're seeing:
- `memory_service/projects/` - Project folders with chat threads
- `memory_service/store/project-*` - Folders that look like projects

**These are NOT the same thing!** They serve completely different purposes.

## Two Separate Systems

### 1. **`memory_service/projects/`** = UI Replay Data
- **Purpose**: Store chat history for UI display (what was said, when)
- **Structure**: `projects/<project_name>/threads/<thread_id>/history.json`
- **Contains**: JSON files with message history
- **Used by**: Frontend to display chat conversations
- **Example**: `projects/general/threads/abc-123/history.json`

### 2. **`memory_service/store/project-*`** = Indexed Chat Message Databases
- **Purpose**: Store indexed chat messages for semantic search
- **Structure**: `store/project-<project_id>/index.sqlite`
- **Contains**: SQLite database with embeddings and chunks for search
- **Used by**: Memory Service to search across chat messages
- **Example**: `store/project-general/index.sqlite`

## Why Two Systems?

**They serve different purposes:**

1. **`projects/`** = "What was said" (for UI replay)
   - Fast to load
   - Human-readable JSON
   - Used for displaying chat history

2. **`store/project-*`** = "Searchable chat content" (for semantic search)
   - Indexed with embeddings
   - Used for finding relevant past messages
   - Enables cross-chat memory search

## The Naming Confusion

The `project-*` folders in `store/` are **NOT project directories** - they're **database folders** for project chat indexes.

Think of it this way:
- `projects/general/` = Project folder (contains chat threads)
- `store/project-general/` = Database folder (contains indexed chat messages for search)

## What Should Be in `store/`?

1. **`project-*` folders** = Chat message indexes (one per project)
   - `store/project-general/index.sqlite` - All indexed chat messages for "general" project
   - `store/project-<uuid>/index.sqlite` - All indexed chat messages for that project

2. **`<source_id>` folders** = File source indexes
   - `store/coin-dir/index.sqlite` - Indexed files from "coin-dir" source
   - `store/drr-repo/index.sqlite` - Indexed files from "drr-repo" source

3. **`tracking.sqlite`** = Global tracking + facts table

## The Structure Makes Sense Now

```
memory_service/
├── projects/                    # UI replay (project folders with chat threads)
│   ├── general/
│   │   └── threads/
│   │       └── <thread_id>/
│   │           └── history.json
│   └── drr/
│       └── threads/
│           └── <thread_id>/
│               └── history.json
│
└── store/                       # Memory Service databases
    ├── tracking.sqlite          # Global tracking + facts
    ├── project-general/         # Chat message index for "general" project
    │   └── index.sqlite
    ├── project-<uuid>/          # Chat message index for other projects
    │   └── index.sqlite
    ├── coin-dir/                # File source index
    │   └── index.sqlite
    └── drr-repo/                # File source index
        └── index.sqlite
```

## Summary

- **`projects/`** = Project folders containing chat threads (UI replay)
- **`store/project-*`** = Database folders for indexed chat messages (search)
- **`store/<source_id>`** = Database folders for indexed files (search)

The `project-*` naming in `store/` indicates "this is a chat message index for a project" - not "this is a project directory."
