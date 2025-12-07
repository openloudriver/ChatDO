"""
Orchestrator v0 - Central chat brain for ChatDO.

Routes chat requests between frontend and backends (OpenAI + Memory Service).
Handles model selection, memory integration, and message routing.
"""
import logging
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import requests
import time

from server.services.memory_service_client import get_memory_client, get_memory_sources_for_project
from chatdo.agents.main_agent import call_ai_router
from chatdo.memory.store import load_thread_history
from chatdo.config import load_target

logger = logging.getLogger(__name__)

# AI Router URL
AI_ROUTER_URL = "http://localhost:8081/v1/ai/run"


def model_wants_web(model_id: str) -> bool:
    """
    Determine if a model_id indicates web search should be used.
    
    For Phase 1: if model_id includes "web", treat it as web-capable.
    Later: UI model selection will drive this explicitly.
    
    Args:
        model_id: Model identifier (e.g., "gpt-5", "web-memory-gpt-5")
        
    Returns:
        True if web search should be considered
    """
    return "web" in model_id.lower()


class OrchestratorChatRequest(BaseModel):
    """Request model for Orchestrator chat."""
    project_id: Optional[str] = None
    model_id: str  # "gpt-5" or "web-memory-gpt-5"
    messages: List[Dict[str, Any]]  # Full conversation history
    use_memory: Optional[bool] = None  # Override for memory usage
    use_web_search: Optional[bool] = None  # Reserved for future use
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class MemorySearchResult(BaseModel):
    """Simplified memory search result."""
    source_id: str
    file_path: Optional[str] = None
    chunk: str
    score: float


class OrchestratorChatResponse(BaseModel):
    """Response model for Orchestrator chat."""
    message: Dict[str, str]  # { role: "assistant", content: "..." }
    usage: Optional[Dict[str, int]] = None  # { promptTokens, completionTokens, totalTokens }
    metadata: Optional[Dict[str, Any]] = None  # { memoryUsed, memoryHitCount, etc. }


def format_memory_context(results: List[Dict]) -> str:
    """
    Format memory search results into a context string for GPT-5.
    
    Args:
        results: List of memory search result dictionaries
        
    Returns:
        Formatted context string
    """
    if not results:
        return ""
    
    context_parts = ["Relevant context from your indexed sources:\n"]
    
    for i, result in enumerate(results, 1):
        source_id = result.get("source_id", "unknown")
        file_path = result.get("file_path", "")
        chunk_text = result.get("text", "")
        
        # Format source identifier
        if file_path:
            # Make path relative if it's an absolute path
            if "/" in file_path:
                parts = file_path.split("/")
                if len(parts) > 2:
                    file_path = "/".join(parts[-2:])
            source_label = f"source: {source_id}, path: {file_path}"
        else:
            source_label = f"source: {source_id}"
        
        context_parts.append(f"\n[Memory {i} – {source_label}]")
        context_parts.append(chunk_text)
    
    return "\n".join(context_parts)


async def memory_search(
    query: str,
    project_id: Optional[str] = None,
    top_k: int = 8
) -> List[MemorySearchResult]:
    """
    Search Memory Service for relevant context.
    
    Args:
        query: Search query (typically the latest user message)
        project_id: Project ID to search within
        top_k: Maximum number of results
        
    Returns:
        List of MemorySearchResult objects
    """
    if not project_id:
        logger.debug("[ORCH] No project_id provided, skipping memory search")
        return []
    
    client = get_memory_client()
    if not client.is_available():
        logger.warning("[ORCH] Memory Service unavailable, skipping memory search")
        return []
    
    # Get source IDs for the project
    source_ids = get_memory_sources_for_project(project_id)
    
    try:
        start_time = time.time()
        results = client.search(
            project_id=project_id,
            query=query,
            limit=top_k,
            source_ids=source_ids if source_ids else None,
            chat_id=None  # Include all chats in the project
        )
        elapsed = time.time() - start_time
        
        # Convert to MemorySearchResult format
        memory_results = []
        for result in results:
            memory_results.append(MemorySearchResult(
                source_id=result.get("source_id", "unknown"),
                file_path=result.get("file_path"),
                chunk=result.get("text", ""),
                score=result.get("score", 0.0)
            ))
        
        logger.info(f"[ORCH] Memory search completed: {len(memory_results)} results in {elapsed:.2f}s")
        return memory_results
        
    except Exception as e:
        logger.warning(f"[ORCH] Memory search failed: {e}", exc_info=True)
        return []


async def run_orchestrator(req: OrchestratorChatRequest) -> OrchestratorChatResponse:
    """
    Main orchestrator function that routes chat requests.
    
    Responsibilities:
    1. Parse and validate request
    2. Decide mode based on modelId and flags
    3. Call Memory Service if needed
    4. Call GPT-5 via AI Router
    5. Return formatted response
    
    Args:
        req: OrchestratorChatRequest with model_id, messages, etc.
        
    Returns:
        OrchestratorChatResponse with assistant message and metadata
    """
    logger.info(f"[ORCH] Starting orchestrator: model_id={req.model_id}, project_id={req.project_id}")
    
    # 1. Parse and validate request
    if not req.messages or len(req.messages) == 0:
        raise ValueError("Messages list cannot be empty")
    
    # Extract latest user message
    last_user_message = None
    for msg in reversed(req.messages):
        if msg.get("role") == "user":
            last_user_message = msg.get("content", "")
            break
    
    if not last_user_message:
        raise ValueError("No user message found in messages list")
    
    logger.debug(f"[ORCH] Latest user message: {last_user_message[:100]}...")
    
    # 2. Decide mode based on modelId and flags
    use_memory = req.use_memory
    if use_memory is None:
        # Auto-detect from model_id
        use_memory = req.model_id in ["web-memory-gpt-5", "memory-gpt-5"]
    
    logger.info(f"[ORCH] Mode: use_memory={use_memory}, model_id={req.model_id}")
    
    # 3. Build web context if model wants web
    from server.services.orchestrator_web import build_web_context, format_web_block
    
    web_ctx = None
    if model_wants_web(req.model_id):
        web_ctx = await build_web_context(last_user_message)
        logger.info(f"[ORCH] Web context: used_web={web_ctx.used_web if web_ctx else False}")
    else:
        logger.debug(f"[ORCH] Model {req.model_id} does not want web search")
    
    # 4. Call Memory Service if needed
    memory_results = []
    memory_used = False
    memory_hit_count = 0
    
    if use_memory and req.project_id:
        try:
            memory_results = await memory_search(
                query=last_user_message,
                project_id=req.project_id,
                top_k=8
            )
            memory_used = len(memory_results) > 0
            memory_hit_count = len(memory_results)
            logger.info(f"[ORCH] Memory search: {memory_hit_count} results found")
        except Exception as e:
            logger.warning(f"[ORCH] Memory search failed, falling back to GPT-only: {e}")
            memory_results = []
            memory_used = False
    
    # 5. Build message list for GPT-5
    # Always keep original messages intact - do not modify or truncate user messages
    messages = []
    
    # Add existing system messages first (if any)
    for msg in req.messages:
        if msg.get("role") == "system":
            messages.append(msg)
    
    # Add web context as system message if available (before memory and user messages)
    if web_ctx and web_ctx.used_web and web_ctx.results:
        web_context_str = format_web_block(web_ctx.results)
        if web_context_str:
            web_system_msg = {
                "role": "system",
                "content": web_context_str
            }
            messages.append(web_system_msg)
            logger.debug(f"[ORCH] Added web context system message with {len(web_ctx.results)} results")
    
    # Add memory context as system message if available (after web, before user messages)
    if memory_results:
        memory_context = format_memory_context(memory_results)
        memory_system_msg = {
            "role": "system",
            "content": memory_context
        }
        messages.append(memory_system_msg)
        logger.debug(f"[ORCH] Added memory context system message with {len(memory_results)} snippets")
    
    # Add all non-system messages (user and assistant) - keep them exactly as provided
    for msg in req.messages:
        if msg.get("role") != "system":
            messages.append(msg)
    
    logger.debug(f"[ORCH] Built message list: {len(messages)} messages (original: {len(req.messages)})")
    
    # 5. Call GPT-5 via AI Router
    try:
        logger.info(f"[ORCH] Calling AI Router with {len(messages)} messages")
        
        # Build AI Router payload
        payload = {
            "role": "chatdo",
            "intent": "general_chat",
            "priority": "high",
            "privacyLevel": "normal",
            "costTier": "standard",
            "input": {
                "messages": messages
            }
        }
        
        # Add optional parameters if provided
        if req.temperature is not None:
            payload["input"]["temperature"] = req.temperature
        if req.max_tokens is not None:
            payload["input"]["max_tokens"] = req.max_tokens
        
        # Call AI Router
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("ok"):
            error_msg = data.get("error", "Unknown AI Router error")
            logger.error(f"[ORCH] AI Router error: {error_msg}")
            raise Exception(f"AI Router error: {error_msg}")
        
        # Extract response
        assistant_messages = data.get("output", {}).get("messages", [])
        if not assistant_messages:
            raise Exception("No messages in AI Router response")
        
        assistant_content = assistant_messages[0].get("content", "")
        provider = data.get("provider", "openai-gpt5")
        model_id = data.get("modelId", "gpt-5")
        
        # Extract usage if available
        usage = None
        if "usage" in data.get("output", {}):
            usage = data["output"]["usage"]
        
        logger.info(f"[ORCH] AI Router response: provider={provider}, model={model_id}, content_length={len(assistant_content)}")
        
        # 6. Build response
        web_used = web_ctx.used_web if web_ctx else False
        web_results = web_ctx.results if web_ctx and web_ctx.used_web else None
        
        response = OrchestratorChatResponse(
            message={
                "role": "assistant",
                "content": assistant_content
            },
            usage=usage,
            metadata={
                "memoryUsed": memory_used,
                "memoryHitCount": memory_hit_count,
                "webUsed": web_used,
                "webResults": web_results,
                "provider": provider,
                "modelId": model_id
            }
        )
        
        logger.info(f"[ORCH] Orchestrator completed: memory_used={memory_used}, memory_hits={memory_hit_count}, web_used={web_used}")
        return response
        
    except requests.exceptions.RequestException as e:
        logger.error(f"[ORCH] AI Router request failed: {e}", exc_info=True)
        raise Exception(f"Failed to communicate with AI Router: {e}")
    except Exception as e:
        logger.error(f"[ORCH] Orchestrator error: {e}", exc_info=True)
        raise

