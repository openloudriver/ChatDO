"""
Smart chat orchestrator - handles normal chat with optional background web search.
When web search is needed, it's done in the background and results are fed to GPT-5.
"""
import json
import logging
from typing import Dict, List, Any, Optional
from chatdo.tools import web_search
from chatdo.agents.ai_router import call_ai_router
from chatdo.prompts import CHATDO_SYSTEM_PROMPT
from chatdo.memory import store as memory_store
from .smart_search_classifier import decide_web_search
from .memory_service_client import get_project_memory_context, get_memory_client
from . import librarian

logger = logging.getLogger(__name__)

def build_filetree_guidance(project_id: Optional[str] = None) -> str:
    """
    Build FileTree guidance with automatically injected available sources.
    
    Args:
        project_id: Optional project ID to automatically list available sources
        
    Returns:
        FileTree guidance string with available sources if project_id is provided
    """
    base_guidance = """
You have access to FileTree tools for exploring memory sources:

1. filetree_list(source_id, max_depth=10, max_entries=1000)
   - Use this to explore the directory structure of a memory source.
   - max_depth is clamped to 10. max_entries is clamped to 1000.

2. filetree_read(source_id, path, max_bytes=512000)
   - Use this to read a specific file's contents.
   - max_bytes is clamped to 512 KB.

Do NOT invent shell commands or filesystem paths. Always use the FileTree tools.
"""
    
    # Automatically inject available sources if project_id is provided
    if project_id:
        from server.services.memory_service_client import get_project_sources_with_details
        sources = get_project_sources_with_details(project_id)
        
        if sources:
            sources_text = "\n\n**Available Memory Sources for this Project:**\n"
            sources_text += "You already know the following memory sources are available. Use the source_id when calling FileTree tools:\n\n"
            for source in sources:
                source_id = source.get("id", "")
                display_name = source.get("display_name", source_id)
                sources_text += f"- **{display_name}** → source_id: `{source_id}`\n"
            sources_text += "\nWhen the user mentions a memory source by name (e.g., 'Coin'), use the corresponding source_id from the list above.\n"
            base_guidance = sources_text + base_guidance
    
    return base_guidance


async def handle_filetree_tool_call(tool_name: str, arguments: dict, project_id: Optional[str] = None) -> dict:
    """
    Handle FileTree tool calls from GPT-5.
    
    Args:
        tool_name: Name of the tool ("filetree_list_sources", "filetree_list", or "filetree_read")
        arguments: Tool arguments dict
        project_id: Optional project ID for source discovery
        
    Returns:
        Tool result as a JSON-serializable dict with "tool_call_result" key
    """
    memory_client = get_memory_client()
    
    if tool_name == "filetree_list_sources":
        # List available sources for a project
        from server.services.memory_service_client import get_project_sources_with_details
        
        if not project_id:
            return {
                "tool_call_result": {
                    "error": "project_id is required for filetree_list_sources",
                    "sources": []
                }
            }
        
        sources = get_project_sources_with_details(project_id)
        return {
            "tool_call_result": {
                "project_id": project_id,
                "sources": sources,
                "count": len(sources)
            }
        }
    
    elif tool_name == "filetree_list":
        result = await memory_client.filetree_list(
            source_id=arguments["source_id"],
            max_depth=arguments.get("max_depth", 10),
            max_entries=arguments.get("max_entries", 1000),
        )
        return {"tool_call_result": result}
    
    elif tool_name == "filetree_read":
        result = await memory_client.filetree_read(
            source_id=arguments["source_id"],
            path=arguments["path"],
            max_bytes=arguments.get("max_bytes", 512000),
        )
        return {"tool_call_result": result}
    
    else:
        logger.warning(f"[FILETREE] Unknown tool name: {tool_name}")
        return {
            "tool_call_result": {
                "error": f"Unknown tool: {tool_name}",
                "source_id": arguments.get("source_id", "unknown")
            }
        }


async def call_ai_router_with_tool_loop(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    intent: str = "general_chat",
    project_id: Optional[str] = None
) -> tuple[str, str, str, str]:
    """
    Call AI Router and process tool calls in a loop.
    
    Args:
        messages: Conversation messages
        tools: List of available tools
        intent: AI intent for routing
        
    Returns:
        Tuple of (content, model_id, provider_id, model_display)
    """
    # Call AI Router (may return tool_calls that need processing)
    assistant_messages, model_id, provider_id, model_display = call_ai_router(
        messages=messages,
        intent=intent,
        tools=tools
    )
    
    # Process tool calls if present (tool loop)
    if assistant_messages and len(assistant_messages) > 0:
        assistant_message = assistant_messages[0]
        # Check if there are tool_calls to process
        if assistant_message.get("tool_calls"):
            logger.info(f"[TOOL-LOOP] Starting tool loop with {len(assistant_message.get('tool_calls', []))} tool call(s)")
            # Process tool calls in a loop
            _, content = await process_tool_calls(
                messages=messages,
                assistant_message=assistant_message,
                tools=tools,
                max_iterations=10,
                project_id=project_id
            )
        else:
            # No tool calls, just extract content
            content = assistant_message.get("content", "")
    else:
        content = ""
    
    return content, model_id, provider_id, model_display


async def process_tool_calls(
    messages: List[Dict[str, Any]],
    assistant_message: Dict[str, Any],
    tools: List[Dict[str, Any]],
    max_iterations: int = 10,
    project_id: Optional[str] = None
) -> tuple[List[Dict[str, Any]], str]:
    """
    Process tool calls in a loop until no more tool calls are present.
    
    Args:
        messages: Current conversation messages
        assistant_message: The assistant message that may contain tool_calls
        tools: List of available tools
        max_iterations: Maximum number of tool call iterations (safety limit)
        project_id: Optional project ID for source discovery (used by filetree_list_sources)
        
    Returns:
        Tuple of (final messages list, final content string)
    """
    iteration = 0
    current_messages = messages.copy()
    current_assistant_message = assistant_message
    
    while iteration < max_iterations:
        # Check if the assistant message has tool_calls
        tool_calls = current_assistant_message.get("tool_calls")
        
        if not tool_calls or len(tool_calls) == 0:
            # No more tool calls, return the final content
            content = current_assistant_message.get("content", "")
            return current_messages, content
        
        logger.info(f"[TOOL-LOOP] Iteration {iteration + 1}: Processing {len(tool_calls)} tool call(s)")
        
        # Add the assistant message with tool_calls to the conversation
        current_messages.append({
            "role": "assistant",
            "content": current_assistant_message.get("content", ""),
            "tool_calls": tool_calls
        })
        
        # Execute each tool call and collect results
        tool_results = []
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")
            function_name = tool_call.get("function", {}).get("name")
            function_args_str = tool_call.get("function", {}).get("arguments", "{}")
            
            if not tool_call_id or not function_name:
                logger.warning(f"[TOOL-LOOP] Invalid tool_call structure: {tool_call}")
                continue
            
            # Parse function arguments
            try:
                function_args = json.loads(function_args_str)
            except json.JSONDecodeError as e:
                logger.error(f"[TOOL-LOOP] Failed to parse tool arguments: {e}, args={function_args_str}")
                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps({"error": f"Invalid JSON in tool arguments: {e}"})
                })
                continue
            
            # Execute the tool call
            logger.info(f"[TOOL-LOOP] Executing tool: {function_name} with args: {function_args}")
            try:
                if function_name in ["filetree_list_sources", "filetree_list", "filetree_read"]:
                    # For filetree_list_sources, use project_id from arguments or context
                    if function_name == "filetree_list_sources":
                        tool_project_id = function_args.get("project_id") or project_id
                        tool_result = await handle_filetree_tool_call(function_name, function_args, project_id=tool_project_id)
                    else:
                        tool_result = await handle_filetree_tool_call(function_name, function_args, project_id=project_id)
                    # Format result as JSON string for OpenAI
                    tool_results.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(tool_result)
                    })
                else:
                    logger.warning(f"[TOOL-LOOP] Unknown tool: {function_name}")
                    tool_results.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps({"error": f"Unknown tool: {function_name}"})
                    })
            except Exception as e:
                logger.error(f"[TOOL-LOOP] Error executing tool {function_name}: {e}", exc_info=True)
                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps({"error": str(e)})
                })
        
        # Add tool results to messages
        current_messages.extend(tool_results)
        
        # Verify message structure before sending
        logger.info(f"[TOOL-LOOP] Calling AI Router again with {len(current_messages)} messages")
        # Log the last few messages to verify structure
        for i, msg in enumerate(current_messages[-5:]):
            logger.debug(f"[TOOL-LOOP] Message {len(current_messages)-5+i}: role={msg.get('role')}, has_tool_calls={bool(msg.get('tool_calls'))}, has_tool_call_id={bool(msg.get('tool_call_id'))}")
        
        assistant_messages, _, _, _ = call_ai_router(
            messages=current_messages,
            intent="general_chat",
            tools=tools
        )
        
        if not assistant_messages or len(assistant_messages) == 0:
            logger.warning("[TOOL-LOOP] No response from AI Router")
            break
        
        # Update current assistant message for next iteration
        current_assistant_message = assistant_messages[0]
        iteration += 1
    
    if iteration >= max_iterations:
        logger.warning(f"[TOOL-LOOP] Reached max iterations ({max_iterations}), stopping tool loop")
    
    # Return final content
    content = current_assistant_message.get("content", "")
    return current_messages, content


# FileTree tool definitions for GPT-5
FILETREE_LIST_SOURCES_TOOL = {
    "type": "function",
    "function": {
        "name": "filetree_list_sources",
        "description": (
            "List all available memory sources for the current project. "
            "Use this FIRST when the user mentions a memory source by display name (e.g., 'Coin') "
            "to discover the correct source_id. Returns a list of sources with their IDs and display names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project ID (e.g., 'general', 'chatdo', 'privacypay'). If not provided, will use the current project context."
                }
            },
            "required": []
        }
    }
}

FILETREE_LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "filetree_list",
        "description": "Return a directory tree for a memory source using the Memory Service FileTree API.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "max_depth": {"type": "integer"},
                "max_entries": {"type": "integer"}
            },
            "required": ["source_id"]
        }
    }
}

FILETREE_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "filetree_read",
        "description": "Read a single file from a memory source using the Memory Service FileTree API.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "path": {"type": "string"},
                "max_bytes": {"type": "integer"}
            },
            "required": ["source_id", "path"]
        }
    }
}


def build_model_label(used_web: bool, used_memory: bool) -> str:
    """
    Build model label based on what was used.
    
    Returns:
        - "GPT-5" if neither web nor memory
        - "Memory + GPT-5" if only memory
        - "Brave + GPT-5" if only web
        - "Brave + Memory + GPT-5" if both
    """
    if used_web and used_memory:
        return "Brave + Memory + GPT-5"
    elif used_web:
        return "Brave + GPT-5"
    elif used_memory:
        return "Memory + GPT-5"
    else:
        return "GPT-5"


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
    has_memory = False
    searched_memory = False  # Track if we attempted to search memory (even if no results)
    if project_id:
        try:
            # Use Librarian for smarter ranking and deduplication
            # Librarian handles cross-chat memory and boosts answers over questions
            hits = librarian.get_relevant_memory(
                project_id=project_id,
                query=user_message,
                chat_id=None,  # Include all chats for cross-chat memory
                max_hits=30
            )
            searched_memory = True  # We attempted to search, regardless of results
            if hits:
                # Format hits into context string
                memory_context = librarian.format_hits_as_context(hits)
                has_memory = True
                logger.info(f"[MEMORY] Retrieved memory context for project_id={project_id}, chat_id={thread_id} ({len(hits)} hits)")
            else:
                logger.info(f"[MEMORY] Searched memory for project_id={project_id} but found no results")
            # Get source names from the actual sources used
            from server.services.memory_service_client import get_memory_sources_for_project
            from server.services import projects_config  # noqa: F401  # imported for side-effects / future use
            source_ids = get_memory_sources_for_project(project_id)
            # Get source display names from Memory Service
            try:
                client = get_memory_client()
                all_sources = client.get_sources()
                source_map = {s.get("id"): s.get("display_name", s.get("id")) for s in all_sources}
                for source_id in source_ids:
                    source_name = source_map.get(source_id, source_id)
                    sources.append(f"Memory-{source_name}")
            except Exception as source_error:
                logger.debug(f"Failed to get source names: {source_error}")
        except Exception as e:
            logger.warning(f"Failed to get memory context: {e}")
    
    # Build FileTree guidance with available sources (do this once, before any branching)
    filetree_guidance = build_filetree_guidance(project_id)
    logger.info(f"[FILETREE-GUIDANCE] project_id={project_id} guidance_length={len(filetree_guidance)}")
    
    # Initialize messages list ONCE at the top - all code paths will modify this same list
    messages: List[Dict[str, Any]] = conversation_history.copy()
    
    # Build base system prompt with FileTree guidance
    base_system_prompt = CHATDO_SYSTEM_PROMPT + filetree_guidance
    if memory_context:
        base_system_prompt = f"{memory_context}\n\n{base_system_prompt}"
    
    # Add system message to messages (only if not already present)
    if not any(msg.get("role") == "system" for msg in messages):
        messages.insert(0, {"role": "system", "content": base_system_prompt})
    else:
        # Update existing system message to include FileTree guidance
        for msg in messages:
            if msg.get("role") == "system" and CHATDO_SYSTEM_PROMPT in msg.get("content", ""):
                # Append FileTree guidance if not already present
                if filetree_guidance not in msg.get("content", ""):
                    msg["content"] = msg["content"] + filetree_guidance
                break
    
    # Add user message to messages (always)
    messages.append({"role": "user", "content": user_message})
    
    # Build tools list (always include FileTree tools)
    tools = [FILETREE_LIST_TOOL, FILETREE_READ_TOOL]
    
    # 1. Decide if we need web search
    # For now, use the existing classifier. In the future, this could accept web_mode parameter
    decision = await decide_web_search(user_message)
    logger.info(f"Smart search decision: use_search={decision.use_search}, reason={decision.reason}")
    
    if not decision.use_search:
        # 2a. Plain GPT-5 chat (no Brave)
        # messages, tools, and system prompt are already set up above
        
        # Call AI Router with tool loop processing
        content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
            messages=messages,
            tools=tools,
            intent="general_chat",
            project_id=project_id
        )
        
        # Build model label based on what was used
        used_web = False
        used_memory = has_memory  # Only show Memory if we actually found and used memory results
        
        model_display = build_model_label(used_web=used_web, used_memory=used_memory)
        logger.info(f"[MODEL] model label = {model_display}")
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                from datetime import datetime, timezone
                from server.services.memory_service_client import get_memory_client
                
                history = memory_store.load_thread_history(target_name, thread_id)
                message_index = len(history)
                
                # Add user message
                history.append({"role": "user", "content": user_message})
                
                # Index user message into Memory Service for cross-chat search
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        user_message_id = f"{thread_id}-user-{message_index}"
                        logger.info(f"[MEMORY] Attempting to index user message {user_message_id} for project {project_id}")
                        success = memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=thread_id,
                            message_id=user_message_id,
                            role="user",
                            content=user_message,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            message_index=message_index
                        )
                        if success:
                            logger.info(f"[MEMORY] ✅ Successfully indexed user message {user_message_id} for project {project_id}")
                        else:
                            logger.warning(f"[MEMORY] ❌ Failed to index user message {user_message_id} for project {project_id} (Memory Service returned False)")
                    except Exception as e:
                        logger.warning(f"[MEMORY] ❌ Exception indexing user message: {e}", exc_info=True)
                else:
                    logger.warning(f"[MEMORY] ⚠️  Skipping user message indexing: project_id is None (thread_id={thread_id})")
                
                # Add assistant message
                history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "usedMemory": used_memory}
                })
                memory_store.save_thread_history(target_name, thread_id, history)
                
                # Index assistant message into Memory Service for cross-chat search
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                        logger.info(f"[MEMORY] Attempting to index assistant message {assistant_message_id} for project {project_id}")
                        success = memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=thread_id,
                            message_id=assistant_message_id,
                            role="assistant",
                            content=content,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            message_index=message_index + 1
                        )
                        if success:
                            logger.info(f"[MEMORY] ✅ Successfully indexed assistant message {assistant_message_id} for project {project_id}")
                        else:
                            logger.warning(f"[MEMORY] ❌ Failed to index assistant message {assistant_message_id} for project {project_id} (Memory Service returned False)")
                    except Exception as e:
                        logger.warning(f"[MEMORY] ❌ Exception indexing assistant message: {e}", exc_info=True)
                else:
                    logger.warning(f"[MEMORY] ⚠️  Skipping assistant message indexing: project_id is None (thread_id={thread_id})")
            except Exception as e:
                logger.warning(f"Failed to save conversation history: {e}")
        
        return {
            "type": "assistant_message",
            "content": content,
            "meta": {
                "usedWebSearch": False,
                "usedMemory": used_memory,
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
        # messages, tools, and system prompt are already set up above
        
        content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
            messages=messages,
            tools=tools,
            intent="general_chat",
            project_id=project_id
        )
        
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
        # messages, tools, and system prompt are already set up above
        
        content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
            messages=messages,
            tools=tools,
            intent="general_chat",
            project_id=project_id
        )
        
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
    
    # Convert web results to Source[] format
    web_sources = []
    for i, result in enumerate(web_results[:5]):
        # Extract domain for siteName
        site_name = None
        if result.get('url'):
            try:
                from urllib.parse import urlparse
                parsed = urlparse(result['url'])
                site_name = parsed.netloc.replace('www.', '')
            except:
                pass
        
        source = {
            'id': f'web-{i}',
            'title': result.get('title', 'Untitled'),
            'url': result.get('url'),
            'description': result.get('snippet', ''),
            'siteName': site_name,
            'rank': i,
            'sourceType': 'web'
        }
        web_sources.append(source)
    
    # Format web results for GPT-5 with citation instructions
    web_results_text = "You have access to the following up-to-date web sources.\n"
    web_results_text += "When you use a specific fact from a source, add a citation like [1] or [2] at the end of the relevant sentence.\n"
    web_results_text += "Use these sources only when needed; otherwise, answer normally.\n\n"
    
    for i, result in enumerate(web_results[:5], 1):
        url_str = f" ({result.get('url', '')})" if result.get('url') else ""
        web_results_text += f"{i}. {result.get('title', 'No title')}{url_str}\n"
        web_results_text += f"{result.get('snippet', 'No snippet')}\n\n"
    
    # Web search succeeded - add web context to existing messages
    # Update system prompt to include web citation instructions
    system_prompt_with_web = base_system_prompt + "\n\nWhen you use a fact from the web sources above, add inline citations like [1], [2], or [1, 3] at the end of the sentence. If the answer does not require web sources, you may answer without citations."
    
    # Update or add system messages for web context
    system_found = False
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages[i] = {"role": "system", "content": system_prompt_with_web}
            # Insert web context after system prompt
            messages.insert(i + 1, {"role": "system", "content": web_results_text})
            system_found = True
            break
    
    if not system_found:
        # No system message found, add both
        messages.insert(0, {"role": "system", "content": system_prompt_with_web})
        messages.insert(1, {"role": "system", "content": web_results_text})
    
    # Call GPT-5 with web search context (with tool loop processing)
    content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
        messages=messages,
        tools=tools,
        intent="general_chat",
        project_id=project_id
    )
    
    # Save to memory store if thread_id is provided
    if thread_id:
        try:
            from datetime import datetime, timezone
            from server.services.memory_service_client import get_memory_client
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            
            # Add user message
            history.append({"role": "user", "content": user_message})
            
            # Index user message into Memory Service for cross-chat search
            if project_id:
                try:
                    memory_client = get_memory_client()
                    user_message_id = f"{thread_id}-user-{message_index}"
                    logger.info(f"[MEMORY] Attempting to index user message {user_message_id} for project {project_id}")
                    success = memory_client.index_chat_message(
                        project_id=project_id,
                        chat_id=thread_id,
                        message_id=user_message_id,
                        role="user",
                        content=user_message,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        message_index=message_index
                    )
                    if success:
                        logger.info(f"[MEMORY] ✅ Successfully indexed user message {user_message_id} for project {project_id}")
                    else:
                        logger.warning(f"[MEMORY] ❌ Failed to index user message {user_message_id} for project {project_id} (Memory Service returned False)")
                except Exception as e:
                    logger.warning(f"[MEMORY] ❌ Exception indexing user message: {e}", exc_info=True)
            else:
                logger.warning(f"[MEMORY] ⚠️  Skipping user message indexing: project_id is None (thread_id={thread_id})")
            
            # Add assistant message
            # Add Brave Search to sources if web search was used
            web_sources = sources.copy() if sources else []
            web_sources.append("Brave Search")
            
            # Combine memory sources with web sources
            all_sources = (sources.copy() if sources else []) + web_sources
            
            assistant_message = {
                "role": "assistant",
                "content": content,
                "model": build_model_label(used_web=bool(web_sources), used_memory=has_memory),
                "provider": provider_id,
                "sources": all_sources if all_sources else None,
                "meta": {
                    "usedWebSearch": True,
                    "webResultsPreview": web_results[:5]
                }
            }
            history.append(assistant_message)
            memory_store.save_thread_history(target_name, thread_id, history)
            
            # Index assistant message into Memory Service for cross-chat search
            if project_id:
                try:
                    memory_client = get_memory_client()
                    assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                    logger.info(f"[MEMORY] Attempting to index assistant message {assistant_message_id} for project {project_id}")
                    success = memory_client.index_chat_message(
                        project_id=project_id,
                        chat_id=thread_id,
                        message_id=assistant_message_id,
                        role="assistant",
                        content=content,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        message_index=message_index + 1
                    )
                    if success:
                        logger.info(f"[MEMORY] ✅ Successfully indexed assistant message {assistant_message_id} for project {project_id}")
                    else:
                        logger.warning(f"[MEMORY] ❌ Failed to index assistant message {assistant_message_id} for project {project_id} (Memory Service returned False)")
                except Exception as e:
                    logger.warning(f"[MEMORY] ❌ Exception indexing assistant message: {e}", exc_info=True)
            else:
                logger.warning(f"[MEMORY] ⚠️  Skipping assistant message indexing: project_id is None (thread_id={thread_id})")
        except Exception as e:
            logger.warning(f"Failed to save conversation history: {e}")
    
    # Combine memory sources with web sources
    all_sources = (sources.copy() if sources else []) + web_sources
    
    return {
        "type": "assistant_message",
        "content": content,
        "meta": {
            "usedWebSearch": True,
            "usedMemory": has_memory,
            "webResultsPreview": web_results[:5]  # Top 5 for sources display
        },
        "model": build_model_label(used_web=bool(web_sources), used_memory=searched_memory),
        "provider": provider_id,
        "sources": all_sources if all_sources else None
    }

