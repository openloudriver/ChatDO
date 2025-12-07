# Messages Scoping Fix - Summary

## Problem
Error: `cannot access local variable 'messages' where it is not associated with a value`

This `UnboundLocalError` occurred because `messages` was defined in different branches of `chat_with_smart_search()`, and when code went down a different path, Python hit a `messages` reference before any assignment had happened in that code path.

## Root Cause
The function had multiple code paths:
1. `if not decision.use_search:` - defined `messages` and returned early
2. `except Exception as e:` (web search failed) - defined `messages` and returned early  
3. `if not web_results:` - defined `messages` and returned early
4. Final path (web search succeeded) - defined `messages` at the end

If execution went through a path where `messages` wasn't defined yet, the error occurred.

## Solution Applied

### 1. Single Declaration at Top
Moved `messages` declaration to the top of the function, before any branching:

```python
# Initialize messages list ONCE at the top - all code paths will modify this same list
messages: List[Dict[str, Any]] = conversation_history.copy()
```

### 2. Early System Prompt Building
Built the system prompt with FileTree guidance early, before branching:

```python
# Build FileTree guidance with available sources (do this once, before any branching)
filetree_guidance = build_filetree_guidance(project_id)
logger.info(f"[FILETREE-GUIDANCE] project_id={project_id} guidance_length={len(filetree_guidance)}")

# Build base system prompt with FileTree guidance
base_system_prompt = CHATDO_SYSTEM_PROMPT + filetree_guidance
if memory_context:
    base_system_prompt = f"{memory_context}\n\n{base_system_prompt}"

# Add system message to messages (only if not already present)
if not any(msg.get("role") == "system" for msg in messages):
    messages.insert(0, {"role": "system", "content": base_system_prompt})
else:
    # Update existing system message to include FileTree guidance
    for msg in messages:
        if msg.get("role") == "system" and CHATDO_SYSTEM_PROMPT in msg.get("content", ""):
            if filetree_guidance not in msg.get("content", ""):
                msg["content"] = msg["content"] + filetree_guidance
            break

# Add user message to messages (always)
messages.append({"role": "user", "content": user_message})

# Build tools list (always include FileTree tools)
tools = [FILETREE_LIST_TOOL, FILETREE_READ_TOOL]
```

### 3. Simplified Code Paths
All code paths now just use the pre-initialized `messages` and `tools`:

```python
if not decision.use_search:
    # 2a. Plain GPT-5 chat (no Brave)
    # messages, tools, and system prompt are already set up above
    
    content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
        messages=messages,
        tools=tools,
        intent="general_chat",
        project_id=project_id
    )
```

### 4. Web Search Path Updates
For web search paths, we now update the existing `messages` list instead of redefining it:

```python
# Web search succeeded - add web context to existing messages
system_prompt_with_web = base_system_prompt + "\n\nWhen you use a fact from the web sources above..."

# Update or add system messages for web context
system_found = False
for i, msg in enumerate(messages):
    if msg.get("role") == "system":
        messages[i] = {"role": "system", "content": system_prompt_with_web}
        messages.insert(i + 1, {"role": "system", "content": web_results_text})
        system_found = True
        break
```

## Files Modified

- `server/services/chat_with_smart_search.py`:
  - Refactored `chat_with_smart_search()` to define `messages` once at the top
  - Moved FileTree guidance building to early in the function
  - Simplified all code paths to use the same `messages` variable
  - Added logging for FileTree guidance injection

## Verification

1. ✅ No `messages =` assignments in inner scopes (no shadowing)
2. ✅ Single declaration at top of function
3. ✅ All code paths use the same `messages` variable
4. ✅ FileTree guidance is built early and logged
5. ✅ Backend server restarted successfully

## Expected Behavior

After this fix:
- No more `UnboundLocalError` for `messages`
- FileTree tools should work correctly
- GPT-5 should see available sources in the system prompt
- Tool loop should execute without errors

## Testing

To test:
1. Send a message in the "General" project (which has Coin source)
2. Ask: "Without running anything on my machine, use the FileTree tools to list the top-level contents of the Coin memory source."
3. Check logs for:
   - `[FILETREE-GUIDANCE]` log showing guidance was injected
   - `[TOOL-LOOP]` logs showing tool calls
   - `[FILETREE-CLIENT]` logs showing calls to `/filetree/coin-dir`
4. UI should show a normal GPT-5 response listing the directory contents

