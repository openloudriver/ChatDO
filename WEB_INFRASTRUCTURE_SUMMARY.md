# ChatDO Web Search Infrastructure Summary

## Overview

ChatDO has a comprehensive web search infrastructure built around **Brave Search API** that provides intelligent, automatic web search integration with GPT-5 responses. The system includes decision-making logic, result formatting, citation handling, and UI integration.

---

## Core Components

### 1. **Brave Search API Integration** (`chatdo/tools/web_search.py`)

**Purpose**: Direct integration with Brave Search API (same search engine as Brave Browser).

**Key Features**:
- Uses `BRAVE_SEARCH_API_KEY` environment variable (required)
- Supports freshness filters: `"pd"` (past day), `"pw"` (past week), `"pm"` (past month), `"py"` (past year)
- Returns structured results: `{title, url, snippet}`
- HTML tag cleaning for clean text output
- Error handling for API failures (401, 429, etc.)

**API Endpoint**: `https://api.search.brave.com/res/v1/web/search`

**Configuration**:
- Free tier: 2,000 queries/month
- Max results per query: 20 (API limit)
- Default: 10 results per query

**Setup**: See `BRAVE_SEARCH_SETUP.md` for API key configuration.

---

### 2. **Web Search Decision Logic**

#### A. **Smart Search Classifier** (`server/services/smart_search_classifier.py`)

**Purpose**: LLM-based classifier that decides when web search is needed.

**How it works**:
1. **Heuristic check first**: Quick keyword matching for common patterns
2. **LLM classifier**: Uses AI Router to classify if query needs fresh web info
3. **Combined decision**: Heuristic can override LLM if it's more conservative

**Heuristic triggers**:
- Time-sensitive: "today", "right now", "latest", "breaking", "current"
- Price queries: "price of", "stock price", "btc price"
- News queries: "what happened", "news about", "update on"
- Explicit requests: "look this up", "check online", "search for"

**LLM classifier criteria**:
- **Use search for**: Current events, live prices, recent developments, breaking news
- **Don't use search for**: Timeless concepts, math, coding help, historical facts

**Returns**: `SearchDecision` with `use_search`, `reason`, and `query`

#### B. **Web Policy** (`server/services/web_policy.py`)

**Purpose**: Deterministic keyword-based policy using JSON configuration.

**Features**:
- Data-driven keyword matrix from `server/config/web_keywords.json`
- Categories: `finance_price`, `finance_news`, `crypto_chain`, `security_incidents`, `global_news`
- Priority-based matching
- Recency requirements (some categories require recency words)
- URL detection (if user pasted URL, always use web)

**Modes**:
- `"on"`: Always use web search
- `"auto"`: Use keyword matrix to decide
- Anything else: No web search

**Configuration file**: `server/config/web_keywords.json`
- Defines categories with keywords, assets, context, and priority
- Includes recency words list

---

### 3. **Web Search Integration Points**

#### A. **WebSocket Handler** (`server/ws.py`)

**Functions**:
- `fetch_web_sources(query, max_results=5)`: Calls Brave Search API and converts to Source format
- `build_web_context_prompt(sources)`: Formats web results into GPT-5 system prompt with citation instructions

**Flow**:
1. Determines if web search should be used via `should_use_web()` (from `web_policy.py`)
2. Sends status message to frontend: `{"type": "status", "status": "searching_web", "message": "Searching web..."}`
3. Calls `fetch_web_sources()` to get results
4. Builds web context prompt with citation instructions
5. Prepends web context to GPT-5 system prompt
6. GPT-5 responds with inline citations like `[1]`, `[2]`, or `[1, 3]`

**Citation format**: GPT-5 is instructed to add citations at the end of sentences when using web sources.

#### B. **Smart Chat with Auto-Search** (`server/services/chat_with_smart_search.py`)

**Purpose**: Handles chat with automatic web search integration.

**Flow**:
1. Uses `decide_web_search()` (from `smart_search_classifier.py`) to determine if web search is needed
2. If web search is needed:
   - Calls Brave Search API
   - Formats results as context
   - Prepends to GPT-5 messages
3. If no web search:
   - Plain GPT-5 chat (may still use Memory Service)
4. Returns response with metadata indicating web usage

**Model labels**:
- `"GPT-5"`: No web, no memory
- `"Memory + GPT-5"`: Memory only
- `"Web + GPT-5"`: Web only
- `"Web + Memory + GPT-5"`: Both web and memory

---

### 4. **Frontend Integration**

#### A. **WebSocket Streaming** (`web/src/components/ChatComposer.tsx`)

**Features**:
- Receives `"status"` messages during web search: `{"type": "status", "status": "searching_web", "message": "Searching web..."}`
- Displays "Searching web..." status in UI during search (prevents UI glitches)
- Handles `"web_search_results"` message type for structured results
- Web mode toggle: `"auto"` or `"on"` (sent as `web_mode` in WebSocket payload)

**Status handling**:
- Shows pulsing dots + "Searching web..." text during 5-10 second search delay
- Clears status when content starts streaming
- Prevents UI flashing/disappearing during web search

#### B. **Web Search Results Display**

**Message type**: `"web_search_results"`

**Structure**:
```json
{
  "type": "web_search_results",
  "data": {
    "query": "search query",
    "provider": "brave",
    "results": [
      {
        "title": "Result Title",
        "url": "https://example.com",
        "snippet": "Description..."
      }
    ]
  },
  "model": "Brave Search",
  "provider": "brave_search"
}
```

**UI Component**: `WebSearchDialog` (imported in `ChatComposer.tsx`)

---

### 5. **Force Search Mode**

**Purpose**: Explicit web search commands that return "Top Results" card instead of GPT-5 synthesis.

**Trigger**: `force_search: true` in WebSocket payload

**Flow**:
1. Routes to `run_agent()` with `skip_web_search=False`
2. If intent is `web_search`, returns structured `web_search_results` immediately
3. Frontend displays results as a card (no GPT-5 response)

**Use cases**: When user explicitly wants search results, not a synthesized answer.

---

## Architecture Flow

### Normal Chat with Auto-Search:

```
User Message
    ↓
Web Policy Decision (should_use_web?)
    ↓
If YES:
    → Send "Searching web..." status to frontend
    → Call Brave Search API (5-10 seconds)
    → Format results as context
    → Prepend to GPT-5 system prompt
    → GPT-5 responds with citations
    ↓
If NO:
    → Plain GPT-5 chat
    ↓
Response with metadata (usedWebSearch, sources)
```

### Explicit Search (force_search):

```
User Message (with force_search=true)
    ↓
Intent Classification (web_search?)
    ↓
If web_search:
    → Call Brave Search API
    → Return structured web_search_results
    → Frontend displays as card
    ↓
If not web_search:
    → Fall back to normal chat flow
```

---

## Key Files

1. **`chatdo/tools/web_search.py`**: Brave Search API client
2. **`server/services/web_policy.py`**: Deterministic keyword-based policy
3. **`server/services/smart_search_classifier.py`**: LLM-based classifier
4. **`server/services/chat_with_smart_search.py`**: Smart chat with auto-search
5. **`server/ws.py`**: WebSocket handler with web integration
6. **`server/config/web_keywords.json`**: Keyword matrix configuration
7. **`BRAVE_SEARCH_SETUP.md`**: Setup instructions

---

## Configuration

### Environment Variables

- **`BRAVE_SEARCH_API_KEY`**: Required. Get from https://brave.com/search/api/
- **`AI_ROUTER_URL`**: Optional. Defaults to `http://localhost:8081/v1/ai/run`

### Web Mode Settings

- **`web_mode: "auto"`**: Use keyword matrix to decide (default)
- **`web_mode: "on"`**: Always use web search
- **`force_search: true`**: Return Top Results card (explicit search)

---

## UI Features

1. **Status Messages**: Shows "Searching web..." during search delay
2. **Citation Display**: GPT-5 responses include inline citations `[1]`, `[2]`, etc.
3. **Web Search Results Card**: Structured display of search results
4. **Model Labels**: UI shows which services were used (Web, Memory, GPT-5)

---

## Error Handling

1. **API Key Missing**: Clear error message directing user to setup
2. **API Rate Limit**: Handles 429 errors gracefully
3. **API Failure**: Falls back to GPT-only (logs warning, continues)
4. **Search Timeout**: 10-second timeout, falls back if exceeded

---

## Integration Points

### With Memory Service:
- Web search can be combined with Memory Service search
- Model label shows: `"Web + Memory + GPT-5"` when both are used
- Web results and Memory results are both included in GPT-5 context

### With Orchestrator:
- Orchestrator v0 currently has `use_web_search` field reserved for future use
- Web search is currently handled by `chat_with_smart_search` and WebSocket handler
- Future: Orchestrator will route web search requests

---

## Current State

✅ **Fully Implemented**:
- Brave Search API integration
- Smart search classifier (LLM + heuristics)
- Web policy (keyword matrix)
- WebSocket streaming with status messages
- Citation handling in GPT-5 responses
- Frontend UI for web search results
- Error handling and fallbacks

🔜 **Future Enhancements**:
- Orchestrator integration for web search routing
- Web search result caching
- Freshness filter optimization
- Multi-query search strategies

---

## Testing

**Test scenarios**:
1. **Auto mode**: Send query with time-sensitive keywords → should trigger web search
2. **Force mode**: Send query with `force_search=true` → should return Top Results card
3. **No web**: Send general question → should use GPT-only
4. **API failure**: Stop Brave API or use invalid key → should fall back gracefully
5. **Status messages**: Verify "Searching web..." appears during search delay

---

## Notes

- **No DuckDuckGo**: DuckDuckGo fallback was removed. Brave Search API is required.
- **Blocking search**: Web search is currently synchronous (5-10 second delay) before GPT-5 call
- **Citation format**: GPT-5 is instructed to use `[1]`, `[2]` format for citations
- **Status messages**: Added to prevent UI glitches during search delay (see `glitch-investigation.md`)

