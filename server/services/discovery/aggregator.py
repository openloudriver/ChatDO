"""
Discovery Aggregator - Orchestrates parallel search across Facts, Index, and Files.

Runs adapters in parallel with timeouts, merges results, and returns unified DiscoveryResponse.
"""
import logging
import asyncio
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from server.contracts.discovery import DiscoveryQuery, DiscoveryResponse, DiscoveryHit

logger = logging.getLogger(__name__)

# Timeout limits per domain (in seconds)
FACTS_TIMEOUT = 0.5  # 500ms - DB-backed, should be fast
FILES_TIMEOUT = 0.5  # 500ms - Metadata search, should be fast
INDEX_TIMEOUT = 2.0  # 2s - Vector search, can be slower


def _run_adapter_sync(adapter_func, query: DiscoveryQuery, timeout: float) -> tuple:
    """
    Run adapter function synchronously with timeout.
    
    Returns:
        Tuple of (hits: List[DiscoveryHit], meta: Dict)
    """
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(adapter_func, query)
            hits, meta = future.result(timeout=timeout)
            return hits, meta
    except FutureTimeoutError:
        logger.warning(f"[DISCOVERY-AGG] Adapter timed out after {timeout}s")
        return [], {"degraded": "timeout", "timing_ms": timeout * 1000}
    except Exception as e:
        logger.error(f"[DISCOVERY-AGG] Adapter error: {e}", exc_info=True)
        return [], {"degraded": f"error:{str(e)}", "timing_ms": 0.0}


async def search_all(query: DiscoveryQuery) -> DiscoveryResponse:
    """
    Search all domains in parallel and return unified DiscoveryResponse.
    
    Args:
        query: DiscoveryQuery with search parameters
        
    Returns:
        DiscoveryResponse with merged hits, counts, timings, and degraded status
    """
    from server.services.discovery.adapters import facts_adapter, index_adapter, files_adapter
    
    # Run adapters in parallel based on scope
    # Use asyncio.get_event_loop().run_in_executor for compatibility
    loop = asyncio.get_event_loop()
    tasks = []
    adapter_order = []
    
    if "facts" in query.scope:
        tasks.append(
            loop.run_in_executor(
                None,
                _run_adapter_sync,
                facts_adapter.search,
                query,
                FACTS_TIMEOUT
            )
        )
        adapter_order.append("facts")
    
    if "index" in query.scope:
        tasks.append(
            loop.run_in_executor(
                None,
                _run_adapter_sync,
                index_adapter.search,
                query,
                INDEX_TIMEOUT
            )
        )
        adapter_order.append("index")
    
    if "files" in query.scope:
        tasks.append(
            loop.run_in_executor(
                None,
                _run_adapter_sync,
                files_adapter.search,
                query,
                FILES_TIMEOUT
            )
        )
        adapter_order.append("files")
    
    # Wait for all adapters to complete (or timeout)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect hits and metadata
    all_hits: List[DiscoveryHit] = []
    counts: Dict[str, int] = {}
    timings_ms: Dict[str, float] = {}
    degraded: Dict[str, str] = {}
    
    # Map results to domains based on adapter_order
    for idx, domain in enumerate(adapter_order):
        result = results[idx]
        
        if isinstance(result, Exception):
            logger.error(f"[DISCOVERY-AGG] {domain} adapter raised exception: {result}")
            degraded[domain] = f"exception:{str(result)}"
            counts[domain] = 0
            timings_ms[domain] = 0.0
            continue
        
        hits, meta = result
        
        all_hits.extend(hits)
        counts[domain] = meta.get("count", len(hits))
        timings_ms[domain] = meta.get("timing_ms", 0.0)
        
        if meta.get("degraded"):
            degraded[domain] = meta["degraded"]
    
    # Merge and normalize ranking
    # For now, keep per-domain scores and sort by domain priority + score
    # Priority: Facts > Index > Files (for fact-like queries)
    domain_priority = {"facts": 3, "index": 2, "files": 1}
    
    # Sort hits: first by domain priority, then by score (descending)
    all_hits.sort(
        key=lambda h: (
            domain_priority.get(h.domain, 0),
            h.score if h.score is not None else 0.0
        ),
        reverse=True
    )
    
    # Apply limit and offset
    total_hits = len(all_hits)
    paginated_hits = all_hits[query.offset:query.offset + query.limit * len(query.scope)]
    
    logger.info(
        f"[DISCOVERY-AGG] Query '{query.query}': {total_hits} total hits, "
        f"returning {len(paginated_hits)} (offset={query.offset}, limit={query.limit * len(query.scope)}), "
        f"degraded={degraded}"
    )
    
    return DiscoveryResponse(
        query=query.query,
        hits=paginated_hits,
        counts=counts,
        timings_ms=timings_ms,
        degraded=degraded
    )

