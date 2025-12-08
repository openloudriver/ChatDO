# AI Router Tools Integration

## Summary

This document describes the changes made to the AI Router to support OpenAI tool calling functionality, enabling FileTree tools and other tool-based interactions with GPT-5.

## Changes Made

### 1. Type Definitions (`packages/ai-router/src/types.ts`)

**Added `tool_choice` to input:**
- Extended `AiRouterInput.input` to include optional `tool_choice?: any` field
- This allows callers to specify tool selection behavior (e.g., "auto", "none", or specific tool)

**Extended response message type:**
- Updated `AiRouterResult.output.messages` to support optional `tool_calls?: any[]` field
- Messages now have the shape: `{ role: "assistant"; content: string; tool_calls?: any[] }`
- This preserves OpenAI's `tool_calls` array in the response for Python-side tool loop processing

### 2. OpenAI Provider (`packages/ai-router/src/providers/openai.ts`)

**Tool forwarding:**
- Extracts `tools` and `tool_choice` from `input.input` (if provided)
- Conditionally includes `tools` and `tool_choice` in the request payload to `client.chat.completions.create()`
- Maintains backwards compatibility: if `tools` or `tool_choice` are not provided, they are not included in the request

**Tool calls preservation:**
- Extracts `tool_calls` from OpenAI's response message (`response.choices[0]?.message.tool_calls`)
- Includes `tool_calls` in the response message object if present
- The full OpenAI response is still available in `output.raw` for debugging

## Implementation Details

### Request Flow
1. Python calls `call_ai_router()` with `tools` parameter
2. Python sends `payload["input"]["tools"] = tools` to AI Router
3. AI Router extracts `tools` from `input.input.tools`
4. AI Router passes `tools` (and optional `tool_choice`) to OpenAI API
5. OpenAI returns response with potential `tool_calls` in the message

### Response Flow
1. OpenAI response includes `message.tool_calls` array (if model decided to call tools)
2. AI Router extracts `tool_calls` from OpenAI response
3. AI Router includes `tool_calls` in the response message object
4. Python receives response with `tool_calls` preserved
5. Python tool loop (in `chat_with_smart_search.py`) processes `tool_calls` and executes tools

## Backwards Compatibility

- **No breaking changes**: If `tools` is not provided, the request behaves exactly as before
- **Optional tool_choice**: If `tool_choice` is not provided, OpenAI uses default behavior ("auto")
- **Response shape**: Messages without `tool_calls` still work (field is optional)

## Limitations & TODOs

### Current Limitations
- **Provider-specific**: Only OpenAI provider supports tools currently
- **No tool loop in AI Router**: Tool execution loop lives in Python (`chat_with_smart_search.py`)
- **Generic types**: `tools` and `tool_calls` use `any[]` type (could be refined with OpenAI-specific types later)

### Future Enhancements
- Add TypeScript types for OpenAI tool definitions (instead of `any[]`)
- Consider adding tool support to other providers (Anthropic, Gemini, etc.) if needed
- Add logging for tool calls (when tools are sent, when tool_calls are received)

## Testing

### Manual Test Plan
1. **Start all services:**
   - AI Router: `cd packages/ai-router && pnpm dev`
   - Backend: `python server/main.py` (or equivalent)
   - Memory Service: `uvicorn memory_service.api:app --port 5858`
   - Frontend: `cd web && pnpm dev`

2. **Test FileTree tool execution:**
   - In ChatDO UI, ask: "Without running anything on my machine, use the FileTree tools to list the top-level contents of the Coin memory source and tell me what files and folders are there."
   - **Expected behavior:**
     - Backend logs show `[FILETREE-CLIENT]` logs (FileTree HTTP calls to Memory Service)
     - GPT-5 should NOT emit `<TASKS>` or raw shell commands
     - GPT-5 should internally call `filetree_list` tool, get JSON back, and answer with directory structure description

3. **Verify tool forwarding:**
   - Check AI Router logs for tool presence in requests
   - Check that OpenAI receives tools in the request payload
   - Verify `tool_calls` are present in response when GPT-5 decides to use tools

## Files Modified

1. `packages/ai-router/src/types.ts`
   - Added `tool_choice?: any` to `AiRouterInput.input`
   - Extended `AiRouterResult.output.messages` to include `tool_calls?: any[]`

2. `packages/ai-router/src/providers/openai.ts`
   - Extract `tools` and `tool_choice` from input
   - Conditionally include them in OpenAI API request
   - Preserve `tool_calls` from OpenAI response in the message object

## Confirmation Checklist

✅ `tools` is accepted in `AiRouterInput.input.tools` (already existed, now used)
✅ `tool_choice` is accepted in `AiRouterInput.input.tool_choice` (newly added)
✅ `tools` is forwarded to `client.chat.completions.create()` (conditionally)
✅ `tool_choice` is forwarded to `client.chat.completions.create()` (conditionally)
✅ `message.tool_calls` is preserved in the response (newly implemented)
✅ Backwards compatible (no tools = same behavior as before)
✅ TypeScript build succeeds
✅ No linting errors

## Notes

- The Python side (`chat_with_smart_search.py`) already has the tool loop and `handle_filetree_tool_call()` function
- The AI Router does NOT implement tool execution - it only forwards tools to OpenAI and preserves tool_calls in responses
- Tool execution and result handling remains in Python, maintaining separation of concerns

