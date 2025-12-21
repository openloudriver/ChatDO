# Model Label Explanation

## How Model Labels Work

The model label is determined by `build_model_label(used_web, used_memory, escalated)`:

- **"GPT-5"** - No web search, no memory found
- **"Memory + GPT-5"** - Memory was found and used (no web search)
- **"Brave + GPT-5"** - Web search was used (no memory)
- **"Brave + Memory + GPT-5"** - Both web search and memory were used

## When You FIRST State a Fact

**Current Behavior: Shows "GPT-5" (not "Memory + GPT-5")**

### Why?

1. **Message is indexed first** (line 440): Your message is indexed, facts are extracted and stored
2. **Memory is searched** (line 666): System searches for relevant memory
3. **No results found**: When you FIRST state a fact, there's nothing in memory yet to find
   - The fact was just stored, but the search query might not match it
   - Or the search happens before the fact is fully indexed
4. **`has_memory = False`**: Because no hits were found
5. **Label = "GPT-5"**: Because `used_memory = False`

### Is This Correct?

**Technically yes, but it's confusing:**

- ✅ **Correct**: There was no memory to retrieve (you're creating new memory)
- ❌ **Confusing**: The fact WAS stored, but the label doesn't reflect that

## When You ASK About a Fact (Later)

**Shows "Memory + GPT-5"** ✅

- Memory search finds the previously stored fact
- `has_memory = True`
- Label = "Memory + GPT-5"

## The Issue

The model label reflects **what was retrieved**, not **what was stored**.

When you first state a fact:
- Fact is **stored** ✅
- But nothing is **retrieved** (because it's new)
- So label shows "GPT-5" (no memory retrieved)

## Recommendation

The labels are **technically correct** but could be improved to show:
- "GPT-5" when no memory is found/used
- "Memory + GPT-5" when memory is retrieved and used
- Maybe add a separate indicator for "fact stored" vs "fact retrieved"

For now, the behavior is:
- **First statement**: "GPT-5" (correct - no memory to retrieve)
- **Later queries**: "Memory + GPT-5" (correct - memory was retrieved)

