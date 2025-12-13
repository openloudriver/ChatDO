"""
Smart search classifier - decides when to use web search for chat queries.
Uses heuristics + LLM to determine if a question needs fresh web information.
"""
import logging
import json
import requests
import os
from typing import Optional

logger = logging.getLogger(__name__)

AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")


class SearchDecision:
    """Decision about whether to use web search."""
    def __init__(self, use_search: bool, reason: str, query: str = ""):
        self.use_search = use_search
        self.reason = reason
        self.query = query


async def decide_web_search(user_message: str) -> SearchDecision:
    """
    Decide if we should use web search for this user message.
    
    Uses heuristics first, then LLM classifier for better accuracy.
    
    Args:
        user_message: The user's message/question
        
    Returns:
        SearchDecision with use_search, reason, and query
    """
    lower = user_message.lower()
    
    # Quick heuristic check first
    heuristic_triggers = [
        'today', 'right now', 'latest', 'breaking', 'current',
        'this week', 'this month', 'this year',
        'price of', 'stock price', 'btc price', 'msty price',
        'who is the current', 'election', 'news about', 'update on',
        'what happened', 'what\'s happening', 'what is happening',
        'can you look this up', 'check online', 'search for',
        'look up', 'find out', 'what\'s the latest', 'what is the latest'
    ]
    
    heuristic_hit = any(trigger in lower for trigger in heuristic_triggers)
    
    # Check for explicit search commands (these should be handled separately)
    explicit_search_patterns = [
        'search:', 'web search:', 'brave:', 'find:'
    ]
    is_explicit_search = any(lower.startswith(pattern) for pattern in explicit_search_patterns)
    
    if is_explicit_search:
        # Explicit search commands are handled by the main endpoint, not here
        return SearchDecision(use_search=False, reason="explicit-search-command", query="")
    
    # If heuristic strongly suggests search (multiple triggers or very clear patterns), skip LLM for speed
    strong_heuristic_patterns = [
        'latest', 'what\'s the latest', 'what is the latest', 'current', 'today', 'this week',
        'breaking', 'news about', 'update on', 'what happened', 'what\'s happening'
    ]
    strong_heuristic = any(pattern in lower for pattern in strong_heuristic_patterns)
    
    # For strong heuristic matches, skip LLM call for instant results
    if strong_heuristic:
        logger.info(f"Strong heuristic match detected, skipping LLM classifier for speed: {user_message[:100]}")
        return SearchDecision(use_search=True, reason="strong-heuristic", query=user_message)
    
    # LLM classifier for better accuracy (only for ambiguous cases)
    try:
        prompt = f"""You are a classifier that decides if we must use live web search to answer a question.

User question:
"{user_message}"

Respond ONLY in JSON with:
{{
  "useSearch": true | false,
  "query": string,
  "reason": string
}}

Use web search when the answer requires up-to-date or factual external information:
- Current events, news, "latest", "today", "this week"
- Live prices, stock prices, current values
- Current people in roles (e.g., "current president")
- Recent developments, breaking news
- Information that changes frequently

Do NOT use search for:
- Timeless concepts, definitions, general knowledge
- Math, coding help, technical explanations
- Personal advice, opinions, creative tasks
- Historical facts that don't change
- Questions about code, architecture, design patterns

If you set useSearch to false, query can be an empty string.
Be conservative - only use search when it's clearly necessary for up-to-date information."""

        payload = {
            "role": "chatdo",
            "intent": "general_chat",
            "priority": "low",  # Classifier is cheap
            "privacyLevel": "normal",
            "costTier": "cheap",
            "input": {
                "messages": [
                    {"role": "system", "content": "You are a JSON-only classifier. Respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
            },
        }
        
        # Use shorter timeout for faster classification - classifier should be quick
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("ok"):
            logger.warning("Classifier API error, falling back to heuristic")
            if heuristic_hit:
                return SearchDecision(use_search=True, reason="heuristic-fallback", query=user_message)
            return SearchDecision(use_search=False, reason="api-error", query="")
        
        assistant_messages = data.get("output", {}).get("messages", [])
        if not assistant_messages:
            logger.warning("Classifier returned no messages, falling back to heuristic")
            if heuristic_hit:
                return SearchDecision(use_search=True, reason="heuristic-fallback", query=user_message)
            return SearchDecision(use_search=False, reason="no-response", query="")
        
        response_text = assistant_messages[0].get("content", "")
        
        # Try to extract JSON from the response
        try:
            # Sometimes LLM wraps JSON in markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            parsed = json.loads(response_text)
            llm_decision = SearchDecision(
                use_search=bool(parsed.get("useSearch", False)),
                reason=parsed.get("reason", "llm-classifier"),
                query=parsed.get("query", user_message)
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse classifier JSON: {e}, response: {response_text[:200]}")
            # Fall back to heuristic
            if heuristic_hit:
                return SearchDecision(use_search=True, reason="parse-error-heuristic", query=user_message)
            return SearchDecision(use_search=False, reason="parse-error", query="")
        
        # Combine heuristic + LLM decision
        # If heuristic says yes but LLM says no, trust heuristic (be conservative)
        if heuristic_hit and not llm_decision.use_search:
            logger.info(f"Classifier: heuristic override (heuristic=yes, llm=no) for: {user_message[:100]}")
            return SearchDecision(use_search=True, reason="heuristic-override", query=llm_decision.query or user_message)
        
        return llm_decision
        
    except Exception as e:
        logger.exception(f"Classifier error: {e}")
        # Fall back to heuristic on any error
        if heuristic_hit:
            return SearchDecision(use_search=True, reason="error-heuristic", query=user_message)
        return SearchDecision(use_search=False, reason="error", query="")

