# ChatDO UI Glitch Investigation Report

## Problem Description
When asking questions with Web search enabled, the ChatDO avatar shows pulsing dots, then disappears for 5-10 seconds, and sometimes the assistant card flashes briefly before finally appearing.

## Root Cause Analysis

### 1. **Web Search Blocks WebSocket Response**

**Location**: `server/ws.py` lines 376-384

```python
if use_web:
    try:
        sources = fetch_web_sources(message, max_results=5)  # ⚠️ BLOCKING CALL
        if sources:
            web_context_prompt = build_web_context_prompt(sources)
```

**Problem**: `fetch_web_sources()` is a **synchronous blocking call** that can take 5-10 seconds. This happens BEFORE any chunks are sent to the frontend.

### 2. **Frontend Sets Streaming State Immediately**

**Location**: `web/src/components/ChatComposer.tsx` line 268

```typescript
ws.onopen = () => {
  setStreaming(true);  // ⚠️ Set immediately, but no chunks arrive for 5-10 seconds
  // ... send message
};
```

**Problem**: The frontend sets `isStreaming = true` as soon as the WebSocket opens, but no chunks arrive because the backend is still doing web search.

### 3. **UI Shows Pulsing Dots During Wait**

**Location**: `web/src/components/ChatMessages.tsx` lines 1561-1587

```typescript
{isStreaming && (
  // Shows pulsing dots when streamingContent.trim().length <= 10
  // Shows actual content when streamingContent.trim().length > 10
)}
```

**Problem**: Because `isStreaming` is true but `streamingContent` is empty/short, the UI shows pulsing dots for the entire 5-10 second web search duration.

### 4. **Race Condition on Completion**

**Location**: `web/src/components/ChatComposer.tsx` lines 366-400

```typescript
} else if (data.type === 'done') {
  // ... add message ...
  
  // ⚠️ 50ms delay before clearing streaming state
  setTimeout(() => {
    clearStreaming();
    setLoading(false);
  }, 50);
}
```

**Problem**: There's a 50ms `setTimeout` before clearing the streaming state. This creates a race condition where:
1. The 'done' message arrives
2. `addMessage()` is called (adds assistant card)
3. 50ms delay before `clearStreaming()` is called
4. During this delay, both the streaming UI and the message might be visible
5. Then streaming UI disappears, causing the "flash"

### 5. **Why It Only Happens With Web Search**

- **Without Web**: First chunk arrives almost immediately → `streamingContent.length > 10` → shows content bubble (not dots)
- **With Web**: 5-10 second delay → `streamingContent` stays empty → shows pulsing dots → then suddenly content appears → race condition causes flash

## Flow Diagram

```
User sends message with Web enabled
    ↓
Frontend: setStreaming(true)  ← WebSocket opens
    ↓
Backend: fetch_web_sources()  ← BLOCKS for 5-10 seconds
    ↓
Frontend: Shows pulsing dots (isStreaming=true, content="")
    ↓
Backend: Web search completes
    ↓
Backend: Starts streaming chunks
    ↓
Frontend: streamingContent grows → switches from dots to content bubble
    ↓
Backend: Sends 'done' message
    ↓
Frontend: addMessage() called → assistant card appears
    ↓
Frontend: setTimeout(50ms) → clearStreaming() called
    ↓
Frontend: Streaming UI disappears → FLASH (brief moment where card might disappear/reappear)
```

## Why Questions Without Web Don't Glitch

- First chunk arrives almost immediately (< 100ms)
- `streamingContent.length > 10` quickly, so content bubble shows instead of dots
- No long delay, so no race condition
- Smooth transition from streaming to final message

## Potential Solutions (Not Implemented - Investigation Only)

### Option 1: Send "web_search_started" message
Backend could send a message immediately when web search starts:
```python
if use_web:
    await websocket.send_json({"type": "web_search_started"})
    sources = fetch_web_sources(message, max_results=5)
```

Frontend could show a different loading state (e.g., "Searching web...") instead of pulsing dots.

### Option 2: Make web search non-blocking
Move web search to a background task and send chunks as they become available. More complex but better UX.

### Option 3: Remove the 50ms setTimeout delay
Change line 397-400 in ChatComposer.tsx to clear streaming state immediately:
```typescript
// Remove setTimeout, clear immediately
clearStreaming();
setLoading(false);
```

**Risk**: Might cause the streaming UI to disappear before the message appears (the original problem the setTimeout was trying to fix).

### Option 4: Show "Searching..." state
When `isStreaming` is true but `streamingContent` is empty for > 1 second, show "Searching web..." instead of pulsing dots.

## Files Involved

1. **Backend**: `server/ws.py` (lines 376-384) - blocking web search
2. **Frontend**: `web/src/components/ChatComposer.tsx` (lines 268, 366-400) - streaming state management
3. **Frontend**: `web/src/components/ChatMessages.tsx` (lines 1561-1587) - UI rendering logic

## Conclusion

The glitch is caused by:
1. **Blocking web search** (5-10 seconds) before any chunks are sent
2. **Frontend shows pulsing dots** during this wait
3. **Race condition** when streaming completes (50ms setTimeout delay)
4. **No indication** to the user that web search is happening

The fix would require either:
- Making web search non-blocking/async
- Adding a "web search in progress" state
- Fixing the race condition in the completion handler

