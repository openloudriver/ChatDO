"""
Facts Adapter - Converts Facts DB results to DiscoveryHit format.

Uses direct DB access (same strategy as librarian.search_facts_ranked_list)
for fast, deterministic results that don't depend on Memory Service availability.
"""
import logging
from typing import List, Dict, Tuple
from server.contracts.discovery import DiscoveryQuery, DiscoveryHit, DiscoverySource

logger = logging.getLogger(__name__)


def search(query: DiscoveryQuery) -> Tuple[List[DiscoveryHit], Dict[str, any]]:
    """
    Search facts and return DiscoveryHit instances.
    
    Args:
        query: DiscoveryQuery with project_id, query string, limit, etc.
        
    Returns:
        Tuple of (hits: List[DiscoveryHit], meta: Dict)
        - hits: List of DiscoveryHit instances from Facts domain
        - meta: Metadata dict with timing, counts, etc.
    """
    import time
    start_time = time.time()
    
    hits = []
    meta = {
        "count": 0,
        "timing_ms": 0.0,
        "degraded": None
    }
    
    if not query.project_id:
        logger.warning("[DISCOVERY-FACTS] project_id required for facts search")
        return hits, meta
    
    try:
        from memory_service.memory_dashboard import db
        from server.services.projects.project_resolver import validate_project_uuid
        
        # Enforce Facts DB contract: project_id must be UUID
        validate_project_uuid(query.project_id)
        
        source_id = f"project-{query.project_id}"
        
        # Search facts directly from DB (fast, deterministic)
        facts = db.search_current_facts(
            project_id=query.project_id,
            query=query.query,
            limit=query.limit,
            source_id=source_id,
            exclude_message_uuid=None  # Discovery search doesn't exclude current message
        )
        
        # Convert facts to DiscoveryHit instances
        for fact in facts:
            fact_id = fact.get("fact_id")
            fact_key = fact.get("fact_key", "")
            value_text = fact.get("value_text", "")
            source_message_uuid = fact.get("source_message_uuid")
            
            # Generate stable hit ID
            hit_id = f"facts:{fact_id}"
            
            # Create readable title from fact_key
            title = fact_key.replace("user.", "").replace("_", " ").title()
            
            # Format created_at timestamp
            created_at_str = None
            created_at = fact.get("created_at")
            if created_at:
                if hasattr(created_at, "isoformat"):
                    created_at_str = created_at.isoformat()
                else:
                    created_at_str = str(created_at)
            
            # Include schema_hint if available (for ranked lists: user.favorites.*)
            source_meta = {
                "fact_key": fact_key,
                "value_type": fact.get("value_type", "string"),
                "confidence": fact.get("confidence", 1.0),
                "is_current": fact.get("is_current", True)
            }
            
            schema_hint = fact.get("schema_hint")
            if schema_hint:
                source_meta["schema_hint"] = schema_hint
            elif fact_key.startswith("user.favorites."):
                # Derive schema_hint from fact_key if not provided
                import re
                match = re.match(r'^user\.favorites\.([^.]+)\.(\d+)$', fact_key)
                if match:
                    topic = match.group(1)
                    source_meta["schema_hint"] = {
                        "domain": "ranked_list",
                        "topic": topic,
                        "key": fact_key,
                        "key_prefix": f"user.favorites.{topic}"  # For aggregation queries
                    }
            
            # Create source for deep linking
            source = DiscoverySource(
                kind="chat_message",
                source_message_uuid=source_message_uuid,
                source_fact_id=fact_id,
                snippet=value_text[:100] if len(value_text) > 100 else value_text,
                created_at=created_at_str,
                meta=source_meta
            )
            
            # Extract rank if fact_key has rank pattern (e.g., "user.favorites.crypto.1")
            rank = None
            import re
            rank_match = re.search(r'\.(\d+)$', fact_key)
            if rank_match:
                rank = int(rank_match.group(1))
            
            # Create DiscoveryHit
            hit = DiscoveryHit(
                id=hit_id,
                domain="facts",
                type="fact",
                title=title,
                text=value_text,
                score=fact.get("confidence", 1.0),  # Use confidence as score
                rank=rank,
                sources=[source],
                meta={
                    "fact_id": fact_id,
                    "fact_key": fact_key,
                    "value_type": fact.get("value_type", "string"),
                    "project_id": query.project_id
                }
            )
            hits.append(hit)
        
        elapsed_ms = (time.time() - start_time) * 1000
        meta["count"] = len(hits)
        meta["timing_ms"] = elapsed_ms
        
        logger.info(
            f"[DISCOVERY-FACTS] Found {len(hits)} facts for query '{query.query}' "
            f"in {elapsed_ms:.1f}ms"
        )
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        meta["timing_ms"] = elapsed_ms
        meta["degraded"] = f"error: {str(e)}"
        logger.error(f"[DISCOVERY-FACTS] Error searching facts: {e}", exc_info=True)
    
    return hits, meta

