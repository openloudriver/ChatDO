"""
Index Adapter - Converts Index search results to DiscoveryHit format.

Calls existing index search (hybrid/vector) and wraps each chunk as DiscoveryHit.
Supports graceful degradation if index service is unavailable.
"""
import logging
from typing import List, Dict, Tuple
from server.contracts.discovery import DiscoveryQuery, DiscoveryHit, DiscoverySource

logger = logging.getLogger(__name__)


def search(query: DiscoveryQuery) -> Tuple[List[DiscoveryHit], Dict[str, any]]:
    """
    Search index (vector/semantic search) and return DiscoveryHit instances.
    
    Args:
        query: DiscoveryQuery with project_id, query string, limit, etc.
        
    Returns:
        Tuple of (hits: List[DiscoveryHit], meta: Dict)
        - hits: List of DiscoveryHit instances from Index domain
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
        logger.warning("[DISCOVERY-INDEX] project_id required for index search")
        return hits, meta
    
    try:
        from server.services.memory_service_client import get_memory_client
        
        client = get_memory_client()
        
        # Check if Memory Service is available
        if not client.is_available():
            elapsed_ms = (time.time() - start_time) * 1000
            meta["timing_ms"] = elapsed_ms
            meta["degraded"] = "unavailable"
            logger.warning("[DISCOVERY-INDEX] Memory Service unavailable, returning empty results")
            return hits, meta
        
        # Call existing search endpoint
        # Use timeout to prevent hanging
        import requests
        try:
            response = requests.post(
                f"{client.base_url}/search",
                json={
                    "project_id": query.project_id,
                    "query": query.query,
                    "limit": query.limit,
                    "source_ids": None,  # Search all sources for this project
                    "exclude_chat_ids": []  # Discovery search doesn't exclude chats
                },
                timeout=2.0  # 2 second timeout for graceful degradation
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                # Convert SearchResult to DiscoveryHit
                for idx, result in enumerate(results):
                    message_uuid = result.get("message_uuid") or result.get("metadata", {}).get("message_uuid")
                    message_id = result.get("message_id", "")
                    chat_id = result.get("chat_id")
                    file_path = result.get("file_path")
                    chunk_index = result.get("chunk_index", 0)
                    text = result.get("text", "")
                    score = result.get("score", 0.0)
                    
                    # Generate stable hit ID
                    if message_uuid:
                        hit_id = f"index:{message_uuid}:{chunk_index}"
                    elif file_path:
                        hit_id = f"index:file:{file_path}:{chunk_index}"
                    else:
                        hit_id = f"index:{message_id}:{chunk_index}"
                    
                    # Determine hit type
                    if result.get("source_type") == "file":
                        hit_type = "file_chunk"
                        title = file_path.split("/")[-1] if file_path else "File"
                    else:
                        hit_type = "chat_chunk"
                        # Generate title from message preview
                        title = text[:60] + "..." if len(text) > 60 else text
                    
                    # Create source for deep linking
                    if result.get("source_type") == "file":
                        # File chunk source
                        source = DiscoverySource(
                            kind="file",
                            source_file_id=result.get("metadata", {}).get("file_id"),
                            source_file_path=file_path,
                            snippet=text[:100] if len(text) > 100 else text,
                            meta={
                                "chunk_index": chunk_index,
                                "filetype": result.get("filetype"),
                                "start_char": result.get("start_char", 0),
                                "end_char": result.get("end_char", 0)
                            }
                        )
                    else:
                        # Chat message chunk source
                        source = DiscoverySource(
                            kind="chat_message",
                            source_message_uuid=message_uuid,
                            source_chat_id=chat_id,
                            snippet=text[:100] if len(text) > 100 else text,
                            meta={
                                "message_id": message_id,
                                "role": result.get("metadata", {}).get("role", "assistant"),
                                "chunk_index": chunk_index
                            }
                        )
                    
                    # Create DiscoveryHit
                    hit = DiscoveryHit(
                        id=hit_id,
                        domain="index",
                        type=hit_type,
                        title=title,
                        text=text,
                        score=score,
                        rank=None,  # Index results are scored, not ranked
                        sources=[source],
                        meta={
                            "source_id": result.get("source_id", ""),
                            "source_type": result.get("source_type", "chat"),
                            "project_id": query.project_id,
                            "chunk_index": chunk_index
                        }
                    )
                    hits.append(hit)
                
                elapsed_ms = (time.time() - start_time) * 1000
                meta["count"] = len(hits)
                meta["timing_ms"] = elapsed_ms
                
                logger.info(
                    f"[DISCOVERY-INDEX] Found {len(hits)} index results for query '{query.query}' "
                    f"in {elapsed_ms:.1f}ms"
                )
            else:
                elapsed_ms = (time.time() - start_time) * 1000
                meta["timing_ms"] = elapsed_ms
                meta["degraded"] = f"http_error:{response.status_code}"
                logger.warning(f"[DISCOVERY-INDEX] Search failed with status {response.status_code}")
                
        except requests.exceptions.Timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            meta["timing_ms"] = elapsed_ms
            meta["degraded"] = "timeout"
            logger.warning(f"[DISCOVERY-INDEX] Search timed out after 2s")
            
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.time() - start_time) * 1000
            meta["timing_ms"] = elapsed_ms
            meta["degraded"] = f"request_error:{str(e)}"
            logger.warning(f"[DISCOVERY-INDEX] Search request failed: {e}")
            
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        meta["timing_ms"] = elapsed_ms
        meta["degraded"] = f"error:{str(e)}"
        logger.error(f"[DISCOVERY-INDEX] Error searching index: {e}", exc_info=True)
    
    return hits, meta

