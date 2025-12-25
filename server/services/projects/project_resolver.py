"""
Project UUID resolver module.

Enforces canonical project UUID usage across all Facts write/read/update paths.
All Facts operations must use project UUID, never project name/slug.
"""
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# UUID pattern: 8-4-4-4-12 hex digits
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def is_uuid_like(value: str) -> bool:
    """Check if a string looks like a UUID."""
    if not value or not isinstance(value, str):
        return False
    return bool(UUID_PATTERN.match(value.strip()))


def resolve_project_uuid(project: Optional[Dict], project_id: Optional[str] = None) -> str:
    """
    Resolve project UUID from project dict or project_id string.
    
    This function ensures all Facts operations use canonical project UUID,
    never project name/slug. It enforces the Facts DB contract:
    project_facts.project_id must always be the project UUID string.
    
    Args:
        project: Optional project dict with 'id' and/or 'name' fields
        project_id: Optional project_id string (can be UUID or name)
        
    Returns:
        Project UUID string (canonical format)
        
    Raises:
        ValueError: If project UUID cannot be resolved or is invalid
    """
    # First, try to get UUID from project dict
    if project:
        project_uuid = project.get("id")
        if project_uuid and is_uuid_like(project_uuid):
            logger.debug(f"[PROJECT-RESOLVE] Resolved UUID from project dict: {project_uuid}")
            return project_uuid
    
    # Second, try project_id parameter (if it's UUID-like)
    if project_id:
        if is_uuid_like(project_id):
            logger.debug(f"[PROJECT-RESOLVE] Resolved UUID from project_id param: {project_id}")
            return project_id
        else:
            # project_id is not UUID-like, might be a name - need to look it up
            logger.debug(f"[PROJECT-RESOLVE] project_id '{project_id}' is not UUID-like, looking up by name")
            return _lookup_project_uuid_by_name(project_id)
    
    # Third, try project name from dict
    if project:
        project_name = project.get("name")
        if project_name:
            return _lookup_project_uuid_by_name(project_name)
    
    # Cannot resolve
    raise ValueError(
        f"Cannot resolve project UUID: project={project}, project_id={project_id}. "
        "Project must have 'id' (UUID) or 'name' field, or project_id must be UUID-like."
    )


def _lookup_project_uuid_by_name(project_name: str) -> str:
    """
    Look up project UUID by project name.
    
    Args:
        project_name: Project name/slug (e.g., "v14", "ChatDO")
        
    Returns:
        Project UUID string
        
    Raises:
        ValueError: If project not found
    """
    try:
        from server.main import load_projects
        
        projects = load_projects()
        for project in projects:
            if project.get("name") == project_name:
                project_uuid = project.get("id")
                if project_uuid and is_uuid_like(project_uuid):
                    logger.debug(f"[PROJECT-RESOLVE] Found project '{project_name}' -> UUID: {project_uuid}")
                    return project_uuid
                else:
                    raise ValueError(
                        f"Project '{project_name}' found but has invalid UUID: {project_uuid}"
                    )
        
        raise ValueError(f"Project not found by name: '{project_name}'")
        
    except Exception as e:
        logger.error(f"[PROJECT-RESOLVE] Failed to lookup project by name '{project_name}': {e}", exc_info=True)
        raise ValueError(f"Cannot resolve project UUID for name '{project_name}': {e}") from e


def validate_project_uuid(project_uuid: str) -> None:
    """
    Validate that project_uuid is UUID-like.
    
    Raises:
        ValueError: If project_uuid is not UUID-like
    """
    if not is_uuid_like(project_uuid):
        raise ValueError(
            f"Invalid project UUID format: '{project_uuid}'. "
            "Project UUID must be in format: 8-4-4-4-12 hex digits (e.g., '3414664d-8bb3-4c4c-973b-6f27490e0ec6'). "
            "Facts DB contract requires UUID-only project_id."
        )

