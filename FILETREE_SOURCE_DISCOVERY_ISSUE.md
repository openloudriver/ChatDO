# FileTree Source Discovery Issue - Summary for ChatGPT

## Problem Statement

The user wants ChatDO to automatically know which memory sources are available to a project without requiring:
- Manual specification of source IDs
- Calling discovery tools
- User mentioning exact source IDs

**Desired Behavior:**
- When user says "list the Coin memory source", GPT-5 should automatically know that "Coin" (display name) maps to "coin-dir" (source_id)
- This mapping should come from the project's connected sources, automatically injected into the system prompt
- No tool calls should be needed for source discovery

## Current Architecture

### Project → Sources Mapping
- Projects are stored in `server/data/projects.json`
- Each project has a `memory_sources` array containing source_ids (e.g., `["coin-dir"]`)
- Memory sources have:
  - `id`: Technical ID (e.g., "coin-dir")
  - `display_name`: Human-readable name (e.g., "Coin")
- The mapping is available via `get_project_sources_for_project(project_id)` and `get_project_sources_with_details(project_id)`

### FileTree Tools
- `filetree_list(source_id, max_depth, max_entries)` - List directory tree
- `filetree_read(source_id, path, max_bytes)` - Read file contents
- Both require the exact `source_id` (not display name)

### Current Flow
1. User sends message with `project_id` (e.g., "general")
2. `chat_with_smart_search()` is called with `project_id`
3. System prompt is built with `CHATDO_SYSTEM_PROMPT + FILETREE_GUIDANCE`
4. GPT-5 receives tools and system prompt
5. GPT-5 tries to use FileTree tools but doesn't know source_id mappings

## What I've Implemented

### 1. Automatic Source Injection Function
Created `build_filetree_guidance(project_id)` that:
- Queries `get_project_sources_with_details(project_id)` to get all sources for the project
- Automatically injects a formatted list into the system prompt:
  ```
  **Available Memory Sources for this Project:**
  You already know the following memory sources are available. Use the source_id when calling FileTree tools:
  
  - **Coin** → source_id: `coin-dir`
  ```
- This happens automatically when `project_id` is provided

### 2. Updated System Prompt Building
Modified all code paths in `chat_with_smart_search()` to:
- Call `build_filetree_guidance(project_id)` instead of using static `FILETREE_GUIDANCE`
- Inject the available sources list into the system prompt before sending to GPT-5
- Updated guidance to tell GPT-5: "When the user mentions a memory source by name (e.g., 'Coin'), use the corresponding source_id from the list above."

### 3. Fixed Variable Scoping Issue
Fixed a Python scoping error where `messages` was used outside its definition scope by:
- Moving all `messages` usage inside the `if not decision.use_search:` block
- Ensuring `messages` is defined before use in all code paths

### 4. Removed Manual Discovery Tool
- Removed `filetree_list_sources` from the default tools list (sources are now auto-injected)
- Kept the tool handler for backward compatibility

## Current Code Structure

### Key Function: `build_filetree_guidance(project_id)`
```python
def build_filetree_guidance(project_id: Optional[str] = None) -> str:
    base_guidance = """
    You have access to FileTree tools for exploring memory sources:
    1. filetree_list(source_id, max_depth=10, max_entries=1000)
    2. filetree_read(source_id, path, max_bytes=512000)
    """
    
    if project_id:
        sources = get_project_sources_with_details(project_id)
        if sources:
            sources_text = "\n\n**Available Memory Sources for this Project:**\n"
            sources_text += "You already know the following memory sources are available...\n\n"
            for source in sources:
                sources_text += f"- **{display_name}** → source_id: `{source_id}`\n"
            sources_text += "\nWhen the user mentions a memory source by name, use the corresponding source_id from the list above.\n"
            base_guidance = sources_text + base_guidance
    
    return base_guidance
```

### Integration Points
- Called in `chat_with_smart_search()` when building system prompts
- All code paths (no web search, web search fallback, web search success) now use this function
- `project_id` is passed through the entire call chain

## Current Issue

**Error:** "Error: cannot access local variable 'messages' where it is not associated with a value"

**Root Cause Analysis:**
Despite fixing the scoping issue, the error persists. This suggests:
1. The backend server might not have reloaded with the fix
2. There might be another code path where `messages` is used before definition
3. The error might be coming from a different part of the codebase (WebSocket handler, REST endpoint, etc.)

## Files Modified

1. **`server/services/chat_with_smart_search.py`**:
   - Added `build_filetree_guidance(project_id)` function
   - Updated all system prompt building to use dynamic guidance
   - Fixed `messages` variable scoping
   - Updated tool loop to pass `project_id` through

2. **`server/services/memory_service_client.py`**:
   - Added `get_project_sources_with_details(project_id)` function
   - Queries project config and Memory Service to get source details

## Testing Status

- ✅ Code imports successfully (no syntax errors)
- ✅ Backend server running on port 8000
- ✅ Memory Service running on port 5858
- ✅ AI Router running on port 8081
- ❌ Still getting "cannot access local variable 'messages'" error in UI

## What ChatGPT Should Investigate

1. **Check all code paths** in `chat_with_smart_search()` to ensure `messages` is defined before use
2. **Check WebSocket handler** (`server/ws.py`) - the error might be coming from there instead
3. **Check REST endpoint** (`server/main.py` `/api/chat`) - verify it's calling the updated function correctly
4. **Verify server reload** - ensure the `--reload` flag is actually picking up changes
5. **Check for other call sites** - search for all places `chat_with_smart_search` is called and verify `project_id` is passed

## Expected Behavior After Fix

When user asks: "Without running anything on my machine, use the FileTree tools to list the top-level contents of the Coin memory source"

GPT-5 should:
1. See in system prompt: "**Coin** → source_id: `coin-dir`"
2. Automatically use `source_id="coin-dir"` when calling `filetree_list()`
3. Return the directory listing without asking for source_id or trying discovery

## Key Questions for ChatGPT

1. Is there a code path where `messages` is referenced before it's defined that I missed?
2. Could the error be coming from a different file (ws.py, main.py) that also uses `messages`?
3. Should I add explicit error handling/logging to identify which code path is failing?
4. Is there a better way to structure the code to avoid scoping issues entirely?

