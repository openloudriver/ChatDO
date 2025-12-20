"""
Smart chat orchestrator - handles normal chat with optional background web search.
When web search is needed, it's done in the background and results are fed to GPT-5.
"""
import json
import logging
import re
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from uuid import uuid4
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


def build_model_label(used_web: bool, used_memory: bool, escalated: bool = True) -> str:
    """
    Build model label based on what was used.
    
    NOTE: Memory is now a tool only. GPT-5 always generates responses.
    "Model: Memory" is preserved as a source label to indicate Memory-backed responses.
    
    Args:
        used_web: Whether Brave web search was used
        used_memory: Whether Memory was used
        escalated: Always True (GPT-5 is always used, kept for compatibility)
    
    Returns:
        - "GPT-5" if nothing special
        - "Memory" if only memory (source label - GPT-5 still generates response)
        - "Memory + GPT-5" if only memory (alternative label format)
        - "Brave + GPT-5" if only web
        - "Brave + Memory + GPT-5" if both web and memory
    """
    if used_web and used_memory:
        return "Brave + Memory + GPT-5"
    elif used_web:
        return "Brave + GPT-5"
    elif used_memory:
        # Return "Memory + GPT-5" to show GPT-5 generated the response using Memory
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
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
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
    
    # CRITICAL: Index user message BEFORE searching memory to avoid race condition
    # This ensures that if the user asks a follow-up question immediately, the Memory Service
    # can find the message they just sent
    # Also extract and store facts (ranked lists) from user messages into facts DB
    if thread_id and project_id:
        try:
            from server.services.memory_service_client import get_memory_client
            from server.services.ranked_lists import extract_ranked_lists
            from server.services.facts import normalize_topic_key
            from uuid import uuid4
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            user_msg_created_at = datetime.now(timezone.utc).isoformat()
            user_message_id = f"{thread_id}-user-{message_index}"
            
            # Index user message immediately (before memory search)
            memory_client = get_memory_client()
            logger.info(f"[MEMORY] Indexing user message BEFORE memory search: {user_message_id} for project {project_id}")
            success = memory_client.index_chat_message(
                project_id=project_id,
                chat_id=thread_id,
                message_id=user_message_id,
                role="user",
                content=user_message,
                timestamp=user_msg_created_at,
                message_index=message_index
            )
            if success:
                logger.info(f"[MEMORY] ✅ Successfully indexed user message {user_message_id} for project {project_id} (before search)")
            else:
                logger.warning(f"[MEMORY] ❌ Failed to index user message {user_message_id} for project {project_id} (Memory Service returned False)")
            
            # Extract and store ranked facts ONLY when extraction is valid + topic is known
            from server.services.facts import extract_ranked_facts
            
            # Compute topic_key and ranked facts
            topic_key = normalize_topic_key(user_message)
            ranked_facts = extract_ranked_facts(user_message)
            
            # Store ONLY if both topic_key and ranked facts exist
            if topic_key and ranked_facts:
                logger.info(f"[FACTS] Storing {len(ranked_facts)} ranked fact(s) for topic_key={topic_key}")
                for rank, value in ranked_facts:
                    success = memory_client.store_fact(
                        project_id=project_id,
                        topic_key=topic_key,
                        kind="ranked",
                        value=value,
                        source_message_id=user_message_id,
                        chat_id=thread_id,
                        rank=rank
                    )
                    if success:
                        logger.info(f"[FACTS] ✅ Stored fact: topic_key={topic_key}, rank={rank}, value={value}")
                    else:
                        logger.warning(f"[FACTS] ❌ Failed to store fact: topic_key={topic_key}, rank={rank}")
            elif topic_key and not ranked_facts:
                logger.debug(f"[FACTS] Topic key found ({topic_key}) but no ranked facts extracted - skipping storage")
            elif not topic_key and ranked_facts:
                logger.debug(f"[FACTS] Ranked facts found but no topic key - skipping storage")
            else:
                logger.debug(f"[FACTS] No topic key and no ranked facts - skipping storage")
        except Exception as e:
            logger.warning(f"[MEMORY] ❌ Exception indexing user message before search: {e}", exc_info=True)
    
    # ============================================================================
    # REMOVED: Facts retrieval bypass
    # ============================================================================
    # All queries now go through GPT-5. Memory Service is a tool only - it provides
    # structured evidence, but GPT-5 always generates the user-facing response.
    # Facts are still retrieved and passed as context to GPT-5, but GPT-5 formats the response.
    
    # NOTE: Facts retrieval bypass removed - all responses must go through GPT-5
    # The facts DB is still used, but facts are passed as Memory context to GPT-5
    # instead of being returned directly.
    
    if False and project_id:  # Disabled - all queries go through GPT-5
        from server.services.ranked_lists import detect_ordinal_query
        from server.services.facts import extract_topic_from_query, normalize_topic_key
        memory_client = get_memory_client()
        
        # Check if this is an ordinal query (e.g., "second favorite color", "#2 favorite crypto")
        ordinal_result = detect_ordinal_query(user_message)
        if ordinal_result:
            rank, topic = ordinal_result
            logger.info(f"[FACTS] Detected ordinal query: rank={rank}, topic={topic}")
            
            # Determine topic_key STRICTLY
            # If query includes topic noun → use that topic_key only
            topic_key = normalize_topic_key(topic) if topic else None
            
            # If query does NOT include topic noun, use most recent topic_key in this chat_id ONLY
            if not topic_key and thread_id:
                from memory_service.memory_dashboard import db
                topic_key = db.get_most_recent_topic_key_in_chat(project_id, thread_id)
                if topic_key:
                    logger.info(f"[FACTS] Using most recent topic_key in chat: {topic_key}")
            
            # If topic_key still None → return clarification question (no GPT-5 Mini)
            if not topic_key:
                clarification = "Which category (colors/cryptos/tv/candies)?"
                logger.info(f"[FACTS] Topic key is None - returning clarification question")
                if thread_id:
                    try:
                        history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                        model_label = "Model: Memory"
                        history.append({
                            "id": str(uuid4()),
                            "role": "assistant",
                            "content": clarification,
                            "model": "Memory",
                            "model_label": model_label,
                            "provider": "memory",
                            "created_at": assistant_msg_created_at
                        })
                        memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                    except Exception as e:
                        logger.warning(f"Failed to save clarification to history: {e}")
                
                return {
                    "type": "assistant_message",
                    "content": clarification,
                    "meta": {"usedFacts": True, "clarification": True},
                    "model": "Memory",
                    "model_label": "Model: Memory",
                    "provider": "memory",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                # Query facts DB for this rank (cross-chat: chat_id=None to search all chats in project)
                fact = memory_client.get_fact_by_rank(
                    project_id=project_id,
                    topic_key=topic_key,
                    rank=rank,
                    chat_id=None  # Cross-chat: search all chats in project, not just current chat
                )
                
                if fact:
                    answer = fact.get("value")
                    fact_chat_id = fact.get("chat_id")
                    logger.info(f"[FACTS] ✅ Answering ordinal query from facts DB: rank={rank}, topic_key={topic_key}, answer={answer}, chat_id={fact_chat_id}")
                    
                    # Format response
                    ordinal_words = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 
                                    6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
                    ordinal_word = ordinal_words.get(rank, f"#{rank}")
                    topic_display = topic_key.replace("_", " ").replace("favorite ", "")
                    formatted_answer = f"Your {topic_display} ranked {ordinal_word} is **{answer}**. [M1]"
                    
                    # Build sources array for UI to display source tag
                    sources = []
                    if fact_chat_id:
                        sources.append({
                            "id": "memory-fact-1",
                            "title": "Stored Fact",
                            "siteName": "Memory",
                            "description": f"From chat {fact_chat_id[:8]}...",
                            "rank": 0,
                            "sourceType": "memory",
                            "citationPrefix": "M",
                            "meta": {
                                "chat_id": fact_chat_id,
                                "message_id": fact.get("source_message_id"),
                                "topic_key": topic_key,
                                "rank": rank,
                                "value": answer
                            }
                        })
                    
                    # Save to history
                    if thread_id:
                        try:
                            history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                            model_label = "Model: Memory"
                            history.append({
                                "id": str(uuid4()),
                                "role": "assistant",
                                "content": formatted_answer,
                                "model": "Memory",
                                "model_label": model_label,
                                "provider": "memory",
                                "created_at": assistant_msg_created_at
                            })
                            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                        except Exception as e:
                            logger.warning(f"Failed to save ordinal answer to history: {e}")
                    
                    # Return direct answer WITHOUT calling GPT-5 Mini
                    return {
                        "type": "assistant_message",
                        "content": formatted_answer,
                        "meta": {"usedFacts": True},
                        "sources": sources,
                        "model": "Memory",
                        "model_label": "Model: Memory",
                        "provider": "memory",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    logger.info(f"[FACTS] Ordinal query detected but no fact found: rank={rank}, topic_key={topic_key}")
                    # Return "I don't have that stored yet" - do NOT call GPT-5 Mini
                    if thread_id:
                        try:
                            history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                            model_label = "Model: Memory"
                            response_text = "I don't have that stored yet."
                            history.append({
                                "id": str(uuid4()),
                                "role": "assistant",
                                "content": response_text,
                                "model": "Memory",
                                "model_label": model_label,
                                "provider": "memory",
                                "created_at": assistant_msg_created_at
                            })
                            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                        except Exception as e:
                            logger.warning(f"Failed to save 'not found' answer to history: {e}")
                    
                    return {
                        "type": "assistant_message",
                        "content": "I don't have that stored yet.",
                        "meta": {"usedFacts": True, "factNotFound": True},
                        "model": "Memory",
                        "model_label": "Model: Memory",
                        "provider": "memory",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
        
        # Check if query is asking for full list (e.g., "list my favorite colors", "what are my favorite X")
        if re.search(r'\b(list|show|what are)\s+(?:my|all|your)?\s*(?:favorite|top)?', user_message.lower()):
            # Determine topic_key STRICTLY
            # If query includes topic noun → use that topic_key only
            topic_key = extract_topic_from_query(user_message)
            
            # If query does NOT include topic noun, use most recent topic_key in this chat_id ONLY
            if not topic_key and thread_id:
                from memory_service.memory_dashboard import db
                topic_key = db.get_most_recent_topic_key_in_chat(project_id, thread_id)
                if topic_key:
                    logger.info(f"[FACTS] Using most recent topic_key in chat for list query: {topic_key}")
            
            # If topic_key still None → return clarification question (no GPT-5 Mini)
            if not topic_key:
                clarification = "Which category (colors/cryptos/tv/candies)?"
                logger.info(f"[FACTS] Topic key is None for list query - returning clarification question")
                if thread_id:
                    try:
                        history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                        model_label = "Model: Memory"
                        history.append({
                            "id": str(uuid4()),
                            "role": "assistant",
                            "content": clarification,
                            "model": "Memory",
                            "model_label": model_label,
                            "provider": "memory",
                            "created_at": assistant_msg_created_at
                        })
                        memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                    except Exception as e:
                        logger.warning(f"Failed to save clarification to history: {e}")
                
                return {
                    "type": "assistant_message",
                    "content": clarification,
                    "meta": {"usedFacts": True, "clarification": True},
                    "model": "Memory",
                    "model_label": "Model: Memory",
                    "provider": "memory",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            
            logger.info(f"[FACTS] Detected full list query: topic_key={topic_key}")
            
            # Get all facts for this topic (cross-chat: chat_id=None to search all chats in project)
            facts = memory_client.get_facts(
                project_id=project_id,
                topic_key=topic_key,
                chat_id=None  # Cross-chat: search all chats in project, not just current chat
            )
            
            # Filter to only ranked facts (kind="ranked")
            ranked_facts = [f for f in facts if f.get("kind") == "ranked"]
            
            if ranked_facts:
                # Sort by rank
                ranked_facts.sort(key=lambda f: f.get("rank", 0))
                
                # Format: Output exactly "1) <value>\n2) <value>\n3) <value>" - NO markdown headings, NO ##, NO M1
                list_items = "\n".join([f"{f.get('rank', 0)}) {f.get('value')}" for f in ranked_facts])
                list_text = list_items
                
                # Build sources array for UI to display source tags (one source per unique chat)
                chat_sources = {}
                for idx, fact in enumerate(ranked_facts):
                    fact_chat_id = fact.get("chat_id")
                    if fact_chat_id and fact_chat_id not in chat_sources:
                        chat_sources[fact_chat_id] = {
                            "id": f"memory-fact-{len(chat_sources) + 1}",
                            "title": f"Stored Facts (Chat {fact_chat_id[:8]}...)",
                            "siteName": "Memory",
                            "description": f"Ranked list from chat {fact_chat_id[:8]}...",
                            "rank": len(chat_sources),
                            "sourceType": "memory",
                            "citationPrefix": "M",
                            "meta": {
                                "chat_id": fact_chat_id,
                                "topic_key": topic_key,
                                "fact_count": len([f for f in ranked_facts if f.get("chat_id") == fact_chat_id])
                            }
                        }
                
                sources = list(chat_sources.values())
                logger.info(f"[FACTS] ✅ Returning full ranked list from facts DB: topic_key={topic_key}, items={len(ranked_facts)}, sources={len(sources)}")
                
                # Save to history
                if thread_id:
                    try:
                        history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                        model_label = "Model: Memory"
                        history.append({
                            "id": str(uuid4()),
                            "role": "assistant",
                            "content": list_text,
                            "model": "Memory",
                            "model_label": model_label,
                            "provider": "memory",
                            "created_at": assistant_msg_created_at
                        })
                        memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                    except Exception as e:
                        logger.warning(f"Failed to save list answer to history: {e}")
                
                # Return direct answer WITHOUT calling Llama
                return {
                    "type": "assistant_message",
                    "content": list_text,
                    "meta": {"usedFacts": True},
                    "sources": sources,
                    "model": "Memory",
                    "model_label": "Model: Memory",
                    "provider": "memory",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                logger.info(f"[FACTS] Full list query detected but no ranked facts found: topic_key={topic_key}")
                # Return "I don't have that stored yet" - do NOT call Llama
                if thread_id:
                    try:
                        history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                        model_label = "Model: Memory"
                        response_text = "I don't have that stored yet."
                        history.append({
                            "id": str(uuid4()),
                            "role": "assistant",
                            "content": response_text,
                            "model": "Memory",
                            "model_label": model_label,
                            "provider": "memory",
                            "created_at": assistant_msg_created_at
                        })
                        memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                    except Exception as e:
                        logger.warning(f"Failed to save 'not found' answer to history: {e}")
                
                return {
                    "type": "assistant_message",
                    "content": "I don't have that stored yet.",
                    "meta": {"usedFacts": True, "factNotFound": True},
                    "model": "Memory",
                    "model_label": "Model: Memory",
                    "provider": "memory",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
    
    # 0. Get memory context if project_id is available
    memory_context = ""
    sources = []
    has_memory = False
    searched_memory = False  # Track if we attempted to search memory (even if no results)
    hits = []  # Initialize hits to empty list so it's always defined
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
                # Format hits into context string for GPT-5
                memory_context = librarian.format_hits_as_context(hits)
                has_memory = True
                logger.info(f"[MEMORY] Retrieved memory context for project_id={project_id}, chat_id={thread_id} ({len(hits)} hits)")
                logger.info(f"[MEMORY] Will pass Memory context to GPT-5: has_memory={has_memory}, hits_count={len(hits)}")
            else:
                logger.info(f"[MEMORY] Searched memory for project_id={project_id} but found no results")
                logger.info(f"[MEMORY] No Memory context to pass to GPT-5: has_memory={has_memory}, hits_count=0")
            
            # Also retrieve structured facts for detected topics (cross-chat)
            try:
                from server.services.facts import extract_topic_from_query
                topic_key = extract_topic_from_query(user_message)
                if topic_key:
                    facts = memory_client.get_facts(
                        project_id=project_id,
                        topic_key=topic_key,
                        chat_id=None  # Cross-chat: search all chats in project
                    )
                    if facts:
                        # Format facts as context for GPT-5
                        ranked_facts = [f for f in facts if f.get("kind") == "ranked"]
                        single_facts = [f for f in facts if f.get("kind") == "single"]
                        
                        facts_context_parts = []
                        if ranked_facts:
                            ranked_facts.sort(key=lambda f: f.get("rank", 0))
                            facts_context_parts.append(f"\n[STORED FACTS - {topic_key.replace('_', ' ').title()}]")
                            facts_context_parts.append("Ranked list (from all chats in this project):")
                            for f in ranked_facts:
                                facts_context_parts.append(f"  {f.get('rank', 0)}) {f.get('value')}")
                        
                        if single_facts:
                            if not facts_context_parts:
                                facts_context_parts.append(f"\n[STORED FACTS - {topic_key.replace('_', ' ').title()}]")
                            facts_context_parts.append("Preferences:")
                            for f in single_facts:
                                facts_context_parts.append(f"  - {f.get('value')}")
                        
                        if facts_context_parts:
                            facts_context = "\n".join(facts_context_parts)
                            if memory_context:
                                memory_context = f"{memory_context}\n{facts_context}"
                            else:
                                memory_context = facts_context
                            logger.info(f"[FACTS] Added {len(facts)} facts to GPT-5 context for topic_key={topic_key}")
            except Exception as e:
                logger.warning(f"Failed to retrieve facts for GPT-5 context: {e}", exc_info=True)
            
            # Convert Memory hits to structured Source objects for frontend
            if hits:
                # Get source display names for better titles
                from server.services.memory_service_client import get_memory_sources_for_project
                from server.services import projects_config  # noqa: F401  # imported for side-effects / future use
                source_map = {}
                try:
                    client = get_memory_client()
                    all_sources = client.get_sources()
                    source_map = {s.get("id"): s.get("display_name", s.get("id")) for s in all_sources}
                except Exception as source_error:
                    logger.debug(f"Failed to get source names: {source_error}")
                
                # Convert each MemoryHit to a Source object
                for idx, hit in enumerate(hits):
                    # Generate title from content or file path
                    title = "Memory Source"
                    if hit.file_path:
                        # Extract filename from path
                        import os
                        title = os.path.basename(hit.file_path) or hit.file_path
                    elif hit.content:
                        # Use first 60 chars of content as title
                        content_preview = hit.content.strip().split('\n')[0]
                        title = content_preview[:60] + "..." if len(content_preview) > 60 else content_preview
                    
                    # Get source display name if available
                    source_display_name = source_map.get(hit.source_id, hit.source_id)
                    if hit.file_path:
                        title = f"{source_display_name}: {title}"
                    
                    # Create description from content snippet (first 150 chars)
                    description = hit.content[:150] + "..." if len(hit.content) > 150 else hit.content
                    
                    # Build Source object
                    memory_source = {
                        "id": f"memory-{hit.source_id}-{idx}",
                        "title": title,
                        "description": description,
                        "sourceType": "memory",
                        "citationPrefix": "M",
                        "rank": idx,  # Rank within Memory group
                        "siteName": "Memory",
                        "meta": {
                            "chat_id": hit.chat_id,
                            "message_id": hit.message_id,
                            "message_uuid": hit.message_uuid,  # Stable UUID for deep-linking
                            "file_path": hit.file_path,
                            "source_id": hit.source_id,
                            "source_type": hit.source_type,
                            "role": hit.role,
                            "content": hit.content,  # Full content for reference
                        }
                    }
                    sources.append(memory_source)
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
        # 2a. Memory-only or GPT-5 chat (no Brave)
        # Always use GPT-5 - Memory is a tool, not a speaking model
        used_web = False
        used_memory = has_memory
        
        # Always route to GPT-5 (never GPT-5 Mini)
        logger.info(f"[MEMORY] Routing to GPT-5 with Memory context ({len(hits) if hits else 0} hits)")
        content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
            messages=messages,
            tools=tools,
            intent="general_chat",
            project_id=project_id
        )
        # Model label: "Memory" if memory was used, "GPT-5" otherwise
        # "Model: Memory" is preserved as a source label to indicate Memory-backed responses
        model_display = build_model_label(used_web=used_web, used_memory=used_memory, escalated=True)
        logger.info(f"[MODEL] model label = {model_display}")
        
        # Build model_label and created_at BEFORE the thread_id check (needed for return statement)
        model_label = f"Model: {model_display}"
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                from server.services.memory_service_client import get_memory_client
                
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                message_index = len(history)
                
                # Add user message with timestamp
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                user_msg = {
                    "id": str(uuid4()),
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at
                }
                # NOTE: Ranked lists are now stored in facts DB, not thread metadata
                history.append(user_msg)
                
                # Index user message into Memory Service for cross-chat search
                # NOTE: This is redundant since we index early (before memory search), but kept for safety
                # The early indexing ensures the message is available for immediate follow-up questions
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        user_message_id = f"{thread_id}-user-{message_index}"
                        logger.debug(f"[MEMORY] Re-indexing user message {user_message_id} for project {project_id} (already indexed early, this is redundant)")
                        success = memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=thread_id,
                            message_id=user_message_id,
                            role="user",
                            content=user_message,
                            timestamp=user_msg_created_at,
                            message_index=message_index
                        )
                        if success:
                            logger.debug(f"[MEMORY] ✅ Re-indexed user message {user_message_id} for project {project_id}")
                        else:
                            logger.warning(f"[MEMORY] ❌ Failed to re-index user message {user_message_id} for project {project_id} (Memory Service returned False)")
                    except Exception as e:
                        logger.warning(f"[MEMORY] ❌ Exception re-indexing user message: {e}", exc_info=True)
                else:
                    logger.warning(f"[MEMORY] ⚠️  Skipping user message indexing: project_id is None (thread_id={thread_id})")
                
                # Add assistant message with timestamp and model_label
                history.append({
                    "id": str(uuid4()),
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "model_label": model_label,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "usedMemory": used_memory},
                    "created_at": assistant_msg_created_at
                })
                memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                
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
                            timestamp=assistant_msg_created_at,
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
            "model_label": model_label,
            "provider": provider_id,
            "sources": sources if sources else None,
            "created_at": assistant_msg_created_at
        }
    
    # 2b. Use Brave Pro AI (Summary + Top Results) + GPT-5
    search_query = decision.query or user_message
    logger.info(f"Performing Brave Pro AI search (Summary + Top Results) for query: {search_query}")
    
    try:
        # Use Brave Pro AI: Get both search results and summary concurrently
        from concurrent.futures import ThreadPoolExecutor
        
        web_results = None
        web_summary = None
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            search_future = executor.submit(web_search.search_web, search_query, 5)
            summarize_future = executor.submit(web_search.brave_summarize, search_query)
            
            # Wait for search results (required)
            try:
                web_results = search_future.result(timeout=5)
            except Exception as e:
                logger.warning(f"Web search failed: {e}")
                web_results = []
            
            # Try to get summary (optional - don't fail if it times out)
            try:
                web_summary = summarize_future.result(timeout=15)
                if web_summary:
                    logger.info(f"[BRAVE] Pro AI summary generated ({len(web_summary.get('text', ''))} chars)")
            except Exception as e:
                logger.warning(f"Brave Pro AI summary failed or timed out: {e}")
                web_summary = None
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
        
        # Build model_label for this response
        model_label = f"Model: {model_display}"
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                history.append({
                    "id": str(uuid4()),
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at
                })
                history.append({
                    "id": str(uuid4()),
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "model_label": model_label,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "webSearchError": str(e)},
                    "created_at": assistant_msg_created_at
                })
                memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
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
            "model_label": model_label,
            "provider": provider_id,
            "sources": sources if sources else None,
            "created_at": assistant_msg_created_at
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
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        model_label = f"Model: {model_display}"
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                history.append({
                    "id": str(uuid4()),
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at
                })
                history.append({
                    "id": str(uuid4()),
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "model_label": model_label,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {"usedWebSearch": False, "webSearchEmpty": True},
                    "created_at": assistant_msg_created_at
                })
                memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
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
            "model_label": model_label,
            "provider": provider_id,
            "sources": sources if sources else None,
            "created_at": assistant_msg_created_at
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
    
    # Format web results for GPT-5 with Brave Pro AI summary and citation instructions
    web_results_text_parts = []
    
    # Add Brave Pro AI summary if available
    if web_summary and web_summary.get('text'):
        web_results_text_parts.append('=== Brave Pro AI Summary ===')
        web_results_text_parts.append(web_summary.get('text'))
        web_results_text_parts.append('')
    
    web_results_text_parts.append('You have access to the following up-to-date web sources.')
    web_results_text_parts.append('When you use a specific fact from a source, add a citation like [1] or [2] at the end of the relevant sentence.')
    web_results_text_parts.append('Use these sources only when needed; otherwise, answer normally.')
    web_results_text_parts.append('')
    
    for i, result in enumerate(web_results[:5], 1):
        url_str = f" ({result.get('url', '')})" if result.get('url') else ""
        web_results_text_parts.append(f"{i}. {result.get('title', 'No title')}{url_str}\n{result.get('snippet', '')}".strip())
    
    web_results_text = '\n'.join(web_results_text_parts)
    
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
            from server.services.memory_service_client import get_memory_client
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            
            # Add user message with timestamp
            from uuid import uuid4
            user_msg_created_at = datetime.now(timezone.utc).isoformat()
            user_msg = {
                "id": str(uuid4()),
                "role": "user",
                "content": user_message,
                "created_at": user_msg_created_at
            }
            # NOTE: Ranked lists are now stored in facts DB, not thread metadata
            history.append(user_msg)
            
            # Index user message into Memory Service for cross-chat search
            # NOTE: This is redundant since we index early (before memory search), but kept for safety
            # The early indexing ensures the message is available for immediate follow-up questions
            if project_id:
                try:
                    memory_client = get_memory_client()
                    user_message_id = f"{thread_id}-user-{message_index}"
                    logger.debug(f"[MEMORY] Re-indexing user message {user_message_id} for project {project_id} (already indexed early, this is redundant)")
                    success = memory_client.index_chat_message(
                        project_id=project_id,
                        chat_id=thread_id,
                        message_id=user_message_id,
                        role="user",
                        content=user_message,
                        timestamp=user_msg_created_at,
                        message_index=message_index
                    )
                    if success:
                        logger.debug(f"[MEMORY] ✅ Re-indexed user message {user_message_id} for project {project_id}")
                    else:
                        logger.warning(f"[MEMORY] ❌ Failed to re-index user message {user_message_id} for project {project_id} (Memory Service returned False)")
                except Exception as e:
                    logger.warning(f"[MEMORY] ❌ Exception re-indexing user message: {e}", exc_info=True)
            else:
                logger.warning(f"[MEMORY] ⚠️  Skipping user message indexing: project_id is None (thread_id={thread_id})")
            
            # Add assistant message with timestamp and model_label
            # Combine memory sources with web sources (web_sources are already Source objects)
            # sources contains Memory Source objects, web_sources contains Web Source objects
            all_sources = []
            if sources:
                all_sources.extend(sources)  # Memory sources
            if web_sources:
                all_sources.extend(web_sources)  # Web sources (already Source objects)
            
            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
            model_label = build_model_label(used_web=bool(web_sources), used_memory=has_memory, escalated=True)
            assistant_message = {
                "id": str(uuid4()),
                "role": "assistant",
                "content": content,
                "model": model_label.replace("Model: ", ""),  # Store without "Model: " prefix
                "model_label": model_label,
                "provider": provider_id,
                "sources": all_sources if all_sources else None,
                "meta": {
                    "usedWebSearch": True,
                    "webResultsPreview": web_results[:5]
                },
                "created_at": assistant_msg_created_at
            }
            history.append(assistant_message)
            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
            
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
                        timestamp=assistant_msg_created_at,
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
    
    # Combine memory sources with web sources (web_sources are already Source objects)
    # sources contains Memory Source objects, web_sources contains Web Source objects
    all_sources = []
    if sources:
        all_sources.extend(sources)  # Memory sources
    if web_sources:
        all_sources.extend(web_sources)  # Web sources (already Source objects)
    
    # Get created_at and model_label from saved message or generate
    assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
    model_label = build_model_label(used_web=bool(web_sources), used_memory=searched_memory, escalated=True)
    if thread_id:
        try:
            history = memory_store.load_thread_history(target_name, thread_id)
            for msg in reversed(history):
                if msg.get("role") == "assistant" and msg.get("created_at"):
                    assistant_msg_created_at = msg.get("created_at")
                    if msg.get("model_label"):
                        model_label = msg.get("model_label")
                    break
        except:
            pass
    
    return {
        "type": "assistant_message",
        "content": content,
        "meta": {
            "usedWebSearch": True,
            "usedMemory": has_memory,
            "webResultsPreview": web_results[:5]  # Top 5 for sources display
        },
        "model": model_label.replace("Model: ", ""),  # Return without "Model: " prefix for backward compatibility
        "model_label": model_label,
        "provider": provider_id,
        "sources": all_sources if all_sources else None,
        "created_at": assistant_msg_created_at
    }

