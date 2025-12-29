"""
Facts Query Planner - Uses GPT-5 Nano to convert user queries into deterministic query plans.
"""
import logging
import json
from typing import Optional

from server.contracts.facts_ops import FactsQueryPlan
from server.services.facts_llm.client import run_facts_llm, FactsLLMError

logger = logging.getLogger(__name__)


async def plan_facts_query(query_text: str) -> FactsQueryPlan:
    """
    Convert a user query into a deterministic Facts query plan using GPT-5 Nano.
    
    This function hard-fails if GPT-5 Nano is unavailable or returns invalid JSON.
    
    Args:
        query_text: User's query (e.g., "What are my favorite cryptos?")
        
    Returns:
        FactsQueryPlan with intent and parameters
        
    Raises:
        FactsLLMError: If GPT-5 Nano is unavailable or returns invalid JSON
    """
    prompt = f"""You are a Facts query planner. Convert the user's query into a deterministic query plan.

OUTPUT FORMAT (JSON only, no markdown, no explanation):
{{
  "intent": "facts_get_ranked_list" | "facts_get_by_prefix" | "facts_get_exact_key",
  "list_key": "user.favorites.crypto" (for ranked list queries),
  "topic": "crypto" (for ranked list queries),
  "key_prefix": "user.favorites.crypto" (for prefix queries),
  "fact_key": "user.email" (for exact key queries),
  "limit": 100,  // Increased default for unbounded model (pagination only, not storage limit)
  "include_ranks": true,
  "rank": null (for full list) or 2 (for "second favorite"), 3 (for "third favorite"), etc.
}}

INTENT RULES:
1. facts_get_ranked_list: User is asking for a ranked list (e.g., "What are my favorite cryptos?") OR a specific rank (e.g., "What is my second favorite crypto?")
   - Requires: list_key (user.favorites.<topic>) and topic
   - ALWAYS extract the topic from the query, even if you're not sure it exists
   - If the topic doesn't exist, the system will return empty results (that's OK)
   - For ordinal queries (second, third, fourth, etc.), set "rank" to the numeric rank:
     * "second favorite" → rank=2
     * "third favorite" → rank=3
     * "fourth favorite" → rank=4
     * etc.
   - For full list queries (no ordinal), set "rank": null
   - Example (full list): {{"intent": "facts_get_ranked_list", "list_key": "user.favorites.crypto", "topic": "crypto", "limit": 25, "include_ranks": true, "rank": null}}
   - Example (ordinal): "What is my second favorite crypto?" → {{"intent": "facts_get_ranked_list", "list_key": "user.favorites.crypto", "topic": "crypto", "limit": 1, "include_ranks": true, "rank": 2}}
   - Example: "What are my favorite planets?" → {{"intent": "facts_get_ranked_list", "list_key": "user.favorites.planet", "topic": "planet", "limit": 25, "include_ranks": true, "rank": null}}

2. facts_get_by_prefix: User wants facts matching a prefix (e.g., "Show all my favorites" without specifying a topic)
   - Requires: key_prefix
   - ONLY use this if the query truly doesn't specify a topic (e.g., "Show all my favorites", "List my favorites")
   - Example: {{"intent": "facts_get_by_prefix", "key_prefix": "user.favorites", "limit": 50, "include_ranks": true}}

3. facts_get_exact_key: User wants a specific fact (e.g., "What is my email?")
   - Requires: fact_key
   - Example: {{"intent": "facts_get_exact_key", "fact_key": "user.email", "limit": 1, "include_ranks": false}}

SCHEMA LOCK: Ranked lists always use user.favorites.<topic>.<rank>
- Extract topic from query: "cryptos" → "crypto", "colors" → "colors", "planets" → "planet", etc.
- For retrieval queries, ALWAYS try to extract the topic and use facts_get_ranked_list
- Do NOT return ambiguity for retrieval queries - just extract the topic and let the system return empty results if it doesn't exist
- Only use facts_get_by_prefix if the query truly doesn't specify any topic

User query: {query_text}

Output JSON:"""
    
    try:
        logger.debug(f"[FACTS-PLANNER] Planning query: {query_text}")
        llm_response = await run_facts_llm(prompt)
        
        # Parse JSON (extract from markdown if needed)
        json_text = llm_response.strip()
        if json_text.startswith("```"):
            lines = json_text.split("\n")
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    json_lines.append(line)
            json_text = "\n".join(json_lines).strip()
        
        plan_data = json.loads(json_text)
        
        # Detect ordinal queries (second, third, etc.) and extract rank if not already set
        ordinal_parse_source = "none"
        if plan_data.get("intent") == "facts_get_ranked_list" and plan_data.get("rank") is None:
            from server.services.ordinal_detection import detect_ordinal_rank
            detected_rank = detect_ordinal_rank(query_text)
            if detected_rank:
                plan_data["rank"] = detected_rank
                ordinal_parse_source = "planner"
                # Update limit to 1 for ordinal queries
                if plan_data.get("limit", 25) > 1:
                    plan_data["limit"] = 1
                logger.info(f"[FACTS-PLANNER] Detected ordinal rank: {detected_rank} (ordinal_parse_source=planner)")
        
        # Store ordinal_parse_source for telemetry (will be logged but not in schema)
        if ordinal_parse_source != "none":
            logger.info(f"[FACTS-PLANNER] Ordinal query detected: rank={plan_data.get('rank')}, source={ordinal_parse_source}")
        
        plan = FactsQueryPlan(**plan_data)
        
        # Canonicalize topic for ranked list queries using Canonicalizer subsystem
        if plan.intent == "facts_get_ranked_list" and plan.topic:
            from server.services.canonicalizer import canonicalize_topic
            canonicalization_result = canonicalize_topic(plan.topic, invoke_teacher=True)
            canonical_topic = canonicalization_result.canonical_topic
            plan.topic = canonical_topic
            # Rebuild list_key with canonical topic
            from server.services.facts_normalize import canonical_list_key
            plan.list_key = canonical_list_key(canonical_topic)
            logger.debug(
                f"[FACTS-PLANNER] Canonicalized topic: '{plan_data.get('topic')}' → '{canonical_topic}' "
                f"(confidence: {canonicalization_result.confidence:.3f}, source: {canonicalization_result.source})"
            )
        
        logger.debug(f"[FACTS-PLANNER] ✅ Generated plan: intent={plan.intent}, list_key={plan.list_key}, topic={plan.topic}, rank={plan.rank}")
        return plan
        
    except json.JSONDecodeError as e:
        logger.error(f"[FACTS-PLANNER] ❌ Failed to parse JSON: {e}")
        logger.error(f"[FACTS-PLANNER] Raw response: {llm_response[:500]}")
        raise FactsLLMError(f"Facts query planner returned invalid JSON: {e}") from e
    except Exception as e:
        logger.error(f"[FACTS-PLANNER] ❌ Failed to create query plan: {e}")
        raise FactsLLMError(f"Facts query planner failed: {e}") from e

