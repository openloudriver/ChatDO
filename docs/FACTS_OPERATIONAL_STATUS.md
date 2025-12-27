# Facts Operational Status

**Date:** 2025-12-26  
**Status:** ❌ **NOT OPERATIONAL**

## Current Issue

The Facts system is **NOT working correctly**. Messages like "My favorite candy is Twizzlers" are routing to **Index-P** instead of **Facts-S**.

## Evidence

From the UI:
- **User message:** "My favorite candy is Twizzlers"
- **Model label:** `GPT-5 Nano → Index-P → GPT-5` ❌
- **Expected:** `GPT-5 Nano → Facts-S(1)` ✅

## Root Cause Analysis

The Nano router is not correctly detecting "My favorite" patterns. The router should:
1. Detect "My favorite X is/are Y" pattern
2. Return `content_plane="facts"`, `operation="write"`
3. Populate `facts_write_candidate` with topic and value
4. Execute Facts persistence
5. Return Facts-S confirmation

But it's currently:
1. ❌ Returning wrong routing plan (likely `content_plane="index"` or `content_plane="chat"`)
2. ❌ Not executing Facts persistence
3. ❌ Falling through to Index and GPT-5

## Code Flow

### Expected Flow
```
User message → Nano Router → RoutingPlan(content_plane="facts", operation="write") 
→ Facts Persistence → Facts-S(1) → Return confirmation
```

### Actual Flow
```
User message → Nano Router → RoutingPlan(content_plane="index" or "chat") 
→ Skip Facts → Index → GPT-5 → Return response
```

## Diagnostic Steps

### 1. Check Server Logs

Look for these log entries:
```
[NANO-ROUTER] ✅ Routing plan: content_plane=..., operation=...
[NANO-ROUTING] Routing plan check: content_plane=..., operation=...
[NANO-ROUTING] ⚠️ CRITICAL: User message contains 'My favorite' pattern but router returned...
```

**If you see the CRITICAL error**, the router is returning the wrong plan.

### 2. Check Router Response

The router logs the raw response:
```
[NANO-ROUTER] Raw response (first 500 chars): ...
[NANO-ROUTER] Parsed JSON: ...
```

Check what JSON the router is actually returning.

### 3. Verify Router Prompt

The router prompt includes:
- RULE 1: "My favorite" + topic + "is/are" + value(s) → facts/write
- Explicit examples with JSON output
- System message emphasizing the pattern

But the router may be:
- Not seeing the prompt correctly
- JSON schema not being enforced
- Temperature not being set to 0

### 4. Test Router Directly

Run the diagnostic test:
```bash
python3 test_nano_router_direct.py
```

This will show what the router actually returns for "My favorite" patterns.

## Fixes Applied

1. ✅ Removed Python fallback (no workarounds)
2. ✅ Restructured router prompt with pattern matching rules at top
3. ✅ Added explicit JSON examples in prompt
4. ✅ Strengthened system message with critical pattern
5. ✅ Added detailed logging for debugging

## Next Steps

1. **Check server logs** - See what router is actually returning
2. **Run diagnostic test** - Verify router behavior directly
3. **Check AI Router** - Verify `nano_routing` intent is configured correctly
4. **Verify JSON schema** - Check if OpenAI API is enforcing JSON schema mode
5. **Test with simple message** - "My favorite candy is Twizzlers" should route to facts/write

## Verification Checklist

- [ ] Router returns `content_plane="facts"` for "My favorite X is Y"
- [ ] Router returns `operation="write"` for "My favorite X is Y"
- [ ] Router populates `facts_write_candidate` with topic and value
- [ ] Facts persistence executes when routing plan says facts/write
- [ ] Model label shows `GPT-5 Nano → Facts-S(N)` not `Index-P`
- [ ] No Python fallback code (router is single source of truth)

## Files to Check

- `server/services/nano_router.py` - Router implementation
- `server/services/chat_with_smart_search.py` - Routing plan check (line 788)
- `server/services/facts_persistence.py` - Facts persistence
- `packages/ai-router/src/config.ts` - `nano_routing` intent configuration
- Server logs - Actual router responses

