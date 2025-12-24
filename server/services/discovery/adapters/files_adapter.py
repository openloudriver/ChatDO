"""
Files Adapter - Converts Files metadata and content search to DiscoveryHit format.

Supports two modes:
1. Metadata search (path/name) - DB-backed, fast
2. Content search (via Index) - Uses existing vector search

For discovery, we primarily use metadata search for fast, deterministic results.
Content search is handled by the Index adapter with file filters.
"""
import logging
from typing import List, Dict, Tuple
from server.contracts.discovery import DiscoveryQuery, DiscoveryHit, DiscoverySource

logger = logging.getLogger(__name__)


def search(query: DiscoveryQuery) -> Tuple[List[DiscoveryHit], Dict[str, any]]:
    """
    Search files (metadata) and return DiscoveryHit instances.
    
    For content search, use Index adapter with file filters.
    This adapter focuses on metadata search (path/name matching).
    
    Args:
        query: DiscoveryQuery with project_id, query string, limit, etc.
        
    Returns:
        Tuple of (hits: List[DiscoveryHit], meta: Dict)
        - hits: List of DiscoveryHit instances from Files domain
        - meta: Metadata dict with timing, counts, degraded status, etc.
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
        logger.warning("[DISCOVERY-FILES] project_id required for files search")
        return hits, meta
    
    try:
        from server.services.memory_service_client import get_memory_client
        from server.services.memory_service_client import get_memory_sources_for_project
        
        client = get_memory_client()
        
        # Check if Memory Service is available
        if not client.is_available():
            elapsed_ms = (time.time() - start_time) * 1000
            meta["timing_ms"] = elapsed_ms
            meta["degraded"] = "unavailable"
            logger.warning("[DISCOVERY-FILES] Memory Service unavailable, returning empty results")
            return hits, meta
        
        # Get file sources for this project
        source_ids = get_memory_sources_for_project(query.project_id)
        
        if not source_ids:
            elapsed_ms = (time.time() - start_time) * 1000
            meta["timing_ms"] = elapsed_ms
            logger.debug(f"[DISCOVERY-FILES] No file sources found for project {query.project_id}")
            return hits, meta
        
        # Search each source's filetree for matching files
        # This is metadata search (path/name matching), not content search
        query_lower = query.query.lower()
        query_terms = query_lower.split()
        
        for source_id in source_ids[:5]:  # Limit to first 5 sources for performance
            try:
                # List filetree (metadata only, fast)
                response = client.filetree_list(
                    source_id=source_id,
                    max_depth=3,  # Reasonable depth for search
                    max_entries=100  # Limit entries per source
                )
                
                if response.get("error"):
                    continue
                
                # Recursively search filetree nodes for matches
                root = response.get("root", {})
                matching_nodes = _search_filetree_nodes(root, query_terms, source_id)
                
                # Convert matching nodes to DiscoveryHit
                for node in matching_nodes[:query.limit]:  # Limit per source
                    node_path = node.get("path", "")
                    node_name = node.get("name", "")
                    node_type = node.get("type", "file")
                    
                    # Skip directories for now (can add later if needed)
                    if node_type == "directory":
                        continue
                    
                    # Generate stable hit ID
                    hit_id = f"files:{source_id}:{node_path}"
                    
                    # Create source for deep linking
                    source = DiscoverySource(
                        kind="file",
                        source_file_path=node_path,
                        snippet=f"File: {node_name}",
                        meta={
                            "source_id": source_id,
                            "file_name": node_name,
                            "file_type": node_type,
                            "size_bytes": node.get("size"),
                            "modified_at": node.get("modified_at")
                        }
                    )
                    
                    # Create DiscoveryHit
                    hit = DiscoveryHit(
                        id=hit_id,
                        domain="files",
                        type="file_metadata",
                        title=node_name,
                        text=f"Path: {node_path}",
                        score=0.8,  # Metadata matches get decent score
                        rank=None,
                        sources=[source],
                        meta={
                            "source_id": source_id,
                            "path": node_path,
                            "name": node_name,
                            "type": node_type,
                            "project_id": query.project_id
                        }
                    )
                    hits.append(hit)
                    
            except Exception as e:
                logger.warning(f"[DISCOVERY-FILES] Error searching source {source_id}: {e}")
                continue
        
        elapsed_ms = (time.time() - start_time) * 1000
        meta["count"] = len(hits)
        meta["timing_ms"] = elapsed_ms
        
        logger.info(
            f"[DISCOVERY-FILES] Found {len(hits)} file metadata matches for query '{query.query}' "
            f"in {elapsed_ms:.1f}ms"
        )
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        meta["timing_ms"] = elapsed_ms
        meta["degraded"] = f"error:{str(e)}"
        logger.error(f"[DISCOVERY-FILES] Error searching files: {e}", exc_info=True)
    
    return hits, meta


def _search_filetree_nodes(node: Dict, query_terms: List[str], source_id: str) -> List[Dict]:
    """
    Recursively search filetree nodes for matches.
    
    Matches if any query term appears in the file name or path.
    """
    matches = []
    
    node_name = node.get("name", "").lower()
    node_path = node.get("path", "").lower()
    
    # Check if any query term matches
    for term in query_terms:
        if term in node_name or term in node_path:
            matches.append(node)
            break
    
    # Recursively search children
    children = node.get("children", [])
    if children:
        for child in children:
            matches.extend(_search_filetree_nodes(child, query_terms, source_id))
    
    return matches

