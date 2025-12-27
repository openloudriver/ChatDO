# Facts System Diagnosis - Nano Integration

**Date:** 2025-12-26  
**Issue:** "My favorite X are Y" messages routing to Index-P instead of Facts-S  
**Model Label Observed:** `GPT-5 Nano → Index-P → GPT-5` (should be `GPT-5 Nano → Facts-S(1)`)

## Executive Summary

The Facts system has been migrated from Ollama/Qwen to GPT-5 Nano, but routing is not working correctly. Messages like "My favorite cryptos are BTC, XMR and XLM" are being routed to Index instead of Facts write operations.

## Current Architecture

### ✅ Completed Migrations

1. **Facts LLM Client** (`server/services/facts_llm/client.py`)
   - ✅ Uses `nano_facts` intent
   - ✅ Calls AI Router at `http://localhost:8081/v1/ai/run`
   - ✅ No Ollama/Qwen code remaining
   - ✅ Error handling for timeouts, unavailable, invalid JSON

2. **AI Router Configuration** (`packages/ai-router/src/config.ts`)
   - ✅ `nano_facts` intent configured: `{ model: "gpt-5-nano", providerId: "openai-gpt5-nano" }`
   - ✅ `nano_routing` intent configured: `{ model: "gpt-5-nano", providerId: "openai-gpt5-nano" }`

3. **Nano Router** (`server/services/nano_router.py`)
   - ✅ Uses `nano_routing` intent
   - ✅ Returns `RoutingPlan` with `content_plane`, `operation`, `reasoning_required`
   - ✅ Includes `facts_write_candidate` and `facts_read_candidate`
   - ✅ Temperature set to 0.0 for deterministic routing
   - ✅ JSON schema mode enabled

4. **Facts Persistence** (`server/services/facts_persistence.py`)
   - ✅ Accepts `routing_plan_candidate` parameter
   - ✅ Uses candidate directly if available (avoids double Nano call)
   - ✅ Falls back to `run_facts_llm()` if candidate missing
   - ✅ Calls `nano_facts` intent via AI Router

### ❌ Issues Found

1. **Router Not Detecting "My favorite" Patterns**
   - Router is returning `content_plane="index"` or `content_plane="chat"` instead of `content_plane="facts"`
   - Router prompt includes hard invariants but may not be matching correctly
   - Need to verify what router is actually returning

2. **Remaining Qwen References**
   - ✅ Fixed: `server/services/facts_llm/prompts.py` - Updated docstrings
   - ✅ Fixed: `server/services/facts_query_planner.py` - Updated docstrings
   - ✅ Fixed: `server/services/facts_llm/__init__.py` - Updated docstrings
   - ✅ Fixed: `server/services/chat_with_smart_search.py` - Updated comments

3. **Routing Plan Execution**
   - Code checks `routing_plan.content_plane == "facts" and routing_plan.operation == "write"`
   - If this check fails, execution falls through to Index and GPT-5
   - Need to verify router is actually returning facts/write for "My favorite" patterns

## Diagnosis Steps

### Step 1: Verify Router Output

Check server logs for:
```
[NANO-ROUTER] ✅ Routing plan: content_plane=..., operation=..., reasoning_required=..., confidence=...
[NANO-ROUTING] Routing plan check: content_plane=..., operation=..., reasoning_required=..., confidence=..., why=...
```

If router returns `content_plane="index"` or `content_plane="chat"` for "My favorite X are Y", the router prompt needs adjustment.

### Step 2: Verify Facts Execution

Check server logs for:
```
[FACTS] ✅ Facts persistence enabled: thread_id=..., project_id=...
[FACTS-PERSIST] Using routing plan candidate (topic=..., value=...), skipping Facts LLM call
```

If these logs don't appear, the routing plan check is failing.

### Step 3: Check Router Prompt

The router prompt in `server/services/nano_router.py` includes:
```
1. ANY message containing "My favorite X" followed by "is" or "are" → content_plane="facts", operation="write", reasoning_required=false
```

But the router may not be matching this pattern correctly. Need to:
- Check if JSON schema validation is working
- Verify router is actually seeing the prompt
- Check if temperature=0 is being applied

### Step 4: Verify AI Router Integration

Check if AI Router is correctly:
- Receiving `nano_routing` intent
- Routing to `openai-gpt5-nano` provider
- Applying `temperature=0.0` and `response_format` with JSON schema
- Returning valid JSON matching `RoutingPlan` schema

## Expected Behavior

For message: **"My favorite cryptos are BTC, XMR and XLM"**

1. **Nano Router** should return:
   ```json
   {
     "content_plane": "facts",
     "operation": "write",
     "reasoning_required": false,
     "facts_write_candidate": {
       "topic": "crypto",
       "value": ["BTC", "XMR", "XLM"],
       "rank_ordered": true
     },
     "confidence": 1.0,
     "why": "My favorite pattern detected"
   }
   ```

2. **Facts Persistence** should:
   - Use `facts_write_candidate` directly
   - Convert to `FactsOpsResponse` with ranked_list_set operations
   - Store facts: `user.favorites.crypto.1=BTC`, `user.favorites.crypto.2=XMR`, `user.favorites.crypto.3=XLM`
   - Return `store_count=3, update_count=0`

3. **Response** should:
   - Return immediately with confirmation: "Saved: favorite crypto = [BTC, XMR, XLM]"
   - Model label: `GPT-5 Nano → Facts-S(3)`
   - NOT call Index or GPT-5

## Actual Behavior

1. **Nano Router** returns: `content_plane="index"` or `content_plane="chat"` (WRONG)
2. **Facts Persistence** is skipped (routing plan check fails)
3. **Index** is executed (async indexing always runs)
4. **GPT-5** is called for reasoning
5. **Model label**: `GPT-5 Nano → Index-P → GPT-5` (WRONG)

## Root Cause Hypothesis

The Nano router is not correctly detecting "My favorite X are Y" patterns. Possible causes:

1. **Prompt Not Clear Enough**: The router prompt may need more explicit examples
2. **JSON Schema Validation Failing**: Router may be returning invalid JSON that gets parsed incorrectly
3. **Temperature Not Applied**: If temperature isn't 0, router may be non-deterministic
4. **Response Format Not Working**: JSON schema mode may not be enforced by OpenAI API

## Fixes Applied

1. ✅ Updated all Qwen references to GPT-5 Nano
2. ✅ Added detailed logging to router and routing plan checks
3. ✅ Added error detection for "My favorite" patterns that don't route to facts/write
4. ✅ Added Facts-F fallback when routing plan says facts/write but Facts-S/U returns 0 counts

## Next Steps

1. **Review Server Logs**: Check actual router output for "My favorite cryptos are BTC, XMR and XLM"
2. **Test Router Directly**: Call `route_with_nano()` directly with test message
3. **Verify JSON Schema**: Check if OpenAI API is actually enforcing JSON schema mode
4. **Strengthen Prompt**: Make router prompt even more explicit about "My favorite" patterns
5. **Add Post-Processing**: If router fails, add fallback pattern matching for "My favorite" in Python code

## Test Cases

### Test 1: Simple Write
**Input:** "My favorite candy is Reese's"  
**Expected Router Output:** `content_plane="facts"`, `operation="write"`, `facts_write_candidate.topic="candy"`, `facts_write_candidate.value="Reese's"`  
**Expected Model Label:** `GPT-5 Nano → Facts-S(1)`

### Test 2: Multiple Values
**Input:** "My favorite colors are red, white and blue"  
**Expected Router Output:** `content_plane="facts"`, `operation="write"`, `facts_write_candidate.topic="colors"`, `facts_write_candidate.value=["red", "white", "blue"]`, `rank_ordered=true`  
**Expected Model Label:** `GPT-5 Nano → Facts-S(3)`

### Test 3: Crypto List
**Input:** "My favorite cryptos are BTC, XMR and XLM"  
**Expected Router Output:** `content_plane="facts"`, `operation="write"`, `facts_write_candidate.topic="crypto"`, `facts_write_candidate.value=["BTC", "XMR", "XLM"]`, `rank_ordered=true`  
**Expected Model Label:** `GPT-5 Nano → Facts-S(3)`

## Files Modified

- `server/services/facts_llm/client.py` - Uses `nano_facts` intent ✅
- `server/services/facts_llm/prompts.py` - Updated docstrings ✅
- `server/services/facts_query_planner.py` - Updated docstrings ✅
- `server/services/facts_llm/__init__.py` - Updated docstrings ✅
- `server/services/nano_router.py` - Router with hard invariants ✅
- `server/services/facts_persistence.py` - Uses routing plan candidate ✅
- `server/services/chat_with_smart_search.py` - Enforces routing plan ✅
- `packages/ai-router/src/config.ts` - `nano_facts` and `nano_routing` intents ✅

## Verification Checklist

- [ ] No Ollama references in codebase
- [ ] No Qwen references in codebase (except in comments/docstrings - now fixed)
- [ ] `nano_facts` intent configured in AI Router
- [ ] `nano_routing` intent configured in AI Router
- [ ] Router prompt includes hard invariants for "My favorite" patterns
- [ ] Router uses temperature=0.0
- [ ] Router uses JSON schema mode
- [ ] Facts persistence uses routing plan candidate when available
- [ ] Facts persistence falls back to `run_facts_llm()` when candidate missing
- [ ] Routing plan check in `chat_with_smart_search()` enforces facts/write
- [ ] Model labels use arrows (→) not plus signs
- [ ] Facts-S/U returns immediately without calling GPT-5

