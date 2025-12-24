"""
Discovery Routes - Unified search endpoint for Facts, Index, and Files.
"""
import logging
from fastapi import APIRouter, HTTPException
from server.contracts.discovery import DiscoveryQuery, DiscoveryResponse
from server.services.discovery.aggregator import search_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/search", response_model=DiscoveryResponse)
async def search(query: DiscoveryQuery) -> DiscoveryResponse:
    """
    Unified discovery search across Facts, Index, and Files.
    
    Returns a unified result set with hits from all requested domains,
    along with counts, timings, and degraded status for observability.
    
    Args:
        query: DiscoveryQuery with search parameters
        
    Returns:
        DiscoveryResponse with merged hits from all domains
    """
    try:
        # Validate project_id for Facts/Index domains
        if not query.project_id and ("facts" in query.scope or "index" in query.scope):
            raise HTTPException(
                status_code=400,
                detail="project_id is required for facts and index search"
            )
        
        # Run aggregator
        response = await search_all(query)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DISCOVERY-API] Error in search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

