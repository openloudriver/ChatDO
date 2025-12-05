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
    
    def search(self, project_id: str, query: str, limit: int = 8, source_ids: Optional[List[str]] = None, chat_id: Optional[str] = None) -> List[Dict]:
        """
        Search for relevant chunks in a project's indexed files and chat messages.
        
        Args:
            project_id: The project ID (e.g., "drr", "privacypay")
            query: Search query string
            limit: Maximum number of results to return
            source_ids: Optional list of source IDs to search. If None, uses [project_id] as fallback.
            chat_id: DEPRECATED - kept for backward compatibility but no longer excludes chats.
                     All chats in the project are now included in search results.
            
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
                    "source_ids": source_ids,
                    "chat_id": chat_id
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
            results: List of search result dictionaries (can include both files and chat messages)
            
        Returns:
            Formatted context string
        """
        if not results:
            return ""
        
        context_parts = ["[PROJECT MEMORY]"]
        
        for i, result in enumerate(results, 1):
            source_type = result.get("source_type", "file")
            
            if source_type == "chat":
                # Format chat message source
                chat_id = result.get("chat_id", "unknown")
                message_id = result.get("message_id", "unknown")
                context_parts.append(f"\n{i}) Source: Chat message (chat_id: {chat_id[:8]}...)")
            else:
                # Format file source
                file_path = result.get("file_path", "unknown")
                # Make path relative if it's an absolute path
                if file_path and "/" in file_path:
                    # Try to extract just the filename or a relative portion
                    parts = file_path.split("/")
                    if len(parts) > 2:
                        # Show last 2 parts
                        file_path = "/".join(parts[-2:])
                context_parts.append(f"\n{i}) Source: {file_path}")
            
            chunk_text = result.get("text", "")
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
    
    def index_chat_message(
        self,
        project_id: str,
        chat_id: str,
        message_id: str,
        role: str,
        content: str,
        timestamp: str,
        message_index: int
    ) -> bool:
        """
        Index a chat message into the Memory Service.
        
        Args:
            project_id: The project ID
            chat_id: The chat/conversation ID
            message_id: Unique message ID
            role: "user" or "assistant"
            content: Message content
            timestamp: ISO format datetime string
            message_index: Index of message in the conversation
            
        Returns:
            True if indexed successfully, False otherwise
        """
        if not self.is_available():
            logger.warning("[MEMORY] Memory Service is not available, skipping chat message indexing")
            return False
        
        try:
            response = requests.post(
                f"{self.base_url}/index-chat-message",
                json={
                    "project_id": project_id,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                    "message_index": message_index
                },
                timeout=10
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Memory Service index_chat_message failed: {e}")
            return False
    
    def add_memory_source(self, root_path: str, display_name: Optional[str] = None,
                          project_id: Optional[str] = "scratch") -> Dict:
        """
        Call the memory service to create a new memory source and start indexing it.
        """
        if not self.is_available():
            raise requests.RequestException("Memory Service is not available")
        
        payload = {
            "root_path": root_path,
            "display_name": display_name,
            "project_id": project_id or "scratch",
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/sources",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # Extract error detail from response if available
            try:
                detail = e.response.json().get("detail", str(e))
            except:
                detail = str(e)
            raise requests.RequestException(f"Failed to add memory source: {detail}")

    def delete_memory_source(self, source_id: str) -> dict:
        """
        Call the memory service to delete a memory source.
        """
        try:
            response = requests.delete(
                f"{self.base_url}/sources/{source_id}",
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # Extract error detail from response if available
            try:
                detail = e.response.json().get("detail", str(e))
            except:
                detail = str(e)
            raise requests.RequestException(f"Failed to delete memory source: {detail}")


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


def get_project_memory_context(project_id: str | None, query: str, limit: int = 8, chat_id: Optional[str] = None) -> Optional[tuple[str, bool]]:
    """
    Get memory context for a project and format it for injection into prompts.
    Includes both file-based sources and cross-chat memory from ALL chats in the project.
    
    Args:
        project_id: The project ID (can be None)
        query: Search query (typically the user's message)
        limit: Maximum number of results
        chat_id: DEPRECATED - kept for backward compatibility but no longer excludes chats
        
    Returns:
        Tuple of (formatted context string, has_results: bool) or None if no project_id or no sources
        Returns ("", False) if no results or service unavailable
    """
    if not project_id:
        return None
    
    source_ids = get_memory_sources_for_project(project_id)
    # Even if no file sources, we still want to search chat messages
    # So we don't return None here - we'll search chats regardless
    
    client = get_memory_client()
    # Pass None for chat_id to include ALL chats (including current chat)
    results = client.search(project_id, query, limit, source_ids, chat_id=None)
    if results:
        return client.format_context(results), True
    return "", False

