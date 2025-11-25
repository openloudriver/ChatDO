"""
Memory Service client for ChatDO backend.

Calls the Memory Service HTTP API to retrieve project-aware context.
"""
import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

MEMORY_SERVICE_URL = "http://127.0.0.1:5858"


class MemoryServiceClient:
    """Client for communicating with the Memory Service."""
    
    def __init__(self, base_url: str = MEMORY_SERVICE_URL):
        self.base_url = base_url
    
    def is_available(self) -> bool:
        """Check if Memory Service is running."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=2)
            return response.status_code == 200
        except Exception:
            return False
    
    def search(self, project_id: str, query: str, limit: int = 8, source_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Search for relevant chunks in a project's indexed files.
        
        Args:
            project_id: The project ID (e.g., "drr", "privacypay")
            query: Search query string
            limit: Maximum number of results to return
            source_ids: Optional list of source IDs to search. If None, uses [project_id] as fallback.
            
        Returns:
            List of search results with score, file_path, text, etc.
            Returns empty list if service is unavailable or error occurs.
        """
        if not self.is_available():
            logger.debug("Memory Service is not available, skipping memory search")
            return []
        
        # For now, if source_ids not provided, use project_id as fallback
        # Later this will be replaced with proper project -> sources mapping
        if source_ids is None:
            source_ids = [project_id]
        
        try:
            response = requests.post(
                f"{self.base_url}/search",
                json={
                    "project_id": project_id,
                    "query": query,
                    "limit": limit,
                    "source_ids": source_ids
                },
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except Exception as e:
            logger.warning(f"Memory Service search failed: {e}")
            return []
    
    def format_context(self, results: List[Dict]) -> str:
        """
        Format search results into a context block for the AI prompt.
        
        Args:
            results: List of search result dictionaries
            
        Returns:
            Formatted context string
        """
        if not results:
            return ""
        
        context_parts = ["[PROJECT MEMORY]"]
        
        for i, result in enumerate(results, 1):
            file_path = result.get("file_path", "unknown")
            # Make path relative if it's an absolute path
            if "/" in file_path:
                # Try to extract just the filename or a relative portion
                parts = file_path.split("/")
                if len(parts) > 2:
                    # Show last 2 parts
                    file_path = "/".join(parts[-2:])
            
            chunk_text = result.get("text", "")
            context_parts.append(f"\n{i}) Source: {file_path}")
            context_parts.append("---")
            context_parts.append(chunk_text)
        
        return "\n".join(context_parts)
    
    def get_sources(self) -> List[Dict]:
        """Get all sources with status."""
        if not self.is_available():
            return []
        
        try:
            response = requests.get(f"{self.base_url}/sources", timeout=5)
            response.raise_for_status()
            data = response.json()
            return data.get("sources", [])
        except Exception as e:
            logger.warning(f"Memory Service get_sources failed: {e}")
            return []
    
    def get_source_status(self, source_id: str) -> Optional[Dict]:
        """Get status for a specific source."""
        if not self.is_available():
            return None
        
        try:
            response = requests.get(f"{self.base_url}/sources/{source_id}/status", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Memory Service get_source_status failed: {e}")
            return None
    
    def get_source_jobs(self, source_id: str, limit: int = 10) -> List[Dict]:
        """Get recent jobs for a source."""
        if not self.is_available():
            return []
        
        try:
            response = requests.get(f"{self.base_url}/sources/{source_id}/jobs?limit={limit}", timeout=5)
            response.raise_for_status()
            data = response.json()
            return data.get("jobs", [])
        except Exception as e:
            logger.warning(f"Memory Service get_source_jobs failed: {e}")
            return []
    
    def trigger_reindex(self, source_id: str) -> Optional[Dict]:
        """Trigger a reindex for a source."""
        if not self.is_available():
            return None
        
        try:
            response = requests.post(
                f"{self.base_url}/reindex",
                json={"source_id": source_id},
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Memory Service trigger_reindex failed: {e}")
            return None


# Global client instance
_memory_client: Optional[MemoryServiceClient] = None


def get_memory_client() -> MemoryServiceClient:
    """Get or create the global Memory Service client."""
    global _memory_client
    if _memory_client is None:
        _memory_client = MemoryServiceClient()
    return _memory_client


def get_memory_sources_for_project(project_id: str) -> List[str]:
    """Get memory sources configured for a project."""
    from server.services import projects_config
    
    project = projects_config.get_project(project_id)
    if not project:
        return []
    
    return project.get("memory_sources") or []


def get_project_memory_context(project_id: str | None, query: str, limit: int = 8) -> Optional[tuple[str, bool]]:
    """
    Get memory context for a project and format it for injection into prompts.
    
    Args:
        project_id: The project ID (can be None)
        query: Search query (typically the user's message)
        limit: Maximum number of results
        
    Returns:
        Tuple of (formatted context string, has_results: bool) or None if no project_id or no sources
        Returns ("", False) if no results or service unavailable
    """
    if not project_id:
        return None
    
    source_ids = get_memory_sources_for_project(project_id)
    if not source_ids:
        # No sources attached -> skip memory search
        return None
    
    client = get_memory_client()
    results = client.search(project_id, query, limit, source_ids)
    if results:
        return client.format_context(results), True
    return "", False

