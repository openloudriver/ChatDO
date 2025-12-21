# Memory Tag: Storage vs Retrieval

## Current Behavior

**Tag shows "Memory + GPT-5" only when memory is RETRIEVED**
- Storage happens silently (no tag)
- Retrieval triggers the tag

## Proposed: Tag shows when Memory is USED (storage OR retrieval)

### Pros ✅

1. **Accurate representation**: If Memory service was used (stored or retrieved), tag should reflect it
2. **User feedback**: Users can see their facts are being stored
3. **Consistency**: Memory tool usage = Memory tag (matches intent)
4. **Transparency**: Clear indication that the system is using Memory capabilities
5. **Better UX**: Users know their preferences are being saved

### Cons ❌

1. **Tag frequency**: Almost every message would show "Memory + GPT-5" (since most messages are stored)
2. **Less meaningful**: Tag becomes less informative (always present)
3. **Performance implication**: Tag doesn't distinguish between "found relevant memory" vs "just stored new memory"
4. **User confusion**: "Memory + GPT-5" might imply memory was used to answer, not just stored

## Recommendation

**Show tag when Memory is USED (storage OR retrieval)**

**Rationale:**
- The Memory service/tool WAS used (for storage)
- This matches the intent: "if the service or tool was actually used"
- Users should know their facts are being stored
- More accurate representation of system behavior

**Implementation:**
- Track `memory_stored = True` when facts are extracted/stored
- Track `memory_retrieved = True` when memory is found
- Show tag if `memory_stored OR memory_retrieved`

