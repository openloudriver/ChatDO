# Citation Verification: Message UUIDs vs Fact IDs

## Question
Do inline citations always point to message UUIDs, not fact IDs?

## Answer: **YES** ✅

Inline citations **always point to `message_uuid`**, not `fact_id`. This is by design for deep-linking to the original message where the fact was stated.

## Evidence

### 1. Librarian Service (`server/services/librarian.py`)

When creating fact hits from retrieved facts:

```python
fact_hit = MemoryHit(
    source_id=f"project-{project_id}",
    message_id=fact.get("source_message_uuid", ""),  # ✅ Uses source_message_uuid
    chat_id=None,
    role="fact",
    content=content,
    score=0.95,
    source_type="fact",
    file_path=None,
    created_at=fact.get("created_at"),
    metadata={
        "fact_id": fact.get("fact_id"),  # fact_id stored in metadata (for reference only)
        "fact_key": fact.get("fact_key"),
        "value_text": fact.get("value_text"),
        "value_type": fact.get("value_type"),
        "source_message_uuid": fact.get("source_message_uuid"),  # ✅ Also in metadata
        "is_fact": True
    },
    message_uuid=fact.get("source_message_uuid")  # ✅ For deep linking
)
```

**Key points:**
- `message_id` = `source_message_uuid` (the message UUID where fact was stated)
- `message_uuid` = `source_message_uuid` (for deep linking)
- `fact_id` is stored in metadata but **not used for citations**

### 2. Chat Service (`server/services/chat_with_smart_search.py`)

When converting MemoryHit to Source object for frontend:

```python
memory_source = {
    "id": f"memory-{hit.source_id}-{idx}",
    "title": title,
    "description": description,
    "url": None,  # Memory sources don't have URLs
    "siteName": None,
    "rank": idx,
    "sourceType": "memory",
    "meta": {
        "source_id": hit.source_id,
        "chat_id": hit.chat_id,
        "file_path": hit.file_path,
        "message_uuid": hit.message_uuid,  # ✅ Passed to frontend for deep-linking
        # ... other metadata
    }
}
```

**Key points:**
- `meta.message_uuid` = `hit.message_uuid` (which is `source_message_uuid` from the fact)
- This is what the frontend uses for deep-linking

### 3. Frontend (`web/src/components/InlineCitation.tsx`)

When handling citation clicks:

```typescript
const handleMemorySourceClick = async (e: React.MouseEvent) => {
  const messageUuid = source.meta?.message_uuid; // ✅ Uses message_uuid from meta
  
  if (messageUuid) {
    await navigateToMessage(messageUuid, {
      updateUrl: true,
      timeout: 10000,
      container: messagesContainer,
    });
  }
};
```

**Key points:**
- Frontend extracts `message_uuid` from `source.meta.message_uuid`
- Uses it to navigate to the message (deep-linking)
- **Never uses `fact_id`**

## Why Message UUIDs, Not Fact IDs?

1. **Deep-linking**: Citations should take users to the original message where the fact was stated, not to a database record
2. **User experience**: Users see the context of the message, not just the fact value
3. **Consistency**: All citations (facts, chat messages, files) use `message_uuid` for navigation
4. **Traceability**: `message_uuid` points to the source message, which contains the full context

## Fact ID Usage

`fact_id` is stored in metadata but is **not used for citations**. It's available for:
- Internal reference/debugging
- Potential future features (e.g., fact management UI)
- Database operations

But citations **always use `message_uuid`** for navigation.

## Summary

✅ **Inline citations always point to `message_uuid`** (the UUID of the message where the fact was stated)
❌ **Citations never use `fact_id`** (the database ID of the fact record)

This ensures that clicking a citation takes users to the original message with full context, not just the fact value.

