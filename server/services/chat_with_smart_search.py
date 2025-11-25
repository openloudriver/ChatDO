"""
Smart chat orchestrator - handles normal chat with optional background web search.
When web search is needed, it's done in the background and results are fed to GPT-5.
"""
import logging
from typing import Dict, List, Any, Optional
from chatdo.tools import web_search
from chatdo.agents.main_agent import call_ai_router, CHATDO_SYSTEM_PROMPT
from chatdo.memory import store as memory_store
from .smart_search_classifier import decide_web_search
from .memory_service_client import get_project_memory_context, get_memory_client

logger = logging.getLogger(__name__)


async def chat_with_smart_search(
    user_message: str,
    target_name: str = "general",
    thread_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle chat with smart auto-search.
    
    - If web search is needed, calls Brave search in background
    - Feeds results to GPT-5 for synthesis
    - Returns normal assistant message (not Brave card)
    
    Args:
        user_message: The user's message
        target_name: Target name for context
        thread_id: Optional thread ID to load/save conversation history
        conversation_history: Optional pre-loaded conversation history
        
    Returns:
        Dict with:
        - type: "assistant_message"
        - content: The assistant's response text
        - meta: Dict with usedWebSearch, webResultsPreview (if used)
        - model: Model display name
        - provider: Provider ID
    """
    # Load conversation history if thread_id is provided and history not already loaded
    if conversation_history is None:
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id)
                # Convert history to message format (filter out structured messages)
                conversation_history = []
                for msg in history:
                    if msg.get("role") in ["user", "assistant", "system"]:
                        # Skip structured messages (they have type but no content)
                        if msg.get("type") and not msg.get("content"):
                            continue
                        conversation_history.append({
                            "role": msg.get("role"),
                            "content": msg.get("content", "")
                        })
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")
                conversation_history = []
        else:
            conversation_history = []
    
    # 0. Get memory context if project_id is available
    memory_context = ""
    sources = []
    if project_id:
        try:
            memory_result = get_project_memory_context(project_id, user_message, limit=8)
            if memory_result:
                memory_context, has_memory = memory_result
                if has_memory:
                    logger.info(f"Retrieved memory context for project {project_id}")
                    # Get source names from the actual sources used
                    from server.services.memory_service_client import get_memory_sources_for_project
                    from server.services import projects_config
                    source_ids = get_memory_sources_for_project(project_id)
                    # Get source display names from Memory Service
                    client = get_memory_client()
                    all_sources = client.get_sources()
                    source_map = {s.get("id"): s.get("display_name", s.get("id")) for s in all_sources}
                    for source_id in source_ids:
                        source_name = source_map.get(source_id, source_id)
                        sources.append(f"Memory-{source_name}")
        except Exception as e:
            logger.warning(f"Failed to get memory context: {e}")
    
    # 1. Decide if we need web search
    decision = await decide_web_search(user_message)
    logger.info(f"Smart search decision: use_search={decision.use_search}, reason={decision.reason}")
    
    if not decision.use_search:
        # 2a. Plain GPT-5 chat (no Brave)
        messages = conversation_history.copy()
        if not any(msg.get("role") == "system" for msg in messages):
            system_content = CHATDO_SYSTEM_PROMPT
            if memory_context:
                system_content = f"{memory_context}\n\n{CHATDO_SYSTEM_PROMPT}"
            messages.insert(0, {"role": "system", "content": system_content})
        elif memory_context:
            # Add memory context as a separate system message before the existing system message
            messages.insert(0, {"role": "system", "content": memory_context})
        messages.append({"role": "user", "content": user_message})
        
        assistant_messages, model_id, provider_id, model_display = call_ai_router(
            messages=messages,
            intent="general_chat"
        )
        
        content = assistant_messages[0].get("content", "") if assistant_messages else ""
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id)
                history.append({"role": "user", "content": user_message})
                history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False}
                })
                memory_store.save_thread_history(target_name, thread_id, history)
            except Exception as e:
                logger.warning(f"Failed to save conversation history: {e}")
        
        return {
            "type": "assistant_message",
            "content": content,
            "meta": {
                "usedWebSearch": False,
            },
            "model": model_display,
            "provider": provider_id,
            "sources": sources if sources else None
        }
    
    # 2b. Use Brave + GPT-5
    search_query = decision.query or user_message
    logger.info(f"Performing web search for query: {search_query}")
    
    try:
        web_results = web_search.search_web(search_query, max_results=5)
    except Exception as e:
        logger.warning(f"Web search failed: {e}, falling back to GPT-5 only")
        # Fall back to GPT-5 without search results
        messages = conversation_history.copy()
        if not any(msg.get("role") == "system" for msg in messages):
            system_content = CHATDO_SYSTEM_PROMPT
            if memory_context:
                system_content = f"{memory_context}\n\n{CHATDO_SYSTEM_PROMPT}"
            messages.insert(0, {"role": "system", "content": system_content})
        elif memory_context:
            messages.insert(0, {"role": "system", "content": memory_context})
        messages.append({"role": "user", "content": user_message})
        
        assistant_messages, model_id, provider_id, model_display = call_ai_router(
            messages=messages,
            intent="general_chat"
        )
        
        content = assistant_messages[0].get("content", "") if assistant_messages else ""
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id)
                history.append({"role": "user", "content": user_message})
                history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "webSearchError": str(e)}
                })
                memory_store.save_thread_history(target_name, thread_id, history)
            except Exception as e2:
                logger.warning(f"Failed to save conversation history: {e2}")
        
        return {
            "type": "assistant_message",
            "content": content,
            "meta": {
                "usedWebSearch": False,
                "webSearchError": str(e)
            },
            "model": model_display,
            "provider": provider_id,
            "sources": sources if sources else None
        }
    
    if not web_results or len(web_results) == 0:
        logger.warning("Web search returned no results, falling back to GPT-5 only")
        # Fall back to GPT-5 without search results
        messages = conversation_history.copy()
        if not any(msg.get("role") == "system" for msg in messages):
            system_content = CHATDO_SYSTEM_PROMPT
            if memory_context:
                system_content = f"{memory_context}\n\n{CHATDO_SYSTEM_PROMPT}"
            messages.insert(0, {"role": "system", "content": system_content})
        elif memory_context:
            messages.insert(0, {"role": "system", "content": memory_context})
        messages.append({"role": "user", "content": user_message})
        
        assistant_messages, model_id, provider_id, model_display = call_ai_router(
            messages=messages,
            intent="general_chat"
        )
        
        content = assistant_messages[0].get("content", "") if assistant_messages else ""
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id)
                history.append({"role": "user", "content": user_message})
                history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "webSearchEmpty": True}
                })
                memory_store.save_thread_history(target_name, thread_id, history)
            except Exception as e:
                logger.warning(f"Failed to save conversation history: {e}")
        
        return {
            "type": "assistant_message",
            "content": content,
            "meta": {
                "usedWebSearch": False,
                "webSearchEmpty": True
            },
            "model": model_display,
            "provider": provider_id,
            "sources": sources if sources else None
        }
    
    # Format web results for GPT-5
    web_results_text = "Web search results:\n\n"
    for i, result in enumerate(web_results[:5], 1):
        web_results_text += f"{i}. {result.get('title', 'No title')}\n"
        web_results_text += f"   URL: {result.get('url', '')}\n"
        web_results_text += f"   {result.get('snippet', 'No snippet')}\n\n"
    
    # Use the shared ChatDO system prompt - it already includes instructions for web search
    # The web search results will be provided as context in a separate system message
    system_prompt = CHATDO_SYSTEM_PROMPT
    if memory_context:
        system_prompt = f"{memory_context}\n\n{system_prompt}"
    
    # Build messages with web search context
    messages = conversation_history.copy()
    if not any(msg.get("role") == "system" for msg in messages):
        messages.insert(0, {"role": "system", "content": system_prompt})
    else:
        # Replace existing system message
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                messages[i] = {"role": "system", "content": system_prompt}
                break
    
    messages.append({"role": "user", "content": user_message})
    messages.append({
        "role": "system",
        "content": web_results_text
    })
    
    # Call GPT-5 with web search context
    assistant_messages, model_id, provider_id, model_display = call_ai_router(
        messages=messages,
        intent="general_chat"
    )
    
    content = assistant_messages[0].get("content", "") if assistant_messages else ""
    
    # Save to memory store if thread_id is provided
    if thread_id:
        try:
            history = memory_store.load_thread_history(target_name, thread_id)
            # Add user message
            history.append({"role": "user", "content": user_message})
            # Add assistant message
            # Add Brave Search to sources if web search was used
            web_sources = sources.copy() if sources else []
            web_sources.append("Brave Search")
            
            history.append({
                "role": "assistant",
                "content": content,
                "model": model_display,
                "provider": provider_id,
                "sources": web_sources,
                "meta": {
                    "usedWebSearch": True,
                    "webResultsPreview": web_results[:5]
                }
            })
            memory_store.save_thread_history(target_name, thread_id, history)
        except Exception as e:
            logger.warning(f"Failed to save conversation history: {e}")
    
    # Add Brave Search to sources if web search was used
    web_sources = sources.copy() if sources else []
    web_sources.append("Brave Search")
    
    return {
        "type": "assistant_message",
        "content": content,
        "meta": {
            "usedWebSearch": True,
            "webResultsPreview": web_results[:5]  # Top 5 for sources display
        },
        "model": model_display,
        "provider": provider_id,
        "sources": web_sources
    }

