# Deep Link Requirements for Fact Memory

## Quick Answer

**You only need to state your favorite ONCE for deep linking to work.**

## How It Works

### Single Statement (Recommended for Testing)

1. **State the fact once:**
   ```
   "My favorite color is blue"
   ```
   - This gets stored in the fact memory system
   - The `source_message_uuid` points to this message

2. **Ask about it later:**
   ```
   "What is my favorite color?"
   ```
   - System retrieves the fact
   - Citation `[M1]` appears in the response
   - Clicking `[M1]` navigates to the original message where you stated it

### Multiple Statements (Latest Wins)

If you state it multiple times:

1. **First statement:**
   ```
   "My favorite color is blue"
   ```
   - Stored with `source_message_uuid` = message-1

2. **Second statement (later):**
   ```
   "My favorite color is actually green"
   ```
   - This becomes the **current fact** (latest wins)
   - The old fact is marked as `is_current = 0`
   - New fact has `source_message_uuid` = message-2

3. **Ask about it:**
   ```
   "What is my favorite color?"
   ```
   - System retrieves the **current fact** (green)
   - Citation `[M1]` points to **message-2** (the latest statement)
   - The citation always points to the message where the **current** fact was stated

## Key Points

1. **One statement is enough** - The system remembers it and will cite it
2. **Latest wins** - If you state it multiple times, only the latest one is current
3. **Citation points to source** - The citation always links to the message where the current fact was stated
4. **Cross-chat works** - You can state it in Chat A and ask about it in Chat B

## For Testing Deep Links

**Minimum test case:**
- State fact once: `"My favorite color is blue"`
- Ask about it: `"What is my favorite color?"`
- Click citation `[M1]` → Should navigate to the message where you stated it

**Edge case test:**
- State fact twice (different values)
- Ask about it
- Citation should point to the **latest** statement

## Technical Details

- Facts are stored in `project_facts` table
- Each fact has `source_message_uuid` pointing to the original message
- `is_current = 1` indicates the current/latest fact
- When retrieving facts, only `is_current = 1` facts are returned
- The `source_message_uuid` is passed to the frontend for deep linking

