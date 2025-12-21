# Memory Tag Behavior: Deep Dive

## Overview

The Memory tag (`Model: Memory + GPT-5`) now appears **only when structured facts are stored or retrieved**, not just when messages are indexed. This makes the tag more meaningful and informative.

---

## What's the Difference?

### 1. **Indexed Message** (No Tag)
- **What it is**: A regular message that gets stored in the Memory Service for semantic search
- **What happens**:
  - Message content is chunked into smaller pieces
  - Each chunk is converted to an embedding (vector representation)
  - Embeddings are stored in the database for future search
  - Message metadata (chat_id, message_id, timestamp) is stored
- **Purpose**: Enable semantic search across all chat history
- **Example messages**:
  - "Hello, how are you?"
  - "Can you help me with Python?"
  - "What's the weather like?"
  - "I need to write a function that..."
- **Tag**: **"GPT-5"** (no Memory tag)

### 2. **Facts Message** (Shows Tag)
- **What it is**: A message that contains structured facts that get extracted and stored
- **What happens**:
  - Message is indexed (same as above) ✅
  - **PLUS**: Facts are extracted from the message using pattern matching
  - **PLUS**: Extracted facts are stored in the `project_facts` table with:
    - `fact_key` (e.g., "user.favorite_color")
    - `value_text` (e.g., "blue")
    - `value_type` (e.g., "string")
    - `source_message_uuid` (for deep-linking)
    - `effective_at` and `created_at` (for "latest wins" semantics)
- **Purpose**: Enable structured fact retrieval and cross-chat memory
- **Example messages**:
  - "My favorite color is blue"
  - "I prefer Python over JavaScript"
  - "My favorite cryptocurrencies are XMR, BTC, and XLM"
  - "I hate chocolate"
  - "My email is john@example.com"
- **Tag**: **"Memory + GPT-5"** (shows Memory tag)

---

## The Three Scenarios

### Scenario 1: **Facts Stored** (First Time Stating a Fact)
**User message**: "My favorite color is blue"

**What happens**:
1. ✅ Message is indexed (for semantic search)
2. ✅ Facts are extracted: `{fact_key: "user.favorite_color", value_text: "blue"}`
3. ✅ Fact is stored in `project_facts` table
4. ✅ `memory_stored = True` is set

**Tag**: **"Memory + GPT-5"** ✅
**Why**: Memory service was used to store a structured fact

**Assistant response**: "Got it! I'll remember that your favorite color is blue."
- Tag shows because fact was stored

---

### Scenario 2: **Facts Retrieved** (Querying Stored Facts)
**User message**: "What's my favorite color?"

**What happens**:
1. ✅ Message is indexed (for semantic search)
2. ❌ No facts extracted (this is a question, not a fact statement)
3. ✅ Memory search finds the stored fact: `user.favorite_color = "blue"`
4. ✅ Fact is included in the AI context
5. ✅ `has_memory = True` is set

**Tag**: **"Memory + GPT-5"** ✅
**Why**: Memory service was used to retrieve a structured fact

**Assistant response**: "Your favorite color is blue." [M1] (citation to original message)
- Tag shows because fact was retrieved

---

### Scenario 3: **Regular Message** (No Facts)
**User message**: "Can you help me write a Python function?"

**What happens**:
1. ✅ Message is indexed (for semantic search)
2. ❌ No facts extracted (no fact patterns matched)
3. ❌ No facts retrieved (query doesn't match stored facts)
4. ❌ `memory_stored = False` and `has_memory = False`

**Tag**: **"GPT-5"** (no Memory tag)
**Why**: Memory service was only used for indexing (semantic search), not for structured facts

**Assistant response**: "Sure! I can help you write a Python function..."
- No tag because no structured facts were involved

---

## Technical Details

### Fact Extraction Process

The system uses pattern matching to identify fact statements:

**Patterns that trigger fact extraction**:
- "My favorite X is Y"
- "I prefer X over Y"
- "I hate/love X"
- "My email is X"
- "My favorite X are A, B, and C" (ranked lists)
- Dates, quantities, URLs, emails (automatic extraction)

**Patterns that DON'T trigger fact extraction**:
- Questions: "What is...", "How do I...", "Can you..."
- Commands: "Write a function...", "Help me..."
- General conversation: "Hello", "Thanks", "I see"

### Fact Storage vs Message Indexing

**Message Indexing** (always happens):
- Stores message for semantic search
- Enables finding similar messages across chats
- Uses embeddings (vector search)
- Purpose: General memory/search

**Fact Storage** (only when facts are detected):
- Stores structured facts in `project_facts` table
- Enables precise fact retrieval
- Uses exact matching (fact_key + value)
- Purpose: Structured memory (preferences, facts, ranked lists)

### Why Both?

- **Indexing**: "Find messages about Python" → semantic search finds all Python-related messages
- **Facts**: "What's my favorite color?" → exact fact lookup returns "blue"

They serve different purposes:
- **Indexing** = General memory (fuzzy, semantic)
- **Facts** = Structured memory (precise, queryable)

---

## Tag Logic

The Memory tag appears when:

```python
used_memory = has_memory or memory_stored
```

Where:
- `has_memory = True` when facts are **retrieved** (search found facts)
- `memory_stored = True` when facts are **stored** (extraction found facts)

**Tag shows**: "Memory + GPT-5"
**Tag doesn't show**: "GPT-5"

---

## Examples

### Example 1: First Fact Statement
**User**: "My favorite candy is Reese's"
- ✅ Facts extracted: `user.favorite_candy = "Reese's"`
- ✅ Fact stored
- **Tag**: "Memory + GPT-5" ✅

### Example 2: Regular Question
**User**: "What is machine learning?"
- ❌ No facts extracted
- ❌ No facts retrieved (not a fact query)
- **Tag**: "GPT-5" (no Memory tag)

### Example 3: Fact Query
**User**: "What's my favorite candy?"
- ❌ No facts extracted (it's a question)
- ✅ Facts retrieved: `user.favorite_candy = "Reese's"`
- **Tag**: "Memory + GPT-5" ✅

### Example 4: Update Fact
**User**: "Actually, my favorite candy is Hershey's"
- ✅ Facts extracted: `user.favorite_candy = "Hershey's"`
- ✅ Fact stored (supersedes previous fact)
- **Tag**: "Memory + GPT-5" ✅

### Example 5: General Conversation
**User**: "Can you help me debug this code?"
- ❌ No facts extracted
- ❌ No facts retrieved
- **Tag**: "GPT-5" (no Memory tag)

---

## Benefits of This Approach

### ✅ More Meaningful Tags
- Tag only appears when structured facts are involved
- Users know when their preferences/facts are being stored/retrieved
- Tag is informative, not just "always present"

### ✅ Clear Distinction
- **"GPT-5"**: General conversation, no structured facts
- **"Memory + GPT-5"**: Structured facts stored or retrieved

### ✅ Better User Feedback
- Users see when their facts are being saved
- Users see when their facts are being used
- Transparency about what the Memory service is doing

### ✅ Accurate Representation
- Tag reflects actual Memory service usage (facts, not just indexing)
- Matches the intent: "if the service or tool was actually used"

---

## Summary

**Before**: Tag showed for ~95% of messages (all indexed messages)
**After**: Tag shows for ~20-30% of messages (only fact-containing messages)

**Result**: More meaningful, informative tags that accurately represent when the Memory service is used for structured facts (not just general indexing).

