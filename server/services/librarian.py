"""
Librarian service for intelligent memory ranking and filtering.

This module sits between chat_with_smart_search.py and memory_service_client,
providing smarter ranking and deduplication of memory search results.

Future: Llama 3.2 3B will be integrated here as an optional re-ranker.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryHit:
    """Represents a single memory search result after Librarian processing."""
    source_id: str
    message_id: str
    chat_id: Optional[str]
    role: str  # "user" or "assistant" (extracted from message_id or metadata)
    content: str  # The text content
    score: float  # Similarity score (may be adjusted by Librarian)
    source_type: str = "chat"  # "chat" or "file"
    file_path: Optional[str] = None  # For file sources
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Ensure metadata is always a dict."""
        if self.metadata is None:
            self.metadata = {}


def extract_role_from_message_id(message_id: str) -> str:
    """
    Extract role from message_id pattern.
    
    Message IDs typically follow: "{chat_id}-{role}-{index}"
    e.g., "abc123-user-0" or "abc123-assistant-1"
    
    Also handles patterns like: "{chat_id}-{role}-{message_index}"
    """
    if not message_id:
        return "assistant"  # Default
    
    # Split by "-" and look for "user" or "assistant" tokens
    parts = message_id.split("-")
    for part in parts:
        if part == "user":
            return "user"
        elif part == "assistant":
            return "assistant"
    
    # Fallback: check if message_id contains "user" (case-insensitive)
    if "user" in message_id.lower() and "assistant" not in message_id.lower():
        return "user"
    
    return "assistant"  # Default to assistant (assistant messages are more valuable for answers)


def score_hit_for_query(hit: MemoryHit, query: str) -> float:
    """
    Re-score a memory hit based on heuristics to boost answers over questions.
    
    Args:
        hit: The memory hit to score
        query: The user's query
        
    Returns:
        Adjusted score (higher is better)
    """
    base = hit.score
    text = (hit.content or "").lower()
    query_lower = query.lower().strip()
    
    # Heuristic 1: Penalize question-like messages
    # Questions often start with question words or contain "?"
    is_question = (
        "?" in text or
        text.strip().startswith(("what ", "why ", "how ", "when ", "where ", "who ", "which ", "whose "))
    )
    if is_question:
        base -= 0.05  # Small penalty so answers bubble above questions
    
    # Heuristic 2: Boost assistant messages (they often contain answers)
    if hit.role == "assistant":
        base += 0.05
    
    # Heuristic 3: Small boost if query tokens appear in the answer content
    # This helps match "favorite color" with "My favorite color is blue"
    if query_lower:
        query_words = set(query_lower.split())
        text_words = set(text.split())
        # Count how many query words appear in the text
        matching_words = query_words.intersection(text_words)
        if matching_words:
            # Boost proportional to match ratio (capped at 0.03)
            match_ratio = len(matching_words) / max(len(query_words), 1)
            base += min(0.03 * match_ratio, 0.03)
    
    # Heuristic 4: Boost direct answer patterns
    # Patterns like "is blue", "are X, Y, Z", "is <value>"
    if hit.role == "assistant":
        # Look for patterns that suggest a direct answer
        answer_patterns = [
            " is ",
            " are ",
            " was ",
            " were ",
            ": ",
            "— ",  # em dash
            "- ",   # regular dash
        ]
        if any(pattern in text for pattern in answer_patterns):
            base += 0.02
    
    return base


def deduplicate_hits(hits: List[MemoryHit]) -> List[MemoryHit]:
    """
    Remove duplicate hits based on message_id.
    
    Args:
        hits: List of memory hits
        
    Returns:
        Deduplicated list (preserves order of first occurrence)
    """
    seen_ids = set()
    result: List[MemoryHit] = []
    
    for hit in hits:
        key = hit.message_id
        if key in seen_ids:
            continue
        seen_ids.add(key)
        result.append(hit)
    
    return result


def get_relevant_memory(
    project_id: str,
    query: str,
    *,
    chat_id: Optional[str] = None,
    max_hits: int = 30,
) -> List[MemoryHit]:
    """
    High-level helper used by chat_with_smart_search.
    
    Calls the existing Memory Service search, applies Librarian ranking/deduplication,
    and returns clean, ordered MemoryHit instances.
    
    Args:
        project_id: The project ID to search
        query: The search query (typically the user's message)
        chat_id: Optional chat ID (deprecated, kept for compatibility)
        max_hits: Maximum number of hits to return (default: 30)
        
    Returns:
        List of MemoryHit instances, sorted by score (descending)
    """
    from . import memory_service_client
    
    # 1) Call existing memory search
    # Request more results than we need so we can re-rank and filter
    client = memory_service_client.get_memory_client()
    source_ids = memory_service_client.get_memory_sources_for_project(project_id)
    
    # Request 3x the limit to have enough candidates for re-ranking
    raw_results = client.search(
        project_id=project_id,
        query=query,
        limit=max_hits * 3,
        source_ids=source_ids,
        chat_id=None  # Include all chats for cross-chat memory
    )
    
    if not raw_results:
        logger.info(
            "[LIBRARIAN] %s: query=%r -> 0 hits (no results from Memory Service)",
            project_id,
            query[:80] if query else ""
        )
        return []
    
    # 2) Convert raw results to MemoryHit objects
    hits: List[MemoryHit] = []
    for r in raw_results:
        # Extract role from message_id or metadata
        role = extract_role_from_message_id(r.get("message_id", ""))
        
        # Try to get role from metadata if available
        if "role" in r:
            role = r["role"]
        
        hit = MemoryHit(
            source_id=r.get("source_id", ""),
            message_id=r.get("message_id", ""),
            chat_id=r.get("chat_id"),
            role=role,
            content=r.get("text", ""),
            score=float(r.get("score", 0.0)),
            source_type=r.get("source_type", "chat"),
            file_path=r.get("file_path"),
            created_at=r.get("created_at"),
            metadata=r.get("metadata", {}) or {}
        )
        hits.append(hit)
    
    # 3) Deduplicate
    hits = deduplicate_hits(hits)
    
    # 4) Re-score for the specific query
    for hit in hits:
        hit.score = score_hit_for_query(hit, query)
    
    # 5) Sort by score descending
    hits.sort(key=lambda h: h.score, reverse=True)
    
    # 6) Truncate to max_hits
    final_hits = hits[:max_hits]
    
    logger.info(
        "[LIBRARIAN] %s: query=%r -> %d hits (requested=%d, raw_results=%d)",
        project_id,
        query[:80] if query else "",
        len(final_hits),
        max_hits,
        len(raw_results)
    )
    
    # Log top 5 hits for debugging
    if final_hits:
        logger.info("[LIBRARIAN] Top 5 hits:")
        for i, hit in enumerate(final_hits[:5], 1):
            content_preview = hit.content[:60].replace("\n", " ") if hit.content else ""
            logger.info(
                "[LIBRARIAN]   %d. [%s] score=%.4f: %s...",
                i,
                hit.role,
                hit.score,
                content_preview
            )
    
    return final_hits


def format_hits_as_context(hits: List[MemoryHit]) -> str:
    """
    Format a list of MemoryHit objects into the context string format
    expected by the prompt formatter.
    
    This converts MemoryHit objects back to the dict format that
    format_context() expects, maintaining backward compatibility.
    
    Args:
        hits: List of MemoryHit objects
        
    Returns:
        Formatted context string (same format as MemoryServiceClient.format_context)
    """
    if not hits:
        return ""
    
    # Convert MemoryHit back to dict format for format_context
    results = []
    for hit in hits:
        result_dict = {
            "source_id": hit.source_id,
            "message_id": hit.message_id,
            "chat_id": hit.chat_id,
            "text": hit.content,
            "score": hit.score,
            "source_type": hit.source_type,
            "file_path": hit.file_path,
            **hit.metadata
        }
        results.append(result_dict)
    
    # Use the existing format_context method
    from . import memory_service_client
    client = memory_service_client.get_memory_client()
    return client.format_context(results)

