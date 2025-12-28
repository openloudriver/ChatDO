"""
Memory Service client for ChatDO backend.

Calls the Memory Service HTTP API to retrieve project-aware context.
"""
import requests
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MEMORY_SERVICE_URL = "http://127.0.0.1:5858"


class MemoryServiceClient:
    """Client for communicating with the Memory Service."""
    
    def __init__(self, base_url: str = MEMORY_SERVICE_URL):
        self.base_url = base_url
    
    def is_available(self) -> bool:
        """Check if Memory Service is running.
        
        Uses a short timeout for health checks - if it's not responding quickly,
        we consider it unavailable rather than blocking the request.
        """
        import time
        max_retries = 1  # Single attempt with short timeout
        timeout = 1  # 1 second timeout - health check should be instant
        
        for attempt in range(max_retries):
            try:
                response = requests.get(f"{self.base_url}/health", timeout=timeout)
                if response.status_code == 200:
                    return True
            except requests.exceptions.Timeout:
                logger.debug(f"[MEMORY] Health check timeout after {timeout}s - service may be overloaded")
                return False  # Don't retry - if health check times out, service is likely stuck
            except Exception as e:
                logger.debug(f"[MEMORY] Health check failed: {e}")
                return False  # Don't retry on other errors either
        
        return False
    
    def search(self, project_id: str, query: str, limit: int = 8, source_ids: Optional[List[str]] = None, chat_id: Optional[str] = None, exclude_chat_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Search for relevant chunks in a project's indexed files and chat messages.
        
        Args:
            project_id: The project ID (e.g., "drr", "privacypay") - REQUIRED, cannot be None/empty
            query: Search query string
            limit: Maximum number of results to return
            source_ids: Optional list of source IDs to search. If None, uses [project_id] as fallback.
            chat_id: DEPRECATED - kept for backward compatibility but no longer excludes chats.
                     All chats in the project are now included in search results.
            exclude_chat_ids: Optional list of chat_ids to exclude from search (e.g., trashed chats)
            
        Returns:
            List of search results with score, file_path, text, etc.
            Returns empty list if service is unavailable or error occurs.
            
        Raises:
            ValueError: If project_id is None or empty (project isolation requirement)
        """
        # HARD INVARIANT: project_id is required for project isolation
        if not project_id or project_id.strip() == "":
            logger.error("[ISOLATION] Memory search rejected: project_id is missing or empty")
            raise ValueError("project_id is required and cannot be None or empty for project isolation")
        
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
                    "chat_id": chat_id,
                    "exclude_chat_ids": exclude_chat_ids
                },
                timeout=3  # 3 second timeout for search (vector search can take a moment)
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
        Includes citation instructions for Memory sources using [M1], [M2], etc.
        
        Args:
            results: List of search result dictionaries (can include both files and chat messages)
            
        Returns:
            Formatted context string with citation instructions
        """
        if not results:
            return ""
        
        context_parts = [
            "[PROJECT MEMORY]",
            "",
            "You have access to the following memory sources from this project. Use them when relevant.",
            "",
            "CITATION FORMAT: When you use information from these memory sources, add inline citations like [M1] or [M2] at the end of the relevant sentence.",
            "Use [M1, M2] when referencing multiple memory sources. The sources are numbered below (M1, M2, M3, etc.).",
            "",
        ]
        
        for i, result in enumerate(results, 1):
            source_type = result.get("source_type", "file")
            
            if source_type == "fact":
                # Format fact source - facts are stored preferences/facts
                context_parts.append(f"\n[M{i}] (Stored Fact)")
            elif source_type == "chat":
                # Format chat message source - just include citation marker, no verbose chat_id
                context_parts.append(f"\n[M{i}]")
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
                context_parts.append(f"\n[M{i}] Source: {file_path}")
            
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
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Enqueue a chat message for async indexing.
        
        Args:
            project_id: The project ID
            chat_id: The chat/conversation ID
            message_id: Unique message ID
            role: "user" or "assistant"
            content: Message content
            timestamp: ISO format datetime string
            message_index: Index of message in the conversation
            
        Returns:
            Tuple of (success: bool, job_id: Optional[str], message_uuid: Optional[str])
            - success: True if job was enqueued, False if enqueue failed
            - job_id: Job identifier for status tracking (None if failed)
            - message_uuid: Will be None initially, available after job completes
        """
        if not self.is_available():
            logger.warning("[MEMORY] Memory Service is not available, skipping chat message indexing")
            return False, None, None
        
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
                timeout=2  # 2 second timeout - enqueue should be very fast (just adding to queue)
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")
            job_id = data.get("job_id")
            
            if status == "queued":
                logger.info(f"[MEMORY] Enqueued indexing job {job_id} for message {message_id}")
                return True, job_id, None  # message_uuid will be available after job completes
            else:
                logger.warning(f"[MEMORY] Failed to enqueue indexing job: {data.get('message')}")
                return False, None, None
                
        except requests.exceptions.Timeout:
            logger.warning(f"[MEMORY] Memory Service enqueue timed out after 5s")
            return False, None, None
        except Exception as e:
            logger.warning(f"[MEMORY] Memory Service index_chat_message failed: {e}")
            return False, None, None
    
    def get_index_job_status(self, job_id: str) -> Optional[Dict]:
        """
        Get the status of an indexing job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status dict or None if job not found
        """
        if not self.is_available():
            return None
        
        try:
            response = requests.get(
                f"{self.base_url}/index-job-status/{job_id}",
                timeout=2
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"[MEMORY] Failed to get job status for {job_id}: {e}")
            return None
    
    # REMOVED: NEW facts table system client methods
    # - store_fact() - facts are stored via fact_extractor → store_project_fact
    # - get_facts() - use search_facts() instead
    # - get_fact_by_rank() - use search_facts() and filter by fact_key instead
    # All fact operations now use project_facts table via fact_extractor and /search-facts
    
    def get_single_fact(
        self,
        project_id: str,
        topic_key: str,
        chat_id: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get a single fact (non-ranked) for a topic.
        
        Args:
            project_id: Project ID
            topic_key: Normalized topic key
            chat_id: Optional chat ID filter
            
        Returns:
            Fact dictionary or None if not found
        """
        if not self.is_available():
            return None
        
        try:
            params = {
                "project_id": project_id,
                "topic_key": topic_key
            }
            if chat_id:
                params["chat_id"] = chat_id
            
            # REMOVED: /facts/get-single endpoint - use /search-facts instead
            # This method is no longer used
            return None
        except Exception as e:
            logger.warning(f"Memory Service get_single_fact failed: {e}")
            return None
    
    def add_memory_source(self, root_path: str, display_name: Optional[str] = None,
                          project_id: Optional[str] = "general") -> Dict:
        """
        Call the memory service to create a new memory source and start indexing it.
        """
        if not self.is_available():
            raise requests.RequestException("Memory Service is not available")
        
        payload = {
            "root_path": root_path,
            "display_name": display_name,
            "project_id": project_id or "general",
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
    
    async def filetree_list(self, source_id: str, max_depth: int = 10, max_entries: int = 1000) -> dict:
        """
        List directory tree for a Memory source.
        
        Args:
            source_id: The Memory source ID (e.g., "coin-dir")
            max_depth: Maximum depth to traverse (0-10, clamped to 10)
            max_entries: Maximum entries to return (1-1000, clamped to 1000)
            
        Returns:
            Dict with FileTreeResponse structure or error dict
        """
        # Clamp parameters
        max_depth = max(0, min(10, max_depth))
        max_entries = max(1, min(1000, max_entries))
        
        if not self.is_available():
            logger.warning("[FILETREE-CLIENT] Memory Service is not available")
            return {
                "error": "FileTree list failed",
                "source_id": source_id
            }
        
        try:
            response = requests.get(
                f"{self.base_url}/filetree/{source_id}",
                params={
                    "path": "",  # Always use root path
                    "max_depth": max_depth,
                    "max_entries": max_entries
                },
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"[FILETREE-CLIENT] Listed filetree for source={source_id}")
            return response.json()
        except Exception as e:
            logger.warning(f"[FILETREE-CLIENT] FileTree list failed for source={source_id}: {e}")
            return {
                "error": "FileTree list failed",
                "source_id": source_id
            }
    
    async def filetree_read(self, source_id: str, path: str, max_bytes: int = 512000) -> dict:
        """
        Read a single file from a Memory source.
        
        Args:
            source_id: The Memory source ID (e.g., "coin-dir")
            path: Relative file path from source root (required)
            max_bytes: Maximum bytes to read (clamped to 512000)
            
        Returns:
            Dict with FileReadResponse structure or error dict
        """
        # Clamp max_bytes
        max_bytes = max(1, min(512000, max_bytes))
        
        if not self.is_available():
            logger.warning("[FILETREE-CLIENT] Memory Service is not available")
            return {
                "error": "FileTree read failed",
                "source_id": source_id
            }
        
        try:
            response = requests.get(
                f"{self.base_url}/filetree/{source_id}/file",
                params={
                    "path": path,
                    "max_bytes": max_bytes
                },
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"[FILETREE-CLIENT] Read file from source={source_id} path={path} max_bytes={max_bytes}")
            return response.json()
        except Exception as e:
            logger.warning(f"[FILETREE-CLIENT] FileTree read failed for source={source_id} path={path}: {e}")
            return {
                "error": "FileTree read failed",
                "source_id": source_id
            }


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


def get_project_sources_with_details(project_id: str) -> List[Dict[str, str]]:
    """
    Get memory sources for a project with their details (id, display_name).
    
    Returns:
        List of dicts with 'id' and 'display_name' for each source
    """
    from server.services import projects_config
    
    project = projects_config.get_project(project_id)
    if not project:
        return []
    
    source_ids = project.get("memory_sources") or []
    if not source_ids:
        return []
    
    # Get source details from Memory Service
    client = MemoryServiceClient()
    if not client.is_available():
        # Return just IDs if service unavailable
        return [{"id": sid, "display_name": sid} for sid in source_ids]
    
    try:
        response = requests.get(f"{client.base_url}/sources", timeout=5)
        response.raise_for_status()
        all_sources = response.json().get("sources", [])
        
        # Map source_ids to their details
        source_map = {s.get("id"): s for s in all_sources}
        result = []
        for sid in source_ids:
            source = source_map.get(sid)
            if source:
                result.append({
                    "id": sid,
                    "display_name": source.get("display_name", sid)
                })
            else:
                result.append({
                    "id": sid,
                    "display_name": sid
                })
        return result
    except Exception as e:
        logger.warning(f"Failed to get source details: {e}")
        # Fallback: return just IDs
        return [{"id": sid, "display_name": sid} for sid in source_ids]


def get_trashed_chat_ids_for_project(project_id: str) -> List[str]:
    """
    Get list of trashed chat_ids for a project.
    
    Args:
        project_id: The project ID
        
    Returns:
        List of chat_ids that are trashed for this project
    """
    try:
        from server.main import load_chats, get_trashed_chats
        chats = load_chats()
        trashed_chats = get_trashed_chats(chats)
        # Filter to only chats for this project
        return [c.get("id") for c in trashed_chats if c.get("project_id") == project_id]
    except Exception as e:
        logger.warning(f"Failed to get trashed chat_ids for project {project_id}: {e}")
        return []


def get_archived_chat_ids_for_project(project_id: str) -> List[str]:
    """
    Get list of archived chat_ids for a project.
    
    Args:
        project_id: The project ID
        
    Returns:
        List of chat_ids that are archived (but not trashed) for this project
    """
    try:
        from server.main import load_chats, get_archived_chats
        chats = load_chats()
        archived_chats = get_archived_chats(chats)
        # Filter to only chats for this project
        return [c.get("id") for c in archived_chats if c.get("project_id") == project_id]
    except Exception as e:
        logger.warning(f"Failed to get archived chat_ids for project {project_id}: {e}")
        return []


def get_excluded_chat_ids_for_recall(project_id: str) -> List[str]:
    """
    Get list of chat_ids to exclude from ChatDO recall.
    
    RECALL IS ALWAYS ACTIVE-ONLY:
    - Archived chats are ALWAYS excluded from recall
    - Trashed chats are ALWAYS excluded from recall
    - This is enforced server-side, independent of UI search scope
    
    Args:
        project_id: The project ID
        
    Returns:
        List of chat_ids to exclude from recall (trashed + archived)
    """
    excluded = []
    
    # Always exclude trashed (never recalled)
    excluded.extend(get_trashed_chat_ids_for_project(project_id))
    
    # Always exclude archived (never recalled - must restore to Active to be recalled)
    excluded.extend(get_archived_chat_ids_for_project(project_id))
    
    return excluded


def get_project_memory_context(project_id: str | None, query: str, limit: int = 8, chat_id: Optional[str] = None) -> Optional[tuple[str, bool]]:
    """
    Get memory context for a project and format it for injection into prompts.
    Includes both file-based sources and cross-chat memory from ACTIVE chats only.
    
    RECALL IS ALWAYS ACTIVE-ONLY:
    - Archived chats are NEVER included in recall
    - Trashed chats are NEVER included in recall
    - Archived projects are NEVER used for recall
    - This is enforced server-side, independent of UI search scope
    
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
    
    # Check if project is archived - archived projects are never used for recall
    from server.services import projects_config
    project = projects_config.get_project(project_id)
    if project and (project.get("archived", False) or project.get("trashed", False)):
        logger.debug(f"[RECALL] Project {project_id} is archived or trashed - excluding from recall")
        return "", False
    
    source_ids = get_memory_sources_for_project(project_id)
    # Even if no file sources, we still want to search chat messages
    # So we don't return None here - we'll search chats regardless
    
    # Get chat_ids to exclude from recall (ALWAYS excludes trashed + archived)
    exclude_chat_ids = get_excluded_chat_ids_for_recall(project_id)
    
    client = get_memory_client()
    # Pass None for chat_id to include ALL chats (including current chat), but exclude trashed/archived chats
    results = client.search(project_id, query, limit, source_ids, chat_id=None, exclude_chat_ids=exclude_chat_ids)
    if results:
        return client.format_context(results), True
    return "", False

