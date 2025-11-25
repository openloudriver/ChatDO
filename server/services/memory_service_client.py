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
    
    def search(self, project_id: str, query: str, limit: int = 8) -> List[Dict]:
        """
        Search for relevant chunks in a project's indexed files.
        
        Args:
            project_id: The project ID (e.g., "drr", "privacypay")
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            List of search results with score, file_path, text, etc.
            Returns empty list if service is unavailable or error occurs.
        """
        if not self.is_available():
            logger.debug("Memory Service is not available, skipping memory search")
            return []
        
        try:
            response = requests.post(
                f"{self.base_url}/search",
                json={
                    "project_id": project_id,
                    "query": query,
                    "limit": limit
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


# Global client instance
_memory_client: Optional[MemoryServiceClient] = None


def get_memory_client() -> MemoryServiceClient:
    """Get or create the global Memory Service client."""
    global _memory_client
    if _memory_client is None:
        _memory_client = MemoryServiceClient()
    return _memory_client


def get_project_memory_context(project_id: str, query: str, limit: int = 8) -> tuple[str, bool]:
    """
    Get memory context for a project and format it for injection into prompts.
    
    Args:
        project_id: The project ID
        query: Search query (typically the user's message)
        limit: Maximum number of results
        
    Returns:
        Tuple of (formatted context string, has_results: bool)
        Returns ("", False) if no results or service unavailable
    """
    client = get_memory_client()
    results = client.search(project_id, query, limit)
    if results:
        return client.format_context(results), True
    return "", False

