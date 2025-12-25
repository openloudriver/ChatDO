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
    
    Facts DB contract: project_id must be UUID, never project name/slug.
    If project_id is provided, it will be resolved to UUID.
    
    Args:
        query: DiscoveryQuery with search parameters
        
    Returns:
        DiscoveryResponse with merged hits from all domains
    """
    # Resolve project_id to UUID if provided (Facts DB contract)
    if query.project_id:
        try:
            from server.services.projects.project_resolver import resolve_project_uuid
            from server.main import load_projects
            
            projects = load_projects()
            project = next((p for p in projects if p.get("id") == query.project_id or p.get("name") == query.project_id), None)
            if project:
                project_uuid = resolve_project_uuid(project, project_id=query.project_id)
                logger.info(f"[PROJECT] Using project_uuid={project_uuid} project_name={project.get('name', 'unknown')}")
                # Update query with resolved UUID
                query.project_id = project_uuid
            else:
                # Try to resolve by project_id directly (might be UUID already)
                try:
                    project_uuid = resolve_project_uuid(None, project_id=query.project_id)
                    query.project_id = project_uuid
                except ValueError:
                    logger.warning(f"[DISCOVERY] Cannot resolve project_id: {query.project_id}")
        except Exception as e:
            logger.error(f"[DISCOVERY] Failed to resolve project UUID: {e}", exc_info=True)
            # Continue with original project_id - validation will catch if invalid
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

