"""
Orchestrator Web Search Integration (Phase 1).

Integrates existing web search infrastructure into the Orchestrator.
Uses deterministic keyword matrix and Brave Search API.
"""
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from server.services.web_policy import should_use_web
from chatdo.tools import web_search

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorWebContext:
    """Web search context for Orchestrator."""
    used_web: bool
    results: Optional[List[Dict[str, Any]]] = None


def format_web_block(results: List[Dict[str, Any]]) -> str:
    """
    Format web search results into a system message block for GPT-5.
    
    Args:
        results: List of web search result dictionaries with title, url, snippet
        
    Returns:
        Formatted string to include in GPT-5 system message
    """
    if not results:
        return ""
    
    lines = [
        "You have access to the following up-to-date web search results.",
        "When you use a specific fact from a source, add a citation like [1] or [2] at the end of the relevant sentence.",
        "Use these sources only when needed; otherwise, answer normally.",
        ""
    ]
    
    for i, result in enumerate(results[:5], 1):  # Limit to top 5 results
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        snippet = result.get("snippet", "")
        
        url_str = f" ({url})" if url else ""
        lines.append(f"{i}. {title}{url_str}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")  # Blank line between results
    
    return "\n".join(lines)


async def build_web_context(message_text: str) -> OrchestratorWebContext:
    """
    Build web search context for a user message.
    
    Uses existing web_policy to determine if web search is needed,
    then calls Brave Search API if required.
    
    Args:
        message_text: The user's message/question
        
    Returns:
        OrchestratorWebContext with used_web flag and results (if any)
    """
    # Always use "auto" mode - let the keyword matrix decide
    use_web = should_use_web(message_text=message_text, web_mode="auto")
    
    if not use_web:
        logger.debug(f"[ORCH-WEB] Web search not needed for: {message_text[:100]}...")
        return OrchestratorWebContext(used_web=False, results=None)
    
    logger.info(f"[ORCH-WEB] Web search triggered for: {message_text[:100]}...")
    
    try:
        # Use the message text as the search query
        search_query = message_text
        
        # Call Brave Search API (synchronous for Phase 1)
        search_results = web_search.search_web(
            query=search_query,
            max_results=5,  # Limit to 5 for context size
            freshness=None  # No freshness filter for now
        )
        
        if not search_results or len(search_results) == 0:
            logger.warning(f"[ORCH-WEB] Web search returned no results for: {search_query[:100]}...")
            return OrchestratorWebContext(used_web=False, results=None)
        
        # Normalize results to our format
        normalized_results = []
        for result in search_results:
            normalized_results.append({
                "title": result.get("title", "Untitled"),
                "url": result.get("url", ""),
                "snippet": result.get("snippet", "")
            })
        
        logger.info(f"[ORCH-WEB] Web search completed: {len(normalized_results)} results")
        return OrchestratorWebContext(used_web=True, results=normalized_results)
        
    except Exception as e:
        logger.warning(f"[ORCH-WEB] Web search failed, falling back to GPT-only: {e}", exc_info=True)
        # On error, return False so we continue without web
        return OrchestratorWebContext(used_web=False, results=None)

