"""
Prompts for Facts LLM (Qwen) to produce JSON operations.
"""
from typing import Optional, List, Dict


def build_facts_extraction_prompt(
    user_message: str,
    recent_context: Optional[List[Dict]] = None,
    retrieved_facts: Optional[List[Dict]] = None
) -> str:
    """
    Build a strict prompt for Qwen to extract facts as JSON operations.
    
    Args:
        user_message: The user's message to extract facts from
        recent_context: Optional recent conversation context (for topic disambiguation)
        retrieved_facts: Optional retrieved facts (for schema-hint anchoring)
        
    Returns:
        Complete prompt string for Qwen
    """
    # Build context section if available
    context_section = ""
    if recent_context:
        context_lines = []
        for msg in recent_context[-3:]:  # Last 3 messages for context
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]  # Truncate long messages
            context_lines.append(f"{role}: {content}")
        if context_lines:
            context_section = "\n\nRecent context:\n" + "\n".join(context_lines)
    
    # Build retrieved facts section if available (for schema hints)
    facts_section = ""
    if retrieved_facts:
        facts_lines = []
        for fact in retrieved_facts[:5]:  # Top 5 facts
            if isinstance(fact, dict):
                metadata = fact.get("metadata", {})
                fact_key = metadata.get("fact_key", "")
                value_text = metadata.get("value_text", "")
                if fact_key and value_text:
                    facts_lines.append(f"- {fact_key} = {value_text}")
        if facts_lines:
            facts_section = "\n\nExisting facts (for context):\n" + "\n".join(facts_lines)
    
    prompt = f"""You are a fact extraction system. Extract facts from the user's message and output ONLY valid JSON.

SCHEMA LOCK RULE: Ranked lists MUST use the schema: user.favorites.<topic>.<rank>
- Example: "My favorite cryptos are BTC, ETH, SOL" → list_key="user.favorites.crypto", ranks 1, 2, 3
- Example: "Make BTC my #1" → list_key="user.favorites.crypto", rank=1, value="BTC"
- Topic must be inferred from context or message. If ambiguous, use needs_clarification.

OPERATIONS:
1. ranked_list_set: Set a ranked list item
   - Requires: list_key (user.favorites.<topic>), rank (1..N), value
   - Example: {{"op": "ranked_list_set", "list_key": "user.favorites.crypto", "rank": 1, "value": "BTC"}}

2. set: Set a generic fact
   - Requires: fact_key, value
   - Example: {{"op": "set", "fact_key": "user.email", "value": "user@example.com"}}

3. ranked_list_clear: Clear all ranks for a list (rarely used)
   - Requires: list_key

OUTPUT FORMAT (JSON only, no markdown, no explanation):
{{
  "ops": [
    {{"op": "ranked_list_set", "list_key": "user.favorites.crypto", "rank": 1, "value": "BTC"}},
    {{"op": "ranked_list_set", "list_key": "user.favorites.crypto", "rank": 2, "value": "ETH"}}
  ],
  "needs_clarification": [],
  "notes": []
}}

RULES:
- If topic is ambiguous (e.g., "Make BTC my #1" with multiple favorite lists), set needs_clarification: ["Which favorites list? crypto/colors/..."]
- If no facts can be extracted, return {{"ops": [], "needs_clarification": [], "notes": []}}
- Output ONLY the JSON object, no markdown code blocks, no explanation
- Values must be clean (no extra words like "is actually" or "and X at")

User message:
{user_message}{context_section}{facts_section}

Output JSON:"""
    
    return prompt

