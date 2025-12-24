"""
Composer consumption helper - Get unified discovery context for GPT-5.

This function provides a single entry point for getting discovery context
that can be consumed by GPT-5, ensuring citations map 1:1 with sources.
"""
import logging
from typing import List, Dict, Optional
from server.contracts.discovery import DiscoveryQuery, DiscoveryHit
from server.services.discovery.aggregator import search_all

logger = logging.getLogger(__name__)


async def get_context_for_gpt(
    query: str,
    project_id: str,
    chat_id: Optional[str] = None,
    limit: int = 30,
    scope: Optional[List[str]] = None
) -> Dict[str, any]:
    """
    Get discovery context for GPT-5 from unified search.
    
    This function:
    - Calls /discovery/search internally (or shared aggregator)
    - Selects top K hits and formats them into structured context
    - Ensures citations map 1:1 with sources
    
    Args:
        query: Search query string
        project_id: Project ID
        chat_id: Optional chat ID (for filtering)
        limit: Maximum number of hits to return
        scope: Optional list of domains to search (default: ["facts", "index", "files"])
        
    Returns:
        Dict with:
        - context: str - Formatted context block for GPT-5
        - sources: List[Dict] - Source objects for frontend citations
        - facts_count: int - Number of fact hits
        - index_count: int - Number of index hits
        - files_count: int - Number of file hits
    """
    if scope is None:
        scope = ["facts", "index", "files"]
    
    # Create discovery query
    discovery_query = DiscoveryQuery(
        query=query,
        scope=scope,
        limit=limit,
        offset=0,
        chat_id=chat_id,
        project_id=project_id
    )
    
    # Run discovery search
    response = await search_all(discovery_query)
    
    # Format context for GPT-5
    context_parts = []
    sources = []
    citation_counter = 1
    
    # Group hits by domain for better organization
    facts_hits = [h for h in response.hits if h.domain == "facts"]
    index_hits = [h for h in response.hits if h.domain == "index"]
    files_hits = [h for h in response.hits if h.domain == "files"]
    
    # Format Facts
    if facts_hits:
        context_parts.append("[STORED FACTS]")
        for hit in facts_hits:
            citation = f"[M{citation_counter}]"
            context_parts.append(f"{citation} {hit.text}")
            
            # Add source for citation
            for source in hit.sources:
                sources.append({
                    "id": f"memory-{hit.id}",
                    "title": hit.title or "Stored Fact",
                    "description": hit.text[:150],
                    "sourceType": "memory",
                    "citationPrefix": "M",
                    "rank": citation_counter - 1,
                    "siteName": "Facts",
                    "meta": {
                        "kind": "chat_message",
                        "source_message_uuid": source.source_message_uuid,
                        "fact_id": source.source_fact_id,
                        "domain": "facts"
                    }
                })
            citation_counter += 1
        context_parts.append("")
    
    # Format Index (Chat chunks)
    if index_hits:
        context_parts.append("[RELEVANT CHAT MESSAGES]")
        for hit in index_hits:
            citation = f"[M{citation_counter}]"
            context_parts.append(f"{citation} {hit.text}")
            
            # Add source for citation
            for source in hit.sources:
                sources.append({
                    "id": f"memory-{hit.id}",
                    "title": hit.title or "Chat Message",
                    "description": hit.text[:150],
                    "sourceType": "memory",
                    "citationPrefix": "M",
                    "rank": citation_counter - 1,
                    "siteName": "Memory",
                    "meta": {
                        "kind": source.kind,
                        "message_uuid": source.source_message_uuid,
                        "chat_id": source.source_chat_id,
                        "domain": "index"
                    }
                })
            citation_counter += 1
        context_parts.append("")
    
    # Format Files
    if files_hits:
        context_parts.append("[RELEVANT FILES]")
        for hit in files_hits:
            citation = f"[M{citation_counter}]"
            context_parts.append(f"{citation} {hit.text}")
            
            # Add source for citation
            for source in hit.sources:
                sources.append({
                    "id": f"memory-{hit.id}",
                    "title": hit.title or "File",
                    "description": hit.text[:150],
                    "sourceType": "memory",
                    "citationPrefix": "M",
                    "rank": citation_counter - 1,
                    "siteName": "Files",
                    "meta": {
                        "kind": "file",
                        "file_path": source.source_file_path,
                        "file_id": source.source_file_id,
                        "domain": "files"
                    }
                })
            citation_counter += 1
        context_parts.append("")
    
    context = "\n".join(context_parts)
    
    logger.info(
        f"[DISCOVERY-GPT] Generated context: {len(facts_hits)} facts, "
        f"{len(index_hits)} index, {len(files_hits)} files, "
        f"{len(sources)} sources"
    )
    
    return {
        "context": context,
        "sources": sources,
        "facts_count": len(facts_hits),
        "index_count": len(index_hits),
        "files_count": len(files_hits),
        "degraded": response.degraded,
        "timings_ms": response.timings_ms
    }

