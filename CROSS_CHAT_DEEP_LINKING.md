# Cross-Chat Deep Linking in ChatDO

## Overview

ChatDO implements a comprehensive deep linking system that allows users to navigate from citations in one chat to the exact message in another chat where information was originally stated. This enables traceability and context preservation across conversations.

## Architecture

The deep linking system uses **message UUIDs** as stable identifiers that persist across sessions and enable precise navigation to specific messages, even across different chats within the same project.

---

## Data Flow

### 1. Message UUID Generation and Storage

#### Backend: Message Indexing (`memory_service/indexer.py`)

When a chat message is indexed:

1. **Message is saved to thread history** (`chatdo/memory/store.py`)
   - Each message gets a unique `id` (typically a UUID or sequential ID)
   - Stored in `memory/<target>/threads/<thread_id>/history.json`

2. **Message is indexed to Memory Service** (`memory_service/indexer.py`)
   - `index_chat_message()` is called with:
     - `project_id`: The project this chat belongs to
     - `chat_id`: The conversation/thread ID
     - `message_id`: The message ID from thread history
     - `role`: "user" or "assistant"
     - `content`: Message content
     - `timestamp`: When the message was created
     - `message_index`: Position in conversation

3. **Message UUID is generated and stored** (`memory_service/memory_dashboard/db.py`)
   - A stable UUID is generated: `message_uuid = str(uuid.uuid4())`
   - Stored in `chat_messages` table with columns:
     - `project_id`
     - `chat_id`
     - `message_id` (from thread history)
     - `message_uuid` (stable UUID for deep linking)
     - `message_index`
     - `role`
     - `content`
     - `created_at`

**Key Point**: The `message_uuid` is the **canonical identifier** for deep linking. It's stable, unique, and persists across sessions.

---

### 2. Fact Storage with Source Message UUID

#### Backend: Fact Extraction (`memory_service/fact_extractor.py`)

When facts are extracted from messages:

1. **Facts are stored with provenance** (`memory_service/memory_dashboard/db.py`)
   - `store_project_fact()` stores facts in `project_facts` table
   - Each fact includes:
     - `fact_key`: e.g., "user.favorite_color"
     - `value_text`: The fact value
     - `source_message_uuid`: **The UUID of the message where the fact was stated**
     - `project_id`: Project context
     - `is_current`: Whether this is the latest fact for this key (1 = current, 0 = superseded)

2. **Latest wins semantics**:
   - If a fact is stated multiple times, only the latest is marked `is_current = 1`
   - Older facts are marked `is_current = 0` but retained for history
   - Citations always point to the **current fact's** `source_message_uuid`

**Key Point**: Facts store `source_message_uuid`, not `fact_id`, for citations. This ensures citations link to the original message context.

---

### 3. Memory Retrieval and Citation Creation

#### Backend: Memory Search (`server/services/librarian.py`)

When ChatDO retrieves memory for a response:

1. **Facts are retrieved** (`librarian.get_relevant_memory()`)
   - Calls Memory Service `/search-facts` endpoint
   - Returns facts matching the query with `source_message_uuid`

2. **Facts are converted to MemoryHit objects**:
   ```python
   fact_hit = MemoryHit(
       source_id=f"project-{project_id}",
       message_id=fact.get("source_message_uuid", ""),  # Uses source_message_uuid
       message_uuid=fact.get("source_message_uuid"),     # For deep linking
       role="fact",
       content=content,
       score=0.95,
       metadata={
           "fact_id": fact.get("fact_id"),  # Stored but not used for citations
           "source_message_uuid": fact.get("source_message_uuid"),
           "is_fact": True
       }
   )
   ```

3. **Chat messages are also retrieved**:
   - Memory Service searches indexed chat messages
   - Each result includes `message_uuid` from the `chat_messages` table

4. **MemoryHits are converted to Source objects** (`server/services/chat_with_smart_search.py`):
   ```python
   memory_source = {
       "id": f"memory-{hit.source_id}-{idx}",
       "title": title,
       "description": description,
       "sourceType": "memory",
       "citationPrefix": "M",
       "meta": {
           "kind": "chat",  # or "file"
           "chat_id": hit.chat_id,
           "message_uuid": hit.message_uuid,  # CRITICAL: For deep linking
           "file_path": hit.file_path,  # For file sources
       }
   }
   ```

5. **Sources are sent to frontend**:
   - Included in the assistant's response
   - Each source has `meta.message_uuid` for deep linking

---

### 4. Frontend: Citation Rendering

#### Component: `InlineCitation.tsx`

Citations are rendered as clickable elements:

1. **Citation display**:
   - Memory citations appear as `[M1]`, `[M2]`, etc.
   - Inline with the assistant's response text

2. **Citation click handler**:
   ```typescript
   const handleMemorySourceClick = async (e: React.MouseEvent) => {
     const messageUuid = source.meta?.message_uuid;
     
     if (messageUuid) {
       // Find the conversation containing this message
       const targetConversation = await findConversationByMessageUuid(messageUuid);
       
       if (targetConversation) {
         // Switch to that conversation
         await setCurrentConversation(targetConversation);
         
         // Navigate to the specific message
         await navigateToMessage(messageUuid, {
           updateUrl: true,
           timeout: 10000,
         });
       }
     }
   };
   ```

---

### 5. Frontend: Message UUID Lookup

#### Finding the Target Conversation

When a citation is clicked, the frontend must find which conversation contains the message:

1. **Search all chats** (`web/src/components/InlineCitation.tsx`):
   ```typescript
   // Load all chats to search for the message
   const allChatsResponse = await axios.get('http://localhost:8000/api/chats?scope=all');
   const allChats = allChatsResponse.data;
   
   // For each chat, check if it contains the message
   for (const chat of allChats) {
     const messagesResponse = await axios.get(`http://localhost:8000/api/chats/${chat.id}/messages`);
     const messages = messagesResponse.data.messages;
     
     const message = messages.find(m => m.uuid === messageUuid);
     if (message) {
       return chat;  // Found the conversation
     }
   }
   ```

2. **Switch to target conversation**:
   - `setCurrentConversation()` loads the conversation
   - Messages are loaded from backend

---

### 6. Backend: Message UUID Resolution

#### Endpoint: `/api/chats/{chat_id}/messages` (`server/main.py`)

When messages are loaded, the backend resolves message UUIDs:

1. **Load thread history**:
   ```python
   history = load_thread_history(target_name, thread_id, project_id=project_id)
   ```

2. **Look up message_uuid for each message**:
   ```python
   for msg in history:
       message_id = msg.get("id")
       message_uuid = None
       
       if message_id and project_id:
           # Look up message_uuid from Memory Service database
           message_uuid = memory_db.get_message_uuid(
               project_id, 
               thread_id, 
               message_id
           )
       
       message_obj = {
           "role": msg.get("role"),
           "content": msg.get("content", ""),
           "uuid": message_uuid,  # Included in response
           "message_uuid": message_uuid,  # Also for backward compatibility
           # ... other fields
       }
   ```

3. **Database lookup** (`memory_service/memory_dashboard/db.py`):
   ```python
   def get_message_uuid(project_id: str, chat_id: str, message_id: str) -> Optional[str]:
       # Query chat_messages table
       cursor.execute("""
           SELECT message_uuid FROM chat_messages 
           WHERE project_id = ? AND chat_id = ? AND message_id = ?
           LIMIT 1
       """, (project_id, chat_id, message_id))
       
       row = cursor.fetchone()
       if row and row["message_uuid"]:
           return row["message_uuid"]
       
       # If UUID missing, generate one and update record
       if not message_uuid:
           message_uuid = str(uuid.uuid4())
           cursor.execute("""
               UPDATE chat_messages 
               SET message_uuid = ? 
               WHERE project_id = ? AND chat_id = ? AND message_id = ?
           """, (message_uuid, project_id, chat_id, message_id))
       
       return message_uuid
   ```

---

### 7. Frontend: DOM Element Creation

#### Component: `ChatMessages.tsx`

When messages are rendered, each message gets a DOM element with the UUID as ID:

```typescript
{messages.map((message) => (
  <div
    key={message.id || message.uuid}
    id={message.uuid ? `message-${message.uuid}` : undefined}
    className="message"
  >
    {/* Message content */}
  </div>
))}
```

**Key Point**: The element ID is `message-<uuid>` (e.g., `message-123e4567-e89b-12d3-a456-426614174000`).

---

### 8. Frontend: Deep Link Navigation

#### Utility: `messageDeepLink.ts`

When navigating to a message:

1. **Wait for element to appear** (`waitForMessageElement()`):
   ```typescript
   export async function waitForMessageElement(
     elementId: string,
     options: { timeout?: number; container?: HTMLElement }
   ): Promise<HTMLElement> {
     // Use MutationObserver to watch for element
     // Falls back to polling if observer unavailable
     // Retries with exponential backoff
   }
   ```

2. **Scroll and highlight** (`scrollToAndHighlightMessage()`):
   ```typescript
   export function scrollToAndHighlightMessage(
     element: HTMLElement,
     options: {
       behavior?: 'smooth' | 'auto';
       block?: 'start' | 'center' | 'end';
       highlightDuration?: number;
     }
   ): void {
     // Scroll element to top of viewport
     element.scrollIntoView({ behavior: 'smooth', block: 'start' });
     
     // Highlight with background color
     element.style.backgroundColor = 'var(--highlight-color)';
     setTimeout(() => {
       element.style.backgroundColor = '';
     }, highlightDuration);
   }
   ```

3. **Navigate function** (`navigateToMessage()`):
   ```typescript
   export async function navigateToMessage(
     messageId: string,  // Must be UUID-only, no suffixes
     options: {
       updateUrl?: boolean;
       timeout?: number;
       container?: HTMLElement;
     }
   ): Promise<void> {
     // Validate UUID format
     const uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
     if (!uuidPattern.test(messageId)) {
       throw new Error('Invalid message ID format');
     }
     
     const elementId = `message-${messageId}`;
     
     // Update URL hash
     if (updateUrl) {
       window.history.replaceState(null, '', `#${elementId}`);
     }
     
     // Wait for element
     const element = await waitForMessageElement(elementId, { timeout, container });
     
     // Scroll and highlight
     scrollToAndHighlightMessage(element, {
       block: 'start',  // Position at top of viewport
       behavior: 'smooth',
     });
   }
   ```

---

### 9. URL Hash Fragment Support

#### Component: `ChatMessages.tsx`

The system also supports direct navigation via URL hash:

1. **Detect hash on load**:
   ```typescript
   useEffect(() => {
     const hash = window.location.hash;
     if (hash) {
       const messageId = hash.match(/^#message-(.+)$/)?.[1];
       if (messageId) {
         // Wait for messages to render, then navigate
         setTimeout(() => {
           navigateToMessage(messageId, { updateUrl: false });
         }, 500);
       }
     }
   }, [messages]);
   ```

2. **Shareable links**:
   - Users can share URLs like `http://localhost:5173/#message-123e4567-e89b-12d3-a456-426614174000`
   - The system automatically navigates to that message on load

---

## Key Design Decisions

### 1. Message UUIDs, Not Fact IDs

**Decision**: Citations use `message_uuid`, not `fact_id`.

**Rationale**:
- Citations should link to the **original message context**, not a database record
- Users see the full conversation context, not just the fact value
- Consistent with other citation types (chat messages, files)
- Better traceability and user experience

### 2. Stable UUIDs

**Decision**: Each message gets a stable UUID that persists across sessions.

**Rationale**:
- Enables reliable deep linking even after app restarts
- UUIDs are unique and don't conflict
- Can be used in URLs for shareable links

### 3. Latest Wins for Facts

**Decision**: When a fact is stated multiple times, only the latest is current, but citations point to the latest statement.

**Rationale**:
- Reflects the most up-to-date information
- Citations always point to where the current fact was stated
- Historical facts are retained but not cited

### 4. Cross-Chat Search

**Decision**: When clicking a citation, the system searches all chats to find the target message.

**Rationale**:
- Citations can reference messages from any chat in the project
- Users don't need to know which chat contains the message
- Automatic discovery simplifies the user experience

### 5. Async Element Waiting

**Decision**: Navigation waits for DOM elements to appear using MutationObserver with polling fallback.

**Rationale**:
- Messages may be loaded asynchronously
- Virtualized lists may not render all messages immediately
- Robust waiting ensures navigation works even with slow rendering

---

## Data Structures

### Message UUID Format

- **Format**: UUID v4 (e.g., `123e4567-e89b-12d3-a456-426614174000`)
- **Length**: 36 characters (32 hex + 4 hyphens)
- **Uniqueness**: Guaranteed by UUID algorithm
- **Stability**: Generated once and stored permanently

### DOM Element ID Format

- **Format**: `message-<uuid>`
- **Example**: `message-123e4567-e89b-12d3-a456-426614174000`
- **Uniqueness**: Guaranteed by message UUID uniqueness

### URL Hash Format

- **Format**: `#message-<uuid>`
- **Example**: `#message-123e4567-e89b-12d3-a456-426614174000`
- **Shareable**: Can be copied and shared

---

## Error Handling

### Missing Message UUID

If a message doesn't have a UUID:
1. Backend generates one during lookup
2. Updates the database record
3. Returns the UUID to frontend

### Message Not Found

If a citation points to a message that doesn't exist:
1. Frontend logs a warning
2. Falls back to scrolling to bottom of conversation
3. User sees the conversation but not the specific message

### Element Not Found

If the DOM element doesn't appear within timeout:
1. Retries with exponential backoff (up to 5 attempts)
2. Logs warnings for debugging
3. Falls back to scrolling to bottom

---

## Testing

### Manual Testing

1. **Cross-chat citation**:
   - State a fact in Chat A: "My favorite color is blue"
   - In Chat B, ask: "What is my favorite color?"
   - Click citation `[M1]`
   - Should navigate to Chat A and scroll to the exact message

2. **URL hash navigation**:
   - Navigate to URL with `#message-<uuid>` hash
   - Should automatically scroll to that message on load

3. **Element IDs**:
   - Inspect message elements in DevTools
   - Should have `id="message-<uuid>"` attributes

### Automated Testing

- **E2E tests**: `tests/e2e/deep_link_torture.spec.ts`
  - Tests 500+ citation navigations
  - Validates element appearance and scrolling
  - Tests under various network conditions

---

## Performance Considerations

### Database Lookups

- Message UUID lookups are fast (indexed by project_id, chat_id, message_id)
- Lookups happen only when loading messages, not on every citation click

### Frontend Search

- Chat search for message UUID happens client-side
- Could be optimized with a backend endpoint: `/api/messages/{message_uuid}/chat`

### DOM Observation

- MutationObserver is efficient (native browser API)
- Falls back to polling only if observer unavailable
- Timeout prevents infinite waiting

---

## Future Improvements

1. **Backend message UUID lookup endpoint**:
   - Add `/api/messages/{message_uuid}/chat` to find chat directly
   - Reduces frontend search overhead

2. **Caching**:
   - Cache message UUID → chat_id mappings
   - Reduces database lookups

3. **Batch UUID resolution**:
   - Resolve multiple message UUIDs in one query
   - More efficient for conversations with many citations

---

## Summary

Cross-chat deep linking in ChatDO enables seamless navigation from citations to source messages across conversations. The system uses stable message UUIDs, robust element waiting, and automatic conversation discovery to provide a smooth user experience. Citations always point to the original message context, preserving traceability and enabling users to understand where information came from.

