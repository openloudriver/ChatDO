# Librarian Service

## Overview

The Librarian service sits between `chat_with_smart_search.py` and `memory_service_client`, providing intelligent ranking and filtering of memory search results. It ensures that answers are prioritized over questions, deduplicates results, and returns clean, ordered memory hits for injection into GPT-5 context.

## What It Does

1. **Calls Memory Service**: Retrieves raw search results from the Memory Service (FAISS/BGE/ANN stack)
2. **Applies Smart Ranking**: Uses heuristics to boost answer-style messages over question-style messages
3. **Deduplicates**: Removes duplicate hits based on message_id
4. **Returns Clean Results**: Provides a sorted list of `MemoryHit` objects ready for context injection

## Current Ranking Heuristics

The `score_hit_for_query()` function applies the following heuristics:

1. **Question Penalty** (-0.05): Penalizes messages that look like questions (contain "?" or start with question words like "what", "why", "how", etc.)

2. **Assistant Boost** (+0.05): Boosts assistant messages since they typically contain answers

3. **Query Word Matching** (+0.03 max): Small boost when query words appear in the content (helps match "favorite color" with "My favorite color is blue")

4. **Direct Answer Pattern** (+0.02): Additional boost for assistant messages containing direct answer patterns (e.g., "is blue", "are X, Y, Z", colons, dashes)

These heuristics are designed to ensure that when a user asks "What is my favorite color?", the Librarian will rank "Your favorite color is blue" higher than "What is my favorite color?" even if both have similar base similarity scores.

## Architecture

```
chat_with_smart_search.py
    ↓
librarian.get_relevant_memory()
    ↓
memory_service_client.search()  (calls Memory Service API)
    ↓
Raw search results (List[Dict])
    ↓
Convert to MemoryHit objects
    ↓
Deduplicate by message_id
    ↓
Re-score with heuristics
    ↓
Sort by score (descending)
    ↓
Return top max_hits MemoryHit objects
    ↓
librarian.format_hits_as_context()
    ↓
Formatted context string for GPT-5 Nano (via AI Router)
```

## GPT-5 Nano Integration

The Librarian uses GPT-5 Nano via the AI Router to generate responses from Memory hits. The `generate_memory_response_with_gpt5_nano()` function:

1. Formats Memory hits as context
2. Builds a system prompt with Memory-specific instructions
3. Calls the AI Router with `intent="librarian"` (routes to GPT-5 Nano)
4. Returns the generated response with Memory citations

The deterministic heuristics remain for ranking and deduplication before GPT-5 Nano generation.

## Usage

```python
from server.services import librarian

# Get relevant memory hits
hits = librarian.get_relevant_memory(
    project_id="general",
    query="What is my favorite color?",
    max_hits=30
)

# Format hits as context string
context = librarian.format_hits_as_context(hits)
```

## Configuration

- **max_hits**: Default 30. The Librarian requests `max_hits * 3` from Memory Service to have enough candidates for re-ranking, then returns the top `max_hits` after processing.

## Logging

The Librarian logs at INFO level:
```
[LIBRARIAN] general: query='What is my favorite color?' -> 15 hits (requested=30, raw_results=90)
```

This helps track how many hits are returned after Librarian processing vs. raw results from Memory Service.

