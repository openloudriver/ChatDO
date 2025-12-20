"""
Librarian service for intelligent memory ranking and filtering.

This module provides smarter ranking and deduplication of memory search results.
Memory Service is now a tool only - GPT-5 always generates responses.

NOTE: Response generation functions have been removed. This module now only
provides ranking, deduplication, and formatting utilities.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Recency boost weight: newer messages get a small boost (0.0 to RECENCY_WEIGHT)
RECENCY_WEIGHT = 0.15


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
    recency_boost: float = 0.0  # Recency boost factor (0.0 to RECENCY_WEIGHT)
    message_uuid: Optional[str] = None  # Stable UUID for deep linking/citations

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
    
    # Heuristic 5: Boost file sources over chat sources for file/repository queries
    # When query is about files, folders, repository structure, prioritize file sources
    file_query_keywords = [
        "file", "files", "folder", "folders", "directory", "directories",
        "repo", "repository", "structure", "codebase", "project structure",
        "what's in", "list", "show me", "contents"
    ]
    is_file_query = any(keyword in query_lower for keyword in file_query_keywords)
    if is_file_query:
        if hit.source_type == "file" or hit.file_path:
            # Strong boost for file sources when query is about files/repos
            base += 0.15
        elif hit.source_type == "chat" or (hit.source_id and hit.source_id.startswith("project-")):
            # Penalize chat sources for file queries
            base -= 0.10
    
    # Heuristic 6: Add recency boost (computed in get_relevant_memory)
    base += hit.recency_boost
    
    return base


def make_topic_key(hit: MemoryHit) -> str:
    """
    Create a lightweight topic key from hit content for near-duplicate detection.
    
    Args:
        hit: The memory hit
        
    Returns:
        A normalized topic key string (first 160 chars, lowercased, stripped)
    """
    text = (hit.content or "").strip().lower()
    # Remove multiple spaces
    text = " ".join(text.split())
    # Take first 160 chars
    return text[:160]


def deduplicate_hits(hits: List[MemoryHit]) -> List[MemoryHit]:
    """
    Remove duplicate hits based on message_id and near-duplicate content.
    
    For near-duplicates (same topic key), keeps the newest hit (by timestamp)
    or highest-scoring hit if timestamps are unavailable.
    
    Args:
        hits: List of memory hits (should be pre-sorted by score descending)
        
    Returns:
        Deduplicated list, sorted by score (highest first)
    """
    # First pass: exact message_id deduplication
    seen_ids = set()
    id_deduped: List[MemoryHit] = []
    for hit in hits:
        if hit.message_id in seen_ids:
            continue
        seen_ids.add(hit.message_id)
        id_deduped.append(hit)
    
    # Second pass: topic key deduplication (newest wins)
    topic_map: Dict[str, MemoryHit] = {}
    dropped_by_topic: Dict[str, List[str]] = {}
    
    for hit in id_deduped:
        topic_key = make_topic_key(hit)
        
        if topic_key not in topic_map:
            # First occurrence of this topic
            topic_map[topic_key] = hit
        else:
            # We have a near-duplicate - keep the newest or highest-scoring
            existing = topic_map[topic_key]
            
            # Try to compare by timestamp
            existing_ts = _parse_timestamp(existing.created_at)
            hit_ts = _parse_timestamp(hit.created_at)
            
            if existing_ts and hit_ts:
                # Both have timestamps - keep the newer one
                if hit_ts > existing_ts:
                    if topic_key not in dropped_by_topic:
                        dropped_by_topic[topic_key] = []
                    dropped_by_topic[topic_key].append(existing.message_id)
                    topic_map[topic_key] = hit
                else:
                    dropped_by_topic.setdefault(topic_key, []).append(hit.message_id)
            else:
                # No timestamps or only one has timestamp - use score
                if hit.score > existing.score:
                    if topic_key not in dropped_by_topic:
                        dropped_by_topic[topic_key] = []
                    dropped_by_topic[topic_key].append(existing.message_id)
                    topic_map[topic_key] = hit
                else:
                    dropped_by_topic.setdefault(topic_key, []).append(hit.message_id)
    
    # Log deduplication at DEBUG level
    if dropped_by_topic and logger.isEnabledFor(logging.DEBUG):
        for topic_key, dropped_ids in dropped_by_topic.items():
            kept = topic_map[topic_key]
            logger.debug(
                "[LIBRARIAN] dedupe topic_key=%r kept=message_id=%s dropped=%s",
                topic_key[:80],
                kept.message_id,
                dropped_ids
            )
    
    # Return deduplicated hits, sorted by score (highest first)
    result = list(topic_map.values())
    result.sort(key=lambda h: h.score, reverse=True)
    
    return result


def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a timestamp string to datetime.
    
    Handles ISO format strings and common variations.
    
    Args:
        ts_str: Timestamp string (ISO format or None)
        
    Returns:
        datetime object or None if parsing fails
    """
    if not ts_str:
        return None
    
    try:
        # Try ISO format (with or without Z)
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        try:
            # Try common formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
    
    return None


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
    retrieves current facts, and returns clean, ordered MemoryHit instances.
    
    Args:
        project_id: The project ID to search
        query: The search query (typically the user's message)
        chat_id: Optional chat ID (deprecated, kept for compatibility)
        max_hits: Maximum number of hits to return (default: 30)
        
    Returns:
        List of MemoryHit instances, sorted by score (descending)
    """
    from . import memory_service_client
    
    # 1) Retrieve current facts first (fast path)
    fact_hits = []
    try:
        import requests
        client = memory_service_client.get_memory_client()
        if client.is_available():
            # Search for facts matching the query
            try:
                response = requests.post(
                    f"{client.base_url}/search-facts",
                    json={
                        "project_id": project_id,
                        "query": query,
                        "limit": 10
                    },
                    timeout=5
                )
                if response.status_code == 200:
                    facts_data = response.json()
                    facts_list = facts_data.get("facts", [])
                    if facts_list:
                        logger.info(f"[FACTS] Found {len(facts_list)} facts for query '{query}' in project {project_id}")
                    for fact in facts_list:
                        # Create a MemoryHit-like entry for the fact
                        # Format fact content in a user-friendly way
                        fact_key = fact.get('fact_key', '')
                        value_text = fact.get('value_text', '')
                        
                        # Convert fact_key to readable format (e.g., "user.color" -> "favorite color")
                        readable_key = fact_key.replace('user.', '').replace('_', ' ')
                        if 'favorite' in readable_key or 'preferred' in readable_key:
                            content = f"Your {readable_key} is {value_text}"
                        else:
                            content = f"Your {readable_key}: {value_text}"
                        
                        fact_hit = MemoryHit(
                            source_id=f"project-{project_id}",
                            message_id=fact.get("source_message_uuid", ""),  # Use source_message_uuid for citation
                            chat_id=None,
                            role="fact",
                            content=content,
                            score=0.95,  # High score for facts
                            source_type="fact",
                            file_path=None,
                            created_at=fact.get("created_at"),
                            metadata={
                                "fact_id": fact.get("fact_id"),
                                "fact_key": fact.get("fact_key"),
                                "value_text": fact.get("value_text"),
                                "value_type": fact.get("value_type"),
                                "source_message_uuid": fact.get("source_message_uuid"),
                                "is_fact": True
                            },
                            message_uuid=fact.get("source_message_uuid")  # For deep linking - stored in metadata too
                        )
                        fact_hits.append(fact_hit)
                        logger.debug(f"[FACTS] Added fact hit: {fact_key}={value_text}")
                    logger.info(f"[FACTS] Created {len(fact_hits)} fact hits from {len(facts_list)} facts")
            except Exception as e:
                logger.warning(f"Fact search failed: {e}", exc_info=True)
    except Exception as e:
        logger.debug(f"Fact retrieval failed: {e}")
    
    # 2) Call existing memory search
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
    
    logger.info(f"[LIBRARIAN] raw_results={len(raw_results)}, fact_hits={len(fact_hits)}")
    if not raw_results and not fact_hits:
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
        
        metadata = r.get("metadata", {}) or {}
        # Include message_uuid in metadata for citations
        if "message_uuid" in r:
            metadata["message_uuid"] = r["message_uuid"]
        
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
            metadata=metadata
        )
        hits.append(hit)
    
    # 3) Add fact hits to the beginning (high priority)
    hits = fact_hits + hits
    
    # 3) Compute recency boost for all hits
    # Find min and max timestamps to normalize age
    timestamps: List[datetime] = []
    for hit in hits:
        ts = _parse_timestamp(hit.created_at)
        if ts:
            timestamps.append(ts)
    
    if timestamps:
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        ts_range = (max_ts - min_ts).total_seconds() if max_ts > min_ts else 1.0
        
        # Compute recency boost for each hit
        for hit in hits:
            ts = _parse_timestamp(hit.created_at)
            if ts and ts_range > 0:
                # Normalize age: 0 = oldest, 1 = newest
                age_seconds = (ts - min_ts).total_seconds()
                age_norm = age_seconds / ts_range
                hit.recency_boost = age_norm * RECENCY_WEIGHT
                
                # DEBUG logging for recency boost computation
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[LIBRARIAN] recency_boost message_id=%s age_norm=%.4f recency_boost=%.4f",
                        hit.message_id,
                        age_norm,
                        hit.recency_boost
                    )
            else:
                # No timestamp - treat as old (no recency boost)
                hit.recency_boost = 0.0
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[LIBRARIAN] recency_boost message_id=%s age_norm=N/A recency_boost=0.0 (no timestamp)",
                        hit.message_id
                    )
    else:
        # No timestamps available - no recency boost
        for hit in hits:
            hit.recency_boost = 0.0
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[LIBRARIAN] recency_boost: No timestamps available for any hits")
    
    # 4) Re-score for the specific query (includes recency boost)
    for hit in hits:
        hit.score = score_hit_for_query(hit, query)
    
    # 5) Sort by score descending (before deduplication)
    hits.sort(key=lambda h: h.score, reverse=True)
    
    # 6) Deduplicate (newest wins for near-duplicates)
    hits = deduplicate_hits(hits)
    
    # 7) Truncate to max_hits
    final_hits = hits[:max_hits]
    
    # 8) Enhanced logging
    query_preview = (query[:80] + "...") if len(query) > 80 else query
    logger.info(
        "[LIBRARIAN] query=%r raw_hits=%d final_hits=%d",
        query_preview,
        len(raw_results),
        len(final_hits)
    )
    
    # Log top 10 hits with detailed info
    if final_hits:
        for i, hit in enumerate(final_hits[:10], 1):
            content_preview = hit.content[:80].replace("\n", " ") if hit.content else ""
            
            # Calculate age
            age_str = "unknown"
            hit_ts = _parse_timestamp(hit.created_at)
            if hit_ts:
                now = datetime.now(hit_ts.tzinfo) if hit_ts.tzinfo else datetime.now()
                age_delta = now - hit_ts
                age_days = age_delta.total_seconds() / 86400
                if age_days < 1:
                    age_hours = age_delta.total_seconds() / 3600
                    age_str = f"{age_hours:.1f}h" if age_hours >= 1 else f"{age_delta.total_seconds() / 60:.0f}m"
                else:
                    age_str = f"{age_days:.1f}d"
            
            logger.info(
                "[LIBRARIAN] top_hit[%d] role=%s score=%.4f age=%s recency_boost=%.4f %r",
                i - 1,
                hit.role,
                hit.score,
                age_str,
                hit.recency_boost,
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
        # Filter out .DS_Store mentions from file listings in Memory context
        # This handles old indexed content that may still reference .DS_Store files
        content = hit.content
        if content:
            import re
            # Aggressively remove ALL .DS_Store mentions in any context
            # Remove .DS_Store from anywhere in the text (standalone, in lists, etc.)
            content = re.sub(r'\.DS_Store', '', content, flags=re.IGNORECASE)
            # Remove lines that only contain .DS_Store
            content = re.sub(r'^\s*\.DS_Store\s*$', '', content, flags=re.MULTILINE)
            # Remove .DS_Store from bullet lists (various formats)
            content = re.sub(r'[-*•]\s*\.DS_Store\s*\n?', '', content, flags=re.IGNORECASE)
            # Remove .DS_Store from numbered lists
            content = re.sub(r'\d+\.\s*\.DS_Store\s*\n?', '', content, flags=re.IGNORECASE)
            # Remove .DS_Store from comma-separated lists
            content = re.sub(r',\s*\.DS_Store\s*,', ',', content, flags=re.IGNORECASE)
            content = re.sub(r',\s*\.DS_Store\s*$', '', content, flags=re.IGNORECASE | re.MULTILINE)
            content = re.sub(r'^\s*\.DS_Store\s*,', '', content, flags=re.IGNORECASE | re.MULTILINE)
            # Remove .DS_Store from markdown code blocks or inline code
            content = re.sub(r'`\.DS_Store`', '', content, flags=re.IGNORECASE)
            # Clean up extra commas/spaces/newlines
            content = re.sub(r',\s*,', ',', content)
            content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)  # Max 2 consecutive newlines
            content = re.sub(r'^\s+|\s+$', '', content, flags=re.MULTILINE)  # Trim lines
        
        result_dict = {
            "source_id": hit.source_id,
            "message_id": hit.message_id,
            "chat_id": hit.chat_id,
            "text": content,
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


# DEPRECATED: Librarian response generation removed.
# Memory Service is now a tool only - GPT-5 always generates responses.
# The following functions have been removed:
# - generate_memory_response_with_gpt5_mini() - No longer generates responses
# - should_escalate_to_gpt5() - No escalation needed, GPT-5 is always used


def post_process_memory_citations(
    response: str,
    hits: List[MemoryHit],
    max_inline_citations: int = 1
) -> tuple[str, List[int]]:
    """
    Post-process Memory citations to keep only the "best-1" (or adaptive expansion).
    
    Strategy:
    - Default: Keep only best 1 citation
    - Adaptive expansion: If response is multi-claim (lists/bullets/multiple sentences
      with distinct facts) and no single memory hit supports all claims, allow up to 3
    
    Citation scoring (prefer in order):
    1. User messages > Assistant messages
    2. Newest > Oldest (by created_at or message_id)
    3. Higher score > Lower score
    
    Args:
        response: The generated response text with citations like [M1], [M2], [M1, M2]
        hits: List of Memory hits (indexed 0-based, will map to M1, M2, M3...)
        max_inline_citations: Maximum citations to keep (default 1, can expand to 3)
        
    Returns:
        Tuple of (cleaned_response: str, citation_indices_to_keep: List[int])
        citation_indices_to_keep are 0-based indices into hits list (M1=0, M2=1, etc.)
    """
    import re
    
    # Extract all citation patterns: [M1], [M2], [M1, M2], [M1, M2, M3], etc.
    # Pattern matches: [M1], [M2], [M1, M2], [M1, M2, M3], etc.
    citation_pattern = re.compile(r'\[M(\d+(?:\s*,\s*M?\d+)*)\]')
    
    # Find all citations in the response
    found_citations = set()
    for match in citation_pattern.finditer(response):
        citation_str = match.group(1)
        # Parse individual citation numbers
        # Handle both "1, 2" and "1, M2" formats
        parts = citation_str.split(',')
        for part in parts:
            part = part.strip()
            # Remove 'M' prefix if present, then convert to int
            if part.startswith('M'):
                part = part[1:]
            try:
                num = int(part)
                found_citations.add(num)
            except ValueError:
                # Skip invalid citation numbers
                continue
    
    if not found_citations:
        # No citations found, return response as-is
        return response, []
    
    # Convert citation numbers (1-based) to hit indices (0-based)
    # M1 = hits[0], M2 = hits[1], etc.
    cited_indices = [num - 1 for num in found_citations if 1 <= num <= len(hits)]
    
    if not cited_indices:
        # Citations reference non-existent hits, remove all citations
        cleaned_response = citation_pattern.sub('', response)
        return cleaned_response, []
    
    # Score citations for ranking
    def score_citation(hit_idx: int) -> tuple[float, int]:
        """Return (score, hit_idx) for sorting. Higher score = better."""
        if hit_idx >= len(hits):
            return (-999, hit_idx)  # Invalid index
        
        hit = hits[hit_idx]
        score = hit.score
        
        # Boost user messages over assistant
        if hit.role == "user":
            score += 1000
        elif hit.role == "assistant":
            score += 500
        
        # Boost newer messages (if created_at available)
        if hit.created_at:
            try:
                from datetime import datetime
                created = datetime.fromisoformat(hit.created_at.replace('Z', '+00:00'))
                now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
                age_days = (now - created).days
                # Newer = higher boost (max 100 points for messages < 1 day old)
                recency_boost = max(0, 100 - age_days * 2)
                score += recency_boost
            except:
                pass
        
        return (score, hit_idx)
    
    # Score and sort citations
    scored_citations = sorted(
        [(score_citation(idx), idx) for idx in cited_indices],
        key=lambda x: x[0],
        reverse=True
    )
    
    # Determine if response is multi-claim
    is_multi_claim = _detect_multi_claim(response)
    
    # Determine max citations to keep
    if is_multi_claim:
        # Check if any single hit supports all claims
        # For now, if we have multiple distinct citations, assume no single hit supports all
        if len(cited_indices) > 1:
            max_citations = min(3, max_inline_citations * 3)
        else:
            max_citations = max_inline_citations
    else:
        max_citations = max_inline_citations
    
    # Keep top citations
    citations_to_keep = [idx for (_, idx) in scored_citations[:max_citations]]
    citations_to_keep.sort()  # Sort by index for consistent ordering
    
    # Build mapping: old citation number -> new citation number (or None if removed)
    old_to_new = {}
    for new_idx, old_idx in enumerate(citations_to_keep, start=1):
        old_to_new[old_idx] = new_idx
    
    # Remove citations that aren't in citations_to_keep
    def replace_citation(match):
        citation_str = match.group(1)
        # Parse citation numbers (handle both "1, 2" and "1, M2" formats)
        parts = citation_str.split(',')
        numbers = []
        for part in parts:
            part = part.strip()
            if part.startswith('M'):
                part = part[1:]
            try:
                num = int(part)
                numbers.append(num)
            except ValueError:
                continue
        
        # Convert to hit indices (0-based)
        old_indices = [num - 1 for num in numbers if 1 <= num <= len(hits)]
        
        # Filter to only keep citations we want
        kept_indices = [idx for idx in old_indices if idx in citations_to_keep]
        
        if not kept_indices:
            # Remove this citation entirely
            return ''
        
        # Map to new citation numbers
        new_numbers = [old_to_new[idx] for idx in kept_indices]
        new_numbers.sort()
        
        if len(new_numbers) == 1:
            return f'[M{new_numbers[0]}]'
        else:
            # Format as [M1, M2] (not [MM1, M2])
            return f'[M{", ".join(str(n) for n in new_numbers)}]'
    
    # Replace citations in response
    cleaned_response = citation_pattern.sub(replace_citation, response)

    # Clean up any double spaces or trailing commas left by removed citations
    # IMPORTANT: Preserve newlines - only collapse spaces/tabs, not newlines
    # Replace multiple spaces/tabs with single space, but keep newlines
    cleaned_response = re.sub(r'[ \t]+', ' ', cleaned_response)  # Only collapse spaces/tabs
    cleaned_response = re.sub(r'[ \t]*\n[ \t]*', '\n', cleaned_response)  # Normalize newlines (remove spaces around them)
    cleaned_response = re.sub(r'\s*,\s*,', ',', cleaned_response)  # Remove double commas
    cleaned_response = cleaned_response.strip()
    
    logger.info(f"[CITATIONS] Post-processed: kept {len(citations_to_keep)}/{len(cited_indices)} citations (multi-claim={is_multi_claim})")
    
    return cleaned_response, citations_to_keep


def _detect_multi_claim(response: str) -> bool:
    """
    Detect if response is multi-claim (lists/bullets/multiple sentences with distinct facts).
    
    Heuristics:
    - Contains bullet points (-, *, •)
    - Contains numbered lists (1., 2., etc.)
    - Multiple sentences with different topics/facts
    - Contains "and" or "also" connecting distinct facts
    """
    import re
    
    # Check for bullet points
    bullet_pattern = re.compile(r'^[\s]*[-*•]\s+', re.MULTILINE)
    if bullet_pattern.search(response):
        return True
    
    # Check for numbered lists
    numbered_pattern = re.compile(r'^\s*\d+[.)]\s+', re.MULTILINE)
    if numbered_pattern.search(response):
        return True
    
    # Check for multiple sentences with different structures
    sentences = re.split(r'[.!?]\s+', response)
    if len(sentences) >= 3:
        # Check if sentences have different structures (indicating different topics)
        # Simple heuristic: if we have 3+ sentences, likely multi-claim
        return True
    
    # Check for "and" or "also" connecting distinct facts
    # Look for patterns like "X and Y" or "X. Also, Y"
    and_pattern = re.compile(r'\b(and|also|additionally|furthermore|moreover)\b', re.IGNORECASE)
    if and_pattern.search(response) and len(sentences) >= 2:
        return True
    
    return False

