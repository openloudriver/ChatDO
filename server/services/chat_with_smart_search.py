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
    project_id: Optional[str] = None,
    files_actions: Optional[Dict[str, int]] = None
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
                project_id=project_id,
                files_actions=files_actions
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
    project_id: Optional[str] = None,
    files_actions: Optional[Dict[str, int]] = None
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
                    
                    # Note: Files(n) is now computed from final sources list (distinct cited files),
                    # not from tool calls. See count_distinct_file_sources() function.
                    
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


def count_distinct_file_sources(sources: List[Dict[str, Any]]) -> int:
    """
    Count distinct file sources from the final sources list.
    
    Files(n) represents the number of distinct file sources that appear as inline citations (M#).
    Distinct means unique by stable identity:
    - Prefer file_id if available
    - Otherwise (source_id, file_path) pair
    
    Args:
        sources: List of Source objects from the final response
        
    Returns:
        Count of distinct file sources (only those with meta.kind == "file")
    """
    if not sources:
        return 0
    
    distinct_files = set()
    for source in sources:
        meta = source.get("meta", {})
        kind = meta.get("kind")
        
        # Only count file sources
        if kind != "file":
            continue
        
        # Use file_id if available (most stable)
        file_id = meta.get("file_id")
        if file_id:
            distinct_files.add(f"file_id:{file_id}")
        else:
            # Fallback to (source_id, file_path) pair
            source_id = meta.get("source_id") or source.get("source_id")
            file_path = meta.get("file_path")
            if source_id and file_path:
                distinct_files.add(f"path:{source_id}:{file_path}")
    
    count = len(distinct_files)
    if count > 0:
        logger.info(f"[FILES] Counted {count} distinct file sources from citations: {sorted(distinct_files)}")
    return count


def build_model_label(
    facts_actions: Optional[dict] = None,
    files_actions: Optional[dict] = None,
    index_status: str = "P",
    escalated: bool = True,
    nano_router_used: bool = False,
    reasoning_required: bool = True,
    canonicalizer_used: bool = False,
    teacher_invoked: bool = False
) -> str:
    """
    Build model label with execution path using arrows (→).
    
    Format: GPT-5 Nano → Canonicalizer → [Teacher] → {Facts tokens} → {Files token} → Index-(P/F) → {GPT-5 if reasoning_required}
    Shows the actual execution path, not just what was used.
    
    Examples:
    - "GPT-5 Nano → Canonicalizer → Facts-S(3)" (write, no reasoning, no teacher)
    - "GPT-5 Nano → Canonicalizer → Teacher → Facts-S(1)" (write with teacher)
    - "GPT-5 Nano → Canonicalizer → Facts-R(2) → GPT-5" (read with reasoning)
    - "GPT-5 Nano → GPT-5" (chat only, no canonicalizer)
    
    Args:
        facts_actions: Dict with keys S, U, R, F (all integers >= 0, F is bool)
        files_actions: Dict with key R (integer >= 0)
        index_status: "P" (passed) or "F" (failed)
        escalated: Always True (kept for compatibility)
        nano_router_used: Whether Nano router was used (always True now)
        reasoning_required: Whether GPT-5 reasoning is required
        canonicalizer_used: Whether canonicalizer was invoked
        teacher_invoked: Whether teacher model was invoked
    
    Returns:
        Model label string (e.g., "GPT-5 Nano → Canonicalizer → Teacher → Facts-S(3)")
    """
    parts = ["GPT-5 Nano"]  # Always start with Nano router
    
    # Add Canonicalizer if used (only for Facts operations)
    if canonicalizer_used:
        parts.append("Canonicalizer")
        # Add Teacher if invoked
        if teacher_invoked:
            parts.append("Teacher")
    
    # 1. Facts tokens (order: S → U → R, only if count > 0)
    if facts_actions:
        s_count = facts_actions.get("S", 0)
        u_count = facts_actions.get("U", 0)
        r_count = facts_actions.get("R", 0)
        f_flag = facts_actions.get("F", False)
        
        # Check for Facts failure first (hard failure)
        if f_flag:
            parts.append("Facts-F")
        else:
            # Only show S/U/R if no failure
            if s_count > 0:
                parts.append(f"Facts-S({s_count})")
            if u_count > 0:
                parts.append(f"Facts-U({u_count})")
            if r_count > 0:
                parts.append(f"Facts-R({r_count})")
    
    # 2. Files token (only if R > 0)
    if files_actions:
        files_r = files_actions.get("R", 0)
        if files_r > 0:
            parts.append(f"Files({files_r})")
    
    # 3. Index token (always shown)
    parts.append(f"Index-{index_status}")
    
    # 4. GPT-5 reasoning (only if reasoning_required)
    if reasoning_required:
        parts.append("GPT-5")
    
    return " → ".join(parts)


def _is_write_intent(message: str) -> bool:
    """
    Lightweight heuristic to detect write-intent messages (fact-like).
    
    Returns True if message appears to be a fact write operation.
    """
    if not message:
        return False
    
    message_lower = message.lower().strip()
    
    # Write-intent patterns
    write_patterns = [
        "my favorite",  # "My favorite X is Y"
        "remember",     # "Remember that..."
        "my ",          # "My X is Y"
        "set ",         # "Set X to Y"
        "update ",      # "Update X to Y"
        "add ",         # "Add X to my favorites"
        "store ",       # "Store X"
        "save ",        # "Save X"
        "i like",       # "I like X"
        "i love",       # "I love X"
        "i prefer",    # "I prefer X"
        "i have",       # "I have X"
        "i am",         # "I am X"
        "i'm ",         # "I'm X"
        "i was",        # "I was X"
        "i live",       # "I live in X"
        "i work",       # "I work at X"
        "i study",      # "I study X"
        "i use",        # "I use X"
    ]
    
    # Check if message starts with any write pattern
    for pattern in write_patterns:
        if message_lower.startswith(pattern):
            return True
    
    # Check for "is" pattern: "X is Y" or "X are Y"
    if " is " in message_lower or " are " in message_lower:
        # Exclude question patterns
        if not message_lower.startswith(("what", "who", "where", "when", "why", "how", "which", "is ", "are ")):
            return True
    
    return False


async def chat_with_smart_search(
    user_message: str,
    target_name: str = "general",
    thread_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    project_id: Optional[str] = None,
    client_message_uuid: Optional[str] = None  # Client-generated UUID for user message
) -> Dict[str, Any]:
    """
    Chat with smart search and Facts persistence.
    
    Facts DB contract: project_id must be UUID, never project name/slug.
    This should be resolved at the entry point (WS handler, HTTP handler) before calling this function.
    
    NANO-FIRST ARCHITECTURE: Every message passes through GPT-5 Nano router first.
    """
    # ============================================================================
    # PHASE 0: NANO ROUTER (Control Plane) - MANDATORY FIRST STEP
    # ============================================================================
    # Load conversation history for Nano router context
    if conversation_history is None:
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                conversation_history = []
                for msg in history:
                    if msg.get("role") in ["user", "assistant", "system"]:
                        if msg.get("type") and not msg.get("content"):
                            continue
                        conversation_history.append({
                            "role": msg.get("role"),
                            "content": msg.get("content", "")
                        })
            except Exception as e:
                logger.warning(f"Failed to load conversation history for Nano router: {e}")
                conversation_history = []
        else:
            conversation_history = []
    
    # Call Nano router - MANDATORY FIRST STEP
    routing_plan = None
    nano_router_used = False
    try:
        from server.services.nano_router import route_with_nano, NanoRouterError
        from server.contracts.routing_plan import RoutingPlan
        routing_plan = await route_with_nano(user_message, conversation_history)
        nano_router_used = True
        logger.info(
            f"[NANO-ROUTER] ✅ Routing plan: content_plane={routing_plan.content_plane}, "
            f"operation={routing_plan.operation}, reasoning_required={routing_plan.reasoning_required}, "
            f"confidence={routing_plan.confidence}, why={routing_plan.why}"
        )
    except Exception as e:
        logger.error(f"[NANO-ROUTER] ❌ Failed to route with Nano: {e}", exc_info=True)
        # If Nano router fails, we must fail hard - no fallback
        # Create a minimal routing plan for error handling
        from server.contracts.routing_plan import RoutingPlan
        routing_plan = RoutingPlan(
            content_plane="chat",
            operation="none",
            reasoning_required=True,
            confidence=0.0,
            why=f"Nano router failed: {e}"
        )
    
    # Initialize action tracking at the very beginning
    facts_actions = {"S": 0, "U": 0, "R": 0, "F": False}  # Store, Update, Retrieve, Failure
    files_actions = {"R": 0}  # Files retrieved count
    index_status = "P"  # "P" (passed) or "F" (failed)
    memory_failure = False
    
    # Initialize Facts gate tracking
    facts_gate_entered = False
    facts_gate_reason = None
    facts_provider = "nano"  # Now using Nano for Facts
    
    # Validate project_id is UUID if provided (should already be resolved at entry point)
    if project_id:
        from server.services.projects.project_resolver import validate_project_uuid
        try:
            validate_project_uuid(project_id)
        except ValueError as e:
            logger.error(f"[CHAT] Invalid project_id format: {e}")
            # Don't fail completely, but log error - validation will catch at Facts persistence
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
    # Phase 1: Synchronous Facts Persistence (does NOT depend on Memory Service)
    # Store facts immediately and deterministically, get actual counts from DB writes
    current_message_uuid = client_message_uuid  # Initialize with client-provided UUID
    
    # Initialize query_plan early (before Facts persistence) so it can be used in ambiguity check
    # CRITICAL: Must be initialized at function scope before any conditional access
    # Type: Optional[FactsQueryPlan] - will be None until query planning succeeds
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from server.contracts.facts_ops import FactsQueryPlan
    query_plan: Optional['FactsQueryPlan'] = None
    
    # CRITICAL: Initialize is_write_intent early so it's available for all early-return paths
    # This must be set before any conditional checks that reference it
    is_write_intent = _is_write_intent(user_message)
    
    # CRITICAL: Facts persistence requires both thread_id and project_id
    # HARD-FAIL if either is missing - do not silently skip and fall through to Index/GPT-5
    facts_skip_reason = None
    if not thread_id:
        facts_skip_reason = "thread_id is missing"
        logger.error(f"[FACTS] ❌ HARD-FAIL: {facts_skip_reason} (project_id={'provided' if project_id else 'missing'})")
    if not project_id:
        reason = "project_id is missing"
        if facts_skip_reason:
            facts_skip_reason = f"{facts_skip_reason}; {reason}"
        else:
            facts_skip_reason = reason
        logger.error(f"[FACTS] ❌ HARD-FAIL: {reason} (thread_id={'provided' if thread_id else 'missing'})")
    
    # Validate project_id is a valid UUID if provided
    if project_id:
        from server.services.projects.project_resolver import validate_project_uuid
        try:
            validate_project_uuid(project_id)
        except ValueError as e:
            reason = f"project_id is not a valid UUID: {e}"
            if facts_skip_reason:
                facts_skip_reason = f"{facts_skip_reason}; {reason}"
            else:
                facts_skip_reason = reason
            logger.error(f"[FACTS] ❌ HARD-FAIL: {reason}")
    
    # HARD-FAIL: Return Facts-F error if IDs are missing/invalid
    if facts_skip_reason:
        facts_actions["F"] = True
        facts_gate_entered = False
        facts_gate_reason = f"gate_skipped: {facts_skip_reason}"
        
        # CRITICAL: If this is a write-intent message and Facts gate was skipped,
        # we MUST return Facts-F (no fallthrough to Index/GPT-5)
        if is_write_intent:
            error_message = (
                f"Facts unavailable: {facts_skip_reason}. "
                "Please ensure you have selected a project and are in a valid conversation."
            )
            logger.error(f"[FACTS] WRITE_INTENT_BYPASS_PREVENTED: write-intent message blocked, returning Facts-F (reason: {facts_skip_reason})")
            return {
                "type": "assistant_message",
                "content": error_message,
                "meta": {
                    "fastPath": "facts_error",
                    "facts_error": True,
                    "facts_skip_reason": facts_skip_reason,
                    "facts_actions": {"S": 0, "U": 0, "R": 0, "F": True},
                    "facts_provider": facts_provider,
                    "project_uuid": project_id,
                    "thread_id": thread_id,
                    "facts_gate_entered": facts_gate_entered,
                    "facts_gate_reason": facts_gate_reason,
                    "write_intent_detected": True
                },
                "sources": [],
                "model": "Facts-F",
                "model_label": "Model: Facts-F",
                "provider": "facts",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            # For non-write-intent messages, still return Facts-F but log it
            error_message = (
                f"Facts unavailable: {facts_skip_reason}. "
                "Please ensure you have selected a project and are in a valid conversation."
            )
            logger.error(f"[FACTS] Returning hard-fail response: {error_message}")
            return {
                "type": "assistant_message",
                "content": error_message,
                "meta": {
                    "fastPath": "facts_error",
                    "facts_error": True,
                    "facts_skip_reason": facts_skip_reason,
                    "facts_actions": {"S": 0, "U": 0, "R": 0, "F": True},
                    "facts_provider": facts_provider,
                    "project_uuid": project_id,
                    "thread_id": thread_id,
                    "facts_gate_entered": facts_gate_entered,
                    "facts_gate_reason": facts_gate_reason,
                    "write_intent_detected": False
                },
                "sources": [],
                "model": "Facts-F",
                "model_label": "Model: Facts-F",
                "provider": "facts",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
    
    # Both thread_id and project_id are valid - proceed with Facts persistence
    # BUT: Only if Nano router says "facts_write"
    logger.info(f"[FACTS] ✅ Facts persistence enabled: thread_id={thread_id}, project_id={project_id}")
    
    # ENFORCE NANO ROUTING: Only execute Facts-S/U if routing plan says facts/write
    # Log routing plan for debugging
    if routing_plan:
        logger.info(
            f"[NANO-ROUTING] Routing plan check: content_plane={routing_plan.content_plane}, "
            f"operation={routing_plan.operation}, reasoning_required={routing_plan.reasoning_required}, "
            f"confidence={routing_plan.confidence}, why={routing_plan.why}, "
            f"thread_id={thread_id}, project_id={project_id}"
        )
        if routing_plan.facts_write_candidate:
            logger.info(
                f"[NANO-ROUTING] Facts write candidate: topic={routing_plan.facts_write_candidate.topic}, "
                f"value={routing_plan.facts_write_candidate.value}, rank_ordered={routing_plan.facts_write_candidate.rank_ordered}"
            )
        # CRITICAL: If user message contains "My favorite" but router didn't route to facts/write, log error
        user_msg_lower = user_message.lower()
        if "my favorite" in user_msg_lower and ("is" in user_msg_lower or "are" in user_msg_lower):
            if routing_plan.content_plane != "facts" or routing_plan.operation != "write":
                logger.error(
                    f"[NANO-ROUTING] ⚠️ CRITICAL: User message contains 'My favorite' pattern but router "
                    f"returned content_plane={routing_plan.content_plane}, operation={routing_plan.operation}. "
                    f"Message: {user_message[:100]}"
                )
    else:
        logger.warning("[NANO-ROUTING] routing_plan is None - cannot execute Facts write")
    
    if thread_id and project_id and routing_plan and routing_plan.content_plane == "facts" and routing_plan.operation == "write":
        try:
            from server.services.facts_persistence import persist_facts_synchronously
            from datetime import datetime as dt
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            user_msg_created_at = datetime.now(timezone.utc)
            user_message_id = f"{thread_id}-user-{message_index}"
            
            # Use client_message_uuid if provided, otherwise will be generated
            message_uuid_to_use = client_message_uuid
            
            # Persist facts synchronously (does NOT require Memory Service)
            # NEW: Uses routing plan candidate when available to avoid double Nano calls
            # Falls back to GPT-5 Nano Facts extractor only if candidate not available
            # Note: is_write_intent is already set at function start
            persist_result = await persist_facts_synchronously(
                project_id=project_id,
                message_content=user_message,
                role="user",
                message_uuid=message_uuid_to_use,  # Use client-provided UUID
                chat_id=thread_id,
                message_id=user_message_id,
                timestamp=user_msg_created_at,
                message_index=message_index,
                retrieved_facts=None,  # Will be enhanced later to pass retrieved facts for schema-hint resolution
                write_intent_detected=is_write_intent,  # Pass write-intent flag for enhanced diagnostics
                routing_plan_candidate=routing_plan.facts_write_candidate if routing_plan else None
            )
            
            # Extract values from result dataclass
            store_count = persist_result.store_count
            update_count = persist_result.update_count
            stored_fact_keys = persist_result.stored_fact_keys
            message_uuid = persist_result.message_uuid
            ambiguous_topics = persist_result.ambiguous_topics
            canonicalization_result = persist_result.canonicalization_result
            rank_assignment_source = persist_result.rank_assignment_source
            duplicate_blocked = persist_result.duplicate_blocked
            rank_mutations = persist_result.rank_mutations
            
            # Check for Facts LLM failure (negative counts indicate error)
            if store_count < 0 or update_count < 0:
                logger.error(f"[FACTS] Facts LLM failed - returning hard failure")
                facts_actions["F"] = True  # Set failure flag
                facts_actions["S"] = 0
                facts_actions["U"] = 0
                facts_gate_entered = True
                facts_gate_reason = "facts_llm_failed"
                
                # Get detailed error information from the exception if available
                # The error details are logged in facts_persistence.py, but we need to
                # provide a user-friendly message here
                from server.services.facts_llm.client import (
                    FactsLLMTimeoutError,
                    FactsLLMUnavailableError,
                    FactsLLMInvalidJSONError
                )
                
                # Try to get the last error from the exception context
                # For now, use a generic message - the actual error type is logged
                error_message = (
                    f"Facts system failed: The Facts LLM (GPT-5 Nano) encountered an error. "
                    f"Facts were not updated. Check server logs for details."
                )
                
                # CRITICAL: If this is a write-intent message, we MUST return Facts-F (no fallthrough)
                if is_write_intent:
                    logger.error(f"[FACTS] WRITE_INTENT_BYPASS_PREVENTED: write-intent message blocked after Facts LLM failure, returning Facts-F")
                
                return {
                    "type": "assistant_message",
                    "content": error_message,
                    "model": "Facts-F",
                    "model_label": "Model: Facts-F",
                    "provider": "facts",
                    "meta": {
                        "fastPath": "facts_error",
                        "facts_error": True,
                        "facts_actions": {"S": 0, "U": 0, "R": 0, "F": True},
                        "facts_provider": facts_provider,
                        "project_uuid": project_id,
                        "thread_id": thread_id,
                        "facts_gate_entered": facts_gate_entered,
                        "facts_gate_reason": facts_gate_reason,
                        "write_intent_detected": is_write_intent
                    },
                    "sources": [],
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            
            # Check for topic ambiguity or ranked-list protection - if present, return fast-path clarification response
            # BUT: Only block on ambiguity for WRITE operations, not retrieval queries
            # For retrieval queries, ambiguity should be ignored (we'll try to retrieve what the user asked for)
            if ambiguous_topics:
                # Check if this is a ranked-list protection message (single message starting with "You already have")
                is_ranked_list_protection = (
                    len(ambiguous_topics) == 1 and 
                    ambiguous_topics[0].startswith("You already have a ranked list")
                )
                
                # Use the query plan we already created (if available) to check if this is a retrieval query
                # If we don't have a query plan yet, check now
                is_retrieval_query_check = False
                # query_plan is initialized at line 547, so it's always in scope here
                # Check if it was set to a non-None value (it starts as None)
                if query_plan is not None:
                    is_retrieval_query_check = query_plan.intent in ["facts_get_ranked_list", "facts_get_by_prefix", "facts_get_exact_key"]
                else:
                    # Try to plan the query to determine if it's a retrieval query
                    try:
                        from server.services.facts_query_planner import plan_facts_query
                        try:
                            test_plan = await plan_facts_query(user_message)
                            is_retrieval_query_check = test_plan.intent in ["facts_get_ranked_list", "facts_get_by_prefix", "facts_get_exact_key"]
                            # Store the plan for later use
                            query_plan = test_plan
                        except Exception:
                            pass
                    except Exception:
                        pass
                
                # Only return clarification for WRITE operations
                # For retrieval queries, ignore ambiguity and proceed (will return empty if topic doesn't exist)
                if not is_retrieval_query_check:
                    if is_ranked_list_protection:
                        # Ranked-list protection message - return it directly
                        logger.info(f"[MEMORY] Ranked-list protection triggered: {ambiguous_topics[0]}")
                        clarification_message = ambiguous_topics[0]
                        fast_path_type = "ranked_list_protection"
                    else:
                        # Topic ambiguity - format candidate topics for user-friendly display
                        logger.info(f"[MEMORY] Topic ambiguity detected: {ambiguous_topics} - returning clarification")
                        topic_display = " / ".join(ambiguous_topics)
                        clarification_message = (
                            f"Which favorites list is this for? ({topic_display})\n\n"
                            f"Please specify the topic (e.g., 'crypto', 'colors', 'candies') so I can update the correct list."
                        )
                        fast_path_type = "topic_ambiguity"
                    
                    # Return fast-path response with zero fact counts
                    return {
                        "response": clarification_message,
                        "model": "Facts",
                        "provider": "facts",
                        "meta": {
                            "fastPath": fast_path_type,
                            "ambiguous_topics": ambiguous_topics,
                            "facts_actions": {"S": 0, "U": 0, "R": 0, "F": False}
                        },
                        "sources": []
                    }
                else:
                    # This is a retrieval query - ignore ambiguity and proceed
                    logger.info(f"[MEMORY] Topic ambiguity detected but this is a retrieval query - ignoring ambiguity and proceeding")
                    # Clear ambiguous_topics so we proceed with retrieval
                    ambiguous_topics = None
            
            # Set counts from actual DB writes (truthful, not optimistic)
            facts_actions["S"] = store_count
            facts_actions["U"] = update_count
            
            # Log Facts-S/U results for debugging
            if is_write_intent:
                logger.info(
                    f"[FACTS] Write-intent message Facts-S/U results: "
                    f"store_count={store_count}, update_count={update_count}, "
                    f"stored_keys={stored_fact_keys[:5] if stored_fact_keys else []} "
                    f"(showing first 5), message_uuid={message_uuid}"
                )
                if store_count == 0 and update_count == 0:
                    logger.warning(
                        f"[FACTS] ⚠️ Write-intent message but Facts-S/U returned 0 counts. "
                        f"This may indicate GPT-5 Nano didn't extract facts or an error occurred."
                    )
            
            # Use message_uuid for fact exclusion (needed for Facts-R)
            if message_uuid:
                current_message_uuid = message_uuid
                logger.info(f"[MEMORY] Got message_uuid={current_message_uuid} for fact exclusion")
            
            logger.info(
                f"[MEMORY] ✅ Facts persisted: S={store_count} U={update_count} "
                f"keys={stored_fact_keys} (message_uuid={current_message_uuid})"
            )
            
            # STRICT ROUTING INVARIANT: If Facts-S/U succeeded, return confirmation immediately
            # Do NOT fall through to GPT-5 or show "I don't have that stored yet"
            # NOTE: Even if the query could be interpreted as a retrieval query, if Facts-S/U
            # succeeded, we return the confirmation. The user can ask again to retrieve.
            # Also check for duplicate_blocked - this is a successful operation (duplicate prevented)
            if store_count > 0 or update_count > 0 or duplicate_blocked:
                    # This is a write operation (Facts-S/U), return confirmation immediately
                    # Format confirmation message from stored facts
                    # Query DB to get actual values for the stored fact keys
                    from memory_service.memory_dashboard import db
                    
                    confirmation_parts = []
                    
                    # Group facts by topic for ranked lists
                    ranked_lists = {}
                    single_facts = []
                    
                    # Query DB for current values of stored fact keys
                    fact_values = {}
                    if stored_fact_keys and project_id:
                        try:
                            # Get current facts for these keys
                            for fact_key in stored_fact_keys:
                                fact = db.get_current_fact(
                                    project_id=project_id,
                                    fact_key=fact_key
                                )
                                if fact:
                                    fact_values[fact_key] = fact.get("value_text", "")
                        except Exception as e:
                            logger.warning(f"Failed to query fact values for confirmation: {e}")
                    
                    for fact_key in stored_fact_keys:
                        # Check if it's a ranked list key (user.favorites.<topic>.<rank>)
                        import re
                        match = re.match(r'^user\.favorites\.(.+)\.(\d+)$', fact_key)
                        if match:
                            topic = match.group(1)
                            rank = int(match.group(2))
                            value = fact_values.get(fact_key, "")
                            if topic not in ranked_lists:
                                ranked_lists[topic] = []
                            ranked_lists[topic].append((rank, value))
                        else:
                            value = fact_values.get(fact_key, "")
                            single_facts.append((fact_key, value))
                    
                    # Handle duplicate blocking messages
                    duplicate_messages = []
                    if duplicate_blocked:
                        for value, info in duplicate_blocked.items():
                            existing_rank = info.get("existing_rank")
                            topic = info.get("topic", "item")
                            duplicate_messages.append(f"{value} is already in your favorites at #{existing_rank}.")
                    
                    # Handle rank mutation messages (MOVE, INSERT, NO-OP, APPEND)
                    mutation_messages = []
                    if rank_mutations:
                        for fact_key, mutation_info in rank_mutations.items():
                            action = mutation_info.get("action")
                            value = mutation_info.get("value", "")
                            new_rank = mutation_info.get("new_rank")
                            old_rank = mutation_info.get("old_rank")
                            topic = mutation_info.get("topic", "item")
                            
                            if action == "move":
                                if old_rank is not None:
                                    mutation_messages.append(f"Moved {value} to #{new_rank} (was #{old_rank}).")
                                else:
                                    mutation_messages.append(f"Moved {value} to #{new_rank}.")
                            elif action == "insert":
                                mutation_messages.append(f"Inserted {value} at #{new_rank}.")
                            elif action == "noop":
                                mutation_messages.append(f"{value} is already your #{new_rank} favorite {topic}.")
                            elif action == "append":
                                mutation_messages.append(f"Added {value} as #{new_rank}.")
                    
                    # Format ranked lists
                    for topic, items in ranked_lists.items():
                        items.sort(key=lambda x: x[0])  # Sort by rank
                        values = [v for _, v in items if v]  # Extract values, filter empty
                        if values:
                            confirmation_parts.append(f"favorite {topic} = [{', '.join(values)}]")
                    
                    # Format single facts
                    for fact_key, value in single_facts:
                        # Extract readable key name
                        key_name = fact_key.split('.')[-1] if '.' in fact_key else fact_key
                        if value:
                            confirmation_parts.append(f"{key_name} = {value}")
                        else:
                            confirmation_parts.append(f"{key_name}")
                    
                    # Build confirmation message
                    # Priority: rank mutations > regular confirmations > duplicates
                    if mutation_messages:
                        # Rank mutations take precedence - they're more specific
                        confirmation_text = " ".join(mutation_messages)
                        # Append duplicates if any
                        if duplicate_messages:
                            confirmation_text += " " + " ".join(duplicate_messages)
                    elif confirmation_parts:
                        confirmation_text = "Saved: " + ", ".join(confirmation_parts)
                        # If we have duplicates, append them
                        if duplicate_messages:
                            confirmation_text += " " + " ".join(duplicate_messages)
                    elif duplicate_messages:
                        # Only duplicate messages, no new facts stored
                        confirmation_text = " ".join(duplicate_messages)
                    else:
                        # Fallback if we can't format properly
                        if store_count > 0:
                            confirmation_text = f"Saved {store_count} fact(s)."
                        elif update_count > 0:
                            confirmation_text = f"Updated {update_count} fact(s)."
                        else:
                            confirmation_text = "Saved."
                    
                    # Log response path
                    logger.info(
                        f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=WRITE_FASTPATH "
                        f"store_count={store_count} update_count={update_count} "
                        f"message_uuid={current_message_uuid}"
                    )
                    
                    # Save to history
                    if thread_id:
                        try:
                            history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                            message_index = len(history)
                            
                            # Add user message to history FIRST (before assistant message)
                            user_msg_created_at = datetime.now(timezone.utc).isoformat()
                            user_message_id = f"{thread_id}-user-{message_index}"
                            user_msg = {
                                "id": user_message_id,
                                "role": "user",
                                "content": user_message,
                                "created_at": user_msg_created_at,
                                "uuid": current_message_uuid  # Include UUID for rehydration
                            }
                            history.append(user_msg)
                            
                            # Now add assistant message
                            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                            assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                            # Extract canonicalization info for model label
                            canonicalizer_used_hist = canonicalization_result is not None
                            teacher_invoked_hist = canonicalization_result.teacher_invoked if canonicalization_result else False
                            model_label_hist = build_model_label(
                                facts_actions=facts_actions,
                                files_actions=files_actions,
                                index_status=index_status,
                                escalated=False,
                                nano_router_used=nano_router_used,
                                reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                                canonicalizer_used=canonicalizer_used_hist,
                                teacher_invoked=teacher_invoked_hist
                            )
                            history.append({
                                "id": assistant_message_id,
                                "role": "assistant",
                                "content": confirmation_text,
                                "model": model_label_hist,
                                "model_label": f"Model: {model_label_hist}",
                                "provider": "facts",
                                "created_at": assistant_msg_created_at
                            })
                            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                        except Exception as e:
                            logger.warning(f"Failed to save Facts-S/U confirmation to history: {e}")
                    
                    # Return fast-path Facts-S/U confirmation (no GPT-5)
                    # Extract canonicalization info for telemetry and model label
                    canonicalizer_used = canonicalization_result is not None
                    teacher_invoked = canonicalization_result.teacher_invoked if canonicalization_result else False
                    
                    model_label_text = build_model_label(
                        facts_actions=facts_actions,
                        files_actions=files_actions,
                        index_status=index_status,
                        escalated=False,
                        nano_router_used=nano_router_used,
                        reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                        canonicalizer_used=canonicalizer_used,
                        teacher_invoked=teacher_invoked
                    )
                    return {
                        "type": "assistant_message",
                        "content": confirmation_text,
                        "meta": {
                            "usedFacts": True,
                            "fastPath": "facts_write_confirmation",
                            "facts_actions": facts_actions,
                            "files_actions": files_actions,
                            "index_status": index_status,
                            "facts_provider": facts_provider,
                            "project_uuid": project_id,
                            "thread_id": thread_id,
                            "facts_gate_entered": facts_gate_entered,
                            "facts_gate_reason": facts_gate_reason,
                            "write_intent_detected": is_write_intent,
                            # Canonicalization telemetry
                            "canonical_topic": canonicalization_result.canonical_topic if canonicalization_result else None,
                            "canonical_confidence": canonicalization_result.confidence if canonicalization_result else None,
                            "teacher_invoked": teacher_invoked,
                            "alias_source": canonicalization_result.source if canonicalization_result else None,
                            "rank_assignment_source": rank_assignment_source,  # Dict: fact_key -> "explicit" | "atomic_append"
                            "duplicate_blocked": duplicate_blocked,  # Dict: value -> {"value": str, "existing_rank": int, "topic": str, "list_key": str}
                            "rank_mutations": rank_mutations,  # Dict: fact_key -> {"action": str, "old_rank": int|None, "new_rank": int, "value": str, "topic": str}
                            "nano_routing_plan": {
                                "content_plane": routing_plan.content_plane if routing_plan else None,
                                "operation": routing_plan.operation if routing_plan else None,
                                "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                                "confidence": routing_plan.confidence if routing_plan else None
                            },
                            "nano_router_used": nano_router_used
                        },
                        "sources": [],
                        "model": model_label_text,
                        "model_label": f"Model: {model_label_text}",
                        "provider": "facts",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                # Facts-S/U confirmation returned - do not continue to Facts-R section
            else:
                # Routing plan said facts/write but Facts-S/U returned 0 counts
                # Check if this was due to duplicate blocking (which is a success case)
                if duplicate_blocked:
                    # Duplicate was blocked - this is a success, return duplicate message
                    facts_actions["S"] = 0
                    facts_actions["U"] = 0
                    facts_gate_entered = True
                    facts_gate_reason = "duplicate_blocked"
                    
                    # Build duplicate confirmation message
                    duplicate_messages = []
                    for value, info in duplicate_blocked.items():
                        existing_rank = info.get("existing_rank")
                        duplicate_messages.append(f"'{info['value']}' is already in your favorites at #{existing_rank}.")
                    confirmation_text = " ".join(duplicate_messages)
                    
                    # Save user message to history
                    if thread_id and not any(m.get("uuid") == current_message_uuid for m in history):
                        history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                        message_index = len(history)
                        user_msg_created_at = datetime.now(timezone.utc).isoformat()
                        user_message_id = f"{thread_id}-user-{message_index}"
                        user_msg = {
                            "id": user_message_id,
                            "role": "user",
                            "content": user_message,
                            "created_at": user_msg_created_at,
                            "uuid": current_message_uuid
                        }
                        history.append(user_msg)
                        
                        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                        assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                        canonicalizer_used_hist = canonicalization_result is not None
                        teacher_invoked_hist = canonicalization_result.teacher_invoked if canonicalization_result else False
                        model_label_hist = build_model_label(
                            facts_actions=facts_actions,
                            files_actions=files_actions,
                            index_status=index_status,
                            escalated=False,
                            nano_router_used=nano_router_used,
                            reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                            canonicalizer_used=canonicalizer_used_hist,
                            teacher_invoked=teacher_invoked_hist
                        )
                        history.append({
                            "id": assistant_message_id,
                            "role": "assistant",
                            "content": confirmation_text,
                            "model": model_label_hist,
                            "model_label": f"Model: {model_label_hist}",
                            "provider": "facts",
                            "created_at": assistant_msg_created_at
                        })
                        memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                    
                    # Return duplicate confirmation
                    canonicalizer_used = canonicalization_result is not None
                    teacher_invoked = canonicalization_result.teacher_invoked if canonicalization_result else False
                    model_label_text = build_model_label(
                        facts_actions=facts_actions,
                        files_actions=files_actions,
                        index_status=index_status,
                        escalated=False,
                        nano_router_used=nano_router_used,
                        reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                        canonicalizer_used=canonicalizer_used,
                        teacher_invoked=teacher_invoked
                    )
                    
                    return {
                        "type": "assistant_message",
                        "content": confirmation_text,
                        "meta": {
                            "usedFacts": True,
                            "fastPath": "facts_duplicate_blocked",
                            "facts_actions": facts_actions,
                            "files_actions": files_actions,
                            "index_status": index_status,
                            "facts_provider": facts_provider,
                            "project_uuid": project_id,
                            "thread_id": thread_id,
                            "facts_gate_entered": facts_gate_entered,
                            "facts_gate_reason": facts_gate_reason,
                            "write_intent_detected": is_write_intent,
                            "canonical_topic": canonicalization_result.canonical_topic if canonicalization_result else None,
                            "canonical_confidence": canonicalization_result.confidence if canonicalization_result else None,
                            "teacher_invoked": teacher_invoked,
                            "alias_source": canonicalization_result.source if canonicalization_result else None,
                            "rank_assignment_source": rank_assignment_source,
                            "duplicate_blocked": duplicate_blocked,
                            "nano_routing_plan": {
                                "content_plane": routing_plan.content_plane if routing_plan else None,
                                "operation": routing_plan.operation if routing_plan else None,
                                "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                                "confidence": routing_plan.confidence if routing_plan else None
                            },
                            "nano_router_used": nano_router_used
                        },
                        "sources": [],
                        "model": model_label_text,
                        "model_label": f"Model: {model_label_text}",
                        "provider": "facts",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                
                # Routing plan said facts/write but Facts-S/U returned 0 counts
                # Check for clarification or duplicate cases before returning Facts-F
                if routing_plan and routing_plan.content_plane == "facts" and routing_plan.operation == "write":
                    logger.info(
                        f"[FACTS-E2E] RESPONSE: routing_plan=facts/write store_count={store_count} "
                        f"update_count={update_count} duplicate_blocked={bool(duplicate_blocked)} "
                        f"ambiguous_topics={bool(ambiguous_topics)} message_uuid={current_message_uuid}"
                    )
                    
                    # Check for clarification needed
                    if ambiguous_topics:
                        # Already handled above, but log for completeness
                        logger.info(
                            f"[FACTS-E2E] RESPONSE: returned clarification message "
                            f"message_uuid={current_message_uuid}"
                        )
                        # Return was already handled above
                        return  # This shouldn't be reached, but just in case
                    
                    # Check if this looks like a write intent that failed to parse
                    # Detect strong preference patterns even if router didn't catch them
                    import re
                    preference_patterns = [
                        r'my\s+favorite\s+\w+(?:\s+\w+)*\s+(?:are|is)\s+',
                        r'my\s+favorites\s+are\s+',
                    ]
                    has_preference_pattern = any(re.search(pattern, user_message.lower()) for pattern in preference_patterns)
                    
                    if has_preference_pattern and not routing_plan.content_plane == "facts":
                        logger.warning(
                            f"[FACTS-E2E] RESPONSE: router regression detected - message has preference pattern "
                            f"but router said {routing_plan.content_plane}/{routing_plan.operation} "
                            f"message_uuid={current_message_uuid}"
                        )
                    
                    # If we have duplicates, that's already handled above
                    # Otherwise, return Facts-F only if we truly have no write intent
                    logger.warning(
                        f"[FACTS] ⚠️ Routing plan said facts/write but Facts-S/U returned 0 counts. "
                        f"Returning Facts-F instead of falling through to Index/GPT-5."
                    )
                    facts_actions["F"] = True
                    logger.info(
                        f"[FACTS-E2E] RESPONSE: returned Facts-F message_uuid={current_message_uuid}"
                    )
                    # Extract canonicalization info if available (may be None on failure)
                    canonicalizer_used_f = canonicalization_result is not None
                    teacher_invoked_f = canonicalization_result.teacher_invoked if canonicalization_result else False
                    model_label_text = build_model_label(
                        facts_actions=facts_actions,
                        files_actions=files_actions,
                        index_status=index_status,
                        escalated=False,
                        nano_router_used=nano_router_used,
                        reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                        canonicalizer_used=canonicalizer_used_f,
                        teacher_invoked=teacher_invoked_f
                    )
                    return {
                        "type": "assistant_message",
                        "content": "I couldn't extract any facts from that message. Please try rephrasing.",
                        "meta": {
                            "usedFacts": True,
                            "fastPath": "facts_error",
                            "facts_error": True,
                            "facts_actions": facts_actions,
                            "files_actions": files_actions,
                            "index_status": index_status,
                            "facts_provider": facts_provider,
                            "project_uuid": project_id,
                            "thread_id": thread_id,
                            "nano_routing_plan": {
                                "content_plane": routing_plan.content_plane if routing_plan else None,
                                "operation": routing_plan.operation if routing_plan else None,
                                "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                                "confidence": routing_plan.confidence if routing_plan else None
                            },
                            "nano_router_used": nano_router_used,
                            # Canonicalization telemetry (may be None on failure)
                            "canonical_topic": canonicalization_result.canonical_topic if canonicalization_result else None,
                            "canonical_confidence": canonicalization_result.confidence if canonicalization_result else None,
                            "teacher_invoked": teacher_invoked_f,
                            "alias_source": canonicalization_result.source if canonicalization_result else None,
                            "rank_assignment_source": None  # No facts stored, so no rank assignment
                        },
                        "sources": [],
                        "model": model_label_text,
                        "model_label": f"Model: {model_label_text}",
                        "provider": "facts",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
            
        except Exception as e:
            logger.error(f"[MEMORY] ❌ Exception during synchronous fact persistence: {e}", exc_info=True)
            # Facts persistence failure doesn't block the response, but counts remain 0
            # If routing plan said facts/write, return Facts-F instead of falling through
            if routing_plan and routing_plan.content_plane == "facts" and routing_plan.operation == "write":
                logger.warning(
                    f"[FACTS] ⚠️ Exception during Facts-S/U but routing plan said facts/write. "
                    f"Returning Facts-F instead of falling through to Index/GPT-5."
                )
                facts_actions["F"] = True
                model_label_text = build_model_label(
                    facts_actions=facts_actions,
                    files_actions=files_actions,
                    index_status=index_status,
                    escalated=False,
                    nano_router_used=nano_router_used,
                    reasoning_required=routing_plan.reasoning_required if routing_plan else True
                )
                return {
                    "type": "assistant_message",
                    "content": f"I encountered an error while trying to save that: {str(e)}",
                    "meta": {
                        "usedFacts": True,
                        "fastPath": "facts_error",
                        "facts_error": True,
                        "facts_actions": facts_actions,
                        "files_actions": files_actions,
                        "index_status": index_status,
                        "facts_provider": facts_provider,
                        "project_uuid": project_id,
                        "thread_id": thread_id,
                        "nano_routing_plan": {
                            "content_plane": routing_plan.content_plane if routing_plan else None,
                            "operation": routing_plan.operation if routing_plan else None,
                            "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                            "confidence": routing_plan.confidence if routing_plan else None
                        },
                        "nano_router_used": nano_router_used
                    },
                    "sources": [],
                    "model": "Facts-F",
                    "model_label": f"Model: {model_label_text}",
                    "provider": "facts",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
    
    # Phase 2: Async Indexing (best-effort, non-blocking)
    # Index-P/Index-F reflects pipeline health (enqueue success), independent of Facts
    if thread_id and project_id:
        try:
            from server.services.memory_service_client import get_memory_client
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            user_msg_created_at = datetime.now(timezone.utc).isoformat()
            user_message_id = f"{thread_id}-user-{message_index}"
            
            # Enqueue user message for async indexing (non-blocking)
            # Index-P/Index-F reflects pipeline health (enqueue success), not completion
            memory_client = get_memory_client()
            logger.info(f"[MEMORY] Enqueueing user message for async indexing: {user_message_id} for project {project_id}")
            
            # Use client_message_uuid if available (from Facts persistence) or current_message_uuid
            message_uuid_for_indexing = current_message_uuid or client_message_uuid
            
            try:
                success, job_id, message_uuid = memory_client.index_chat_message(
                    project_id=project_id,
                    chat_id=thread_id,
                    message_id=user_message_id,
                    role="user",
                    content=user_message,
                    timestamp=user_msg_created_at,
                    message_index=message_index,
                    message_uuid=message_uuid_for_indexing  # Pass provided UUID
                )
                
                # Use message_uuid from indexing if we don't have one yet
                if message_uuid and not current_message_uuid:
                    current_message_uuid = message_uuid
                    logger.info(f"[MEMORY] Captured message_uuid={message_uuid} from indexing for fact exclusion")
                
                # Index-P = pipeline operational, job accepted/queued
                # Index-F = pipeline failed to accept/queue job
                user_index_job_id = None  # Track job ID for metadata
                if success:
                    index_status = "P"
                    user_index_job_id = job_id
                    logger.info(f"[MEMORY] ✅ Enqueued indexing job {job_id} for user message {user_message_id}")
                else:
                    index_status = "F"
                    logger.warning(f"[MEMORY] ⚠️  Failed to enqueue indexing job for user message {user_message_id}")
                    
            except Exception as e:
                index_status = "F"
                logger.warning(f"[MEMORY] ❌ Exception enqueueing user message: {e}", exc_info=True)
                # Don't block response - Facts already persisted, indexing is best-effort
            
        except Exception as e:
            index_status = "F"
            user_index_job_id = None
            logger.warning(f"[MEMORY] ❌ Exception setting up async indexing: {e}", exc_info=True)
            # Don't block response - Facts already persisted, indexing is best-effort
    
    # ============================================================================
    # REMOVED: Facts retrieval bypass
    # ============================================================================
    # All queries now go through GPT-5. Memory Service is a tool only - it provides
    # structured evidence, but GPT-5 always generates the user-facing response.
    # Facts are still retrieved and passed as context to GPT-5, but GPT-5 formats the response.
    
    # NOTE: Facts retrieval bypass removed - all responses must go through GPT-5
    # The facts DB is still used, but facts are passed as Memory context to GPT-5
    # instead of being returned directly.
    
    # REMOVED: Legacy regex-based Facts-R list fast path
    # All Facts-R queries now go through GPT-5 Nano query-to-plan → deterministic retrieval
    # Fast-path responses are handled in the Nano-based Facts-R section below
    
    # 0. Get memory context if project_id is available
    memory_context = ""
    sources = []
    has_memory = False
    memory_stored = False  # Track if memory was stored (fact extraction/indexing)
    searched_memory = False  # Track if we attempted to search memory (even if no results)
    hits = []  # Initialize hits to empty list so it's always defined
    
    # query_plan is already initialized at line 547 (function scope)
    # CRITICAL: Enforce routing invariant - retrieval queries MUST execute Facts-R first
    # Detect retrieval queries using lightweight heuristic (before LLM planning)
    is_retrieval_query_heuristic = False
    user_message_lower = user_message.lower().strip()
    retrieval_patterns = [
        "list my", "list", "show my", "show", "what are my", "what are", 
        "tell me my", "tell me", "display my", "display", "get my", "get"
    ]
    for pattern in retrieval_patterns:
        if user_message_lower.startswith(pattern):
            is_retrieval_query_heuristic = True
            break
    
    # Re-initialize is_retrieval_query here for the retrieval section
    is_retrieval_query = False
    if project_id:
        try:
            from server.services.facts_query_planner import plan_facts_query
            from server.services.facts_llm.client import FactsLLMError
            
            # Try to plan the query to determine if it's a retrieval query
            try:
                query_plan = await plan_facts_query(user_message)
                is_retrieval_query = query_plan.intent in ["facts_get_ranked_list", "facts_get_by_prefix", "facts_get_exact_key"]
            except FactsLLMError:
                # If query planning fails but heuristic says retrieval, still try Facts-R
                is_retrieval_query = is_retrieval_query_heuristic
            except Exception:
                # If query planning fails for any reason but heuristic says retrieval, still try Facts-R
                is_retrieval_query = is_retrieval_query_heuristic
        except Exception:
            # If we can't import or plan, use heuristic
            is_retrieval_query = is_retrieval_query_heuristic
    
    # CRITICAL ROUTING INVARIANT: Only execute Facts-R if routing plan says facts/read
    # MUST execute Facts-R first and return Facts-R response (never Index/GPT)
    if project_id and routing_plan.content_plane == "facts" and routing_plan.operation == "read":
        # Facts-R is a read operation, so write_intent is False
        is_write_intent = False
        try:
            # NEW: Use routing plan candidate if available, otherwise call Facts query planner
            from server.services.facts_retrieval import execute_facts_plan
            from server.services.facts_llm.client import FactsLLMError
            from server.services.canonicalizer import canonicalize_topic
            from server.contracts.facts_ops import FactsQueryPlan
            
            # Canonicalization result for telemetry
            canonicalization_result = None
            
            # Use routing plan candidate if available (avoids second Nano call)
            ordinal_parse_source = "none"
            if routing_plan.facts_read_candidate:
                router_rank = routing_plan.facts_read_candidate.rank
                if router_rank:
                    ordinal_parse_source = "router"
                
                logger.info(
                    f"[FACTS-R] Using routing plan candidate (topic={routing_plan.facts_read_candidate.topic}, "
                    f"rank={router_rank}), skipping query planner"
                )
                # Canonicalize topic using Canonicalizer subsystem
                canonicalization_result = canonicalize_topic(
                    routing_plan.facts_read_candidate.topic,
                    invoke_teacher=True
                )
                canonical_topic = canonicalization_result.canonical_topic
                logger.info(
                    f"[FACTS-R] Canonicalized topic: '{routing_plan.facts_read_candidate.topic}' → "
                    f"'{canonical_topic}' (confidence: {canonicalization_result.confidence:.3f}, "
                    f"source: {canonicalization_result.source}, "
                    f"teacher_invoked: {canonicalization_result.teacher_invoked})"
                )
                from server.services.facts_normalize import canonical_list_key
                list_key = canonical_list_key(canonical_topic)
                query_plan = FactsQueryPlan(
                    intent="facts_get_ranked_list",
                    list_key=list_key,
                    topic=canonical_topic,
                    limit=25 if router_rank is None else 1,  # Limit to 1 for ordinal queries
                    include_ranks=True,
                    rank=router_rank  # CRITICAL: Pass rank from router
                )
                logger.info(f"[FACTS-R] Query plan created with rank={router_rank} (ordinal_parse_source={ordinal_parse_source})")
            else:
                # Fallback to query planner (should be rare)
                if not query_plan:
                    try:
                        query_plan = await plan_facts_query(user_message)
                    except Exception as e:
                        logger.warning(f"[FACTS-R] Query planning failed for retrieval query: {e}")
                        query_plan = None
            
            # If we have a query plan, execute it
            if query_plan is not None:
                # HIGH-SIGNAL LOGGING: Log retrieval attempt
                raw_topic = query_plan.topic if query_plan else None
                # If canonicalization_result not set yet (from query planner path), canonicalize now
                if not canonicalization_result and raw_topic:
                    canonicalization_result = canonicalize_topic(raw_topic, invoke_teacher=True)
                    canonical_topic = canonicalization_result.canonical_topic
                    logger.info(
                        f"[FACTS-R] Canonicalized topic from query plan: '{raw_topic}' → "
                        f"'{canonical_topic}' (confidence: {canonicalization_result.confidence:.3f}, "
                        f"source: {canonicalization_result.source}, "
                        f"teacher_invoked: {canonicalization_result.teacher_invoked})"
                    )
                else:
                    canonical_topic = canonicalization_result.canonical_topic if canonicalization_result else raw_topic
                computed_list_key = query_plan.list_key if query_plan else None
                
                logger.info(
                    f"[FACTS-R] RETRIEVAL_ATTEMPT "
                    f"message_uuid={current_message_uuid} project_id={project_id} thread_id={thread_id} "
                    f"query_plan.intent={query_plan.intent if query_plan else 'N/A'} "
                    f"query_plan.topic.raw={raw_topic} canonical_topic={canonical_topic} "
                    f"computed_list_key={computed_list_key}"
                )
                
                # Execute plan deterministically
                # Pass ordinal_parse_source for telemetry
                facts_answer = execute_facts_plan(
                    project_uuid=project_id,
                    plan=query_plan,
                    exclude_message_uuid=current_message_uuid,
                    ordinal_parse_source=ordinal_parse_source
                )
                
                # Count distinct canonical keys for Facts-R
                facts_actions["R"] = len(facts_answer.canonical_keys)
                if facts_actions["R"] > 0:
                    logger.info(f"[FACTS-R] Retrieved {facts_actions['R']} distinct canonical keys: {facts_answer.canonical_keys}")
                
                # Fast-path response for ranked list queries (no GPT-5)
                # GPT-5 Nano determines if this is a list query via query plan intent
                if query_plan is not None and query_plan.intent == "facts_get_ranked_list" and facts_answer.facts:
                    # Check if this is an ordinal query (specific rank requested)
                    if query_plan.rank is not None:
                        # Ordinal query: return just the single fact at the requested rank
                        fact = facts_answer.facts[0]  # Should only be one fact when rank is specified
                        list_items = fact.get("value_text", "")
                        sorted_facts = [fact]  # Single fact for sources building
                        logger.info(f"[FACTS-R] Ordinal query response: rank={query_plan.rank}, value={list_items}")
                    else:
                        # Full list query: return all facts in ranked order
                        sorted_facts = sorted(facts_answer.facts, key=lambda f: f.get("rank", float('inf')))
                        list_items = "\n".join([f"{f.get('rank', 0)}) {f.get('value_text', '')}" for f in sorted_facts])
                    
                    # Build sources array with source_message_uuid for deep linking
                    sources_by_uuid = {}
                    for fact in sorted_facts:
                        msg_uuid = fact.get("source_message_uuid")
                        if msg_uuid and msg_uuid not in sources_by_uuid:
                            topic = (query_plan.topic if query_plan is not None else None) or "items"
                            sources_by_uuid[msg_uuid] = {
                                "id": f"fact-{msg_uuid[:8]}",
                                "title": f"Stored Facts",
                                "siteName": "Facts",
                                "description": f"Ranked list: {topic}",
                                "rank": len(sources_by_uuid),
                                "sourceType": "memory",
                                "citationPrefix": "M",
                                "meta": {
                                    "source_message_uuid": msg_uuid,
                                    "topic_key": topic,
                                    "fact_count": len([f for f in sorted_facts if f.get("source_message_uuid") == msg_uuid])
                                }
                            }
                    
                    sources = list(sources_by_uuid.values())
                    logger.info(f"[FACTS-R] ✅ Fast-path ranked list response: topic={query_plan.topic if query_plan is not None else 'unknown'}, items={len(sorted_facts)}")
                    
                    # HIGH-SIGNAL LOGGING: Log response path with rank telemetry
                    requested_rank = query_plan.rank if query_plan else None
                    rank_applied = requested_rank is not None
                    rank_result_found = len(facts_answer.facts) > 0 if rank_applied else None
                    logger.info(
                        f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=READ_FASTPATH "
                        f"message_uuid={current_message_uuid} project_id={project_id} thread_id={thread_id} "
                        f"query_plan.intent={query_plan.intent if query_plan else 'N/A'} "
                        f"query_plan.topic={query_plan.topic if query_plan else 'N/A'} "
                        f"requested_rank={requested_rank} rank_applied={rank_applied} rank_result_found={rank_result_found} "
                        f"ordinal_parse_source={ordinal_parse_source} "
                        f"canonical_topic={canonical_topic} computed_list_key={computed_list_key} "
                        f"facts_answer.count={facts_answer.count} canonical_keys={facts_answer.canonical_keys} "
                        f"store_count={facts_actions.get('S', 0)} update_count={facts_actions.get('U', 0)} "
                        f"facts_r_count={facts_actions.get('R', 0)}"
                    )
                    
                    # Extract canonicalization info for telemetry and model label
                    canonicalizer_used_read = canonicalization_result is not None
                    teacher_invoked_read = canonicalization_result.teacher_invoked if canonicalization_result else False
                    model_label_read = build_model_label(
                        facts_actions=facts_actions,
                        files_actions=files_actions,
                        index_status=index_status,
                        escalated=False,
                        nano_router_used=nano_router_used,
                        reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                        canonicalizer_used=canonicalizer_used_read,
                        teacher_invoked=teacher_invoked_read
                    )
                    
                    # Save to history
                    if thread_id:
                        try:
                            history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                            message_index = len(history)
                            
                            # Add user message to history FIRST (before assistant message)
                            user_msg_created_at = datetime.now(timezone.utc).isoformat()
                            user_message_id = f"{thread_id}-user-{message_index}"
                            user_msg = {
                                "id": user_message_id,
                                "role": "user",
                                "content": user_message,
                                "created_at": user_msg_created_at,
                                "uuid": current_message_uuid  # Include UUID for rehydration
                            }
                            history.append(user_msg)
                            
                            # Now add assistant message
                            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                            assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                            # Extract canonicalization info for model label
                            canonicalizer_used_hist = canonicalization_result is not None
                            teacher_invoked_hist = canonicalization_result.teacher_invoked if canonicalization_result else False
                            model_label_hist = build_model_label(
                                facts_actions=facts_actions,
                                files_actions=files_actions,
                                index_status=index_status,
                                escalated=False,
                                nano_router_used=nano_router_used,
                                reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                                canonicalizer_used=canonicalizer_used_hist,
                                teacher_invoked=teacher_invoked_hist
                            )
                            history.append({
                                "id": assistant_message_id,
                                "role": "assistant",
                                "content": list_items,
                                "model": model_label_hist,
                                "model_label": f"Model: {model_label_hist}",
                                "provider": "facts",
                                "created_at": assistant_msg_created_at,
                                "uuid": None  # Assistant messages don't have message_uuid (they're not indexed separately)
                            })
                            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                        except Exception as e:
                            logger.warning(f"Failed to save list answer to history: {e}")
                    
                    # Return fast-path response (no GPT-5)
                    return {
                        "type": "assistant_message",
                        "content": list_items,
                        "meta": {
                            "usedFacts": True,
                            "fastPath": "facts_retrieval",
                            "facts_actions": facts_actions,
                            "files_actions": files_actions,
                            "index_status": index_status,
                            "facts_provider": facts_provider,
                            "project_uuid": project_id,
                            "thread_id": thread_id,
                            "facts_gate_entered": facts_gate_entered,
                            "facts_gate_reason": facts_gate_reason or "unknown",
                            "write_intent_detected": is_write_intent,
                            # Canonicalization telemetry
                            "canonical_topic": canonicalization_result.canonical_topic if canonicalization_result else None,
                            "canonical_confidence": canonicalization_result.confidence if canonicalization_result else None,
                            "teacher_invoked": teacher_invoked_read,
                            "alias_source": canonicalization_result.source if canonicalization_result else None,
                            # Rank telemetry
                            "requested_rank": query_plan.rank if query_plan else None,
                            "detected_rank": query_plan.rank if query_plan else None,
                            "ordinal_parse_source": ordinal_parse_source,
                            "rank_applied": query_plan.rank is not None if query_plan else False,
                            "rank_result_found": len(facts_answer.facts) > 0 if query_plan and query_plan.rank else None
                        },
                        "sources": sources,
                        "model": model_label_read,
                        "model_label": f"Model: {model_label_read}",
                        "provider": "facts",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                elif query_plan is not None and query_plan.intent == "facts_get_ranked_list" and not facts_answer.facts:
                    # Ranked list query but no facts found
                    # GUARD: "I don't have that stored yet" only appears on empty Facts-R retrieval
                    # Assert that this is NOT a write operation (store_count/update_count should be 0)
                    if facts_actions.get("S", 0) > 0 or facts_actions.get("U", 0) > 0:
                        logger.error(
                            f"[FACTS-RESPONSE] BUG: 'I don't have that stored yet' triggered with "
                            f"store_count={facts_actions.get('S', 0)} update_count={facts_actions.get('U', 0)}. "
                            f"This should not happen - Facts-S/U should return confirmation before Facts-R."
                        )
                    
                    logger.info(f"[FACTS-R] Ranked list query returned no facts: topic={query_plan.topic if query_plan is not None else 'unknown'}")
                    
                    # ORDINAL BOUNDS MESSAGING: If this is an ordinal query and we have max_available_rank,
                    # provide a more informative message
                    response_text = "I don't have that stored yet."
                    if query_plan.rank is not None and facts_answer.max_available_rank is not None:
                        if query_plan.rank > facts_answer.max_available_rank:
                            response_text = f"I only have {facts_answer.max_available_rank} favorite{'s' if facts_answer.max_available_rank != 1 else ''} stored, so there's no #{query_plan.rank} favorite."
                            logger.info(f"[FACTS-R] Ordinal bounds check: requested rank={query_plan.rank}, max_available={facts_answer.max_available_rank}")
                    
                    # HIGH-SIGNAL LOGGING: Log empty retrieval response path
                    logger.info(
                        f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=READ_FASTPATH_EMPTY "
                        f"message_uuid={current_message_uuid} project_id={project_id} thread_id={thread_id} "
                        f"query_plan.intent={query_plan.intent if query_plan else 'N/A'} "
                        f"query_plan.topic.raw={raw_topic} canonical_topic={canonical_topic} "
                        f"computed_list_key={computed_list_key} facts_answer.count={facts_answer.count} "
                        f"canonical_keys={facts_answer.canonical_keys} "
                        f"store_count={facts_actions.get('S', 0)} update_count={facts_actions.get('U', 0)} "
                        f"facts_r_count={facts_actions.get('R', 0)}"
                    )
                    
                    if thread_id:
                        try:
                            history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
                            message_index = len(history)
                            assistant_message_id = f"{thread_id}-assistant-{message_index}"
                            # response_text is already set above with ordinal bounds messaging
                            # Extract canonicalization info for model label
                            canonicalizer_used_empty = canonicalization_result is not None
                            teacher_invoked_empty = canonicalization_result.teacher_invoked if canonicalization_result else False
                            model_label_empty = build_model_label(
                                facts_actions=facts_actions,
                                files_actions=files_actions,
                                index_status=index_status,
                                escalated=False,
                                nano_router_used=nano_router_used,
                                reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                                canonicalizer_used=canonicalizer_used_empty,
                                teacher_invoked=teacher_invoked_empty
                            )
                            history.append({
                                "id": assistant_message_id,
                                "role": "assistant",
                                "content": response_text,
                                "model": model_label_empty,
                                "model_label": f"Model: {model_label_empty}",
                                "provider": "facts",
                                "created_at": assistant_msg_created_at
                            })
                            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
                        except Exception as e:
                            logger.warning(f"Failed to save 'not found' answer to history: {e}")
                    
                    # CRITICAL: This should only appear for retrieval queries, not write-intent
                    if is_write_intent:
                        # Write-intent message but retrieval returned empty - this means Facts-S/U didn't execute
                        # Get diagnostic information from raw LLM response store
                        from server.services.facts_persistence import _raw_llm_responses
                        diagnostic_info = _raw_llm_responses.get(current_message_uuid) if current_message_uuid else None
                        
                        # Build specific error reason
                        if diagnostic_info:
                            ops_count = diagnostic_info.get("ops_count", 0)
                            needs_clarification = diagnostic_info.get("needs_clarification")
                            apply_result = diagnostic_info.get("apply_result", {})
                            apply_warnings = len(apply_result.get("warnings", []))
                            apply_errors = len(apply_result.get("errors", []))
                            
                            if needs_clarification:
                                skip_reason = f"Extractor needs clarification: {', '.join(needs_clarification)}"
                            elif ops_count == 0:
                                skip_reason = "Extractor returned empty ops (no facts extracted from message)"
                            elif apply_warnings > 0 or apply_errors > 0:
                                skip_reason = f"All ops rejected during apply ({apply_warnings} warnings, {apply_errors} errors)"
                            else:
                                skip_reason = "Facts-S/U returned 0 counts (unknown reason)"
                        else:
                            skip_reason = "Facts-S/U returned 0 counts (diagnostics not available)"
                        
                        logger.error(
                            f"[FACTS] WRITE_INTENT_BYPASS_PREVENTED: write-intent message '{user_message[:50]}...' "
                            f"returned empty retrieval. Facts-S/U counts: S={facts_actions.get('S', 0)}, "
                            f"U={facts_actions.get('U', 0)}, reason={skip_reason}, "
                            f"facts_gate_entered={facts_gate_entered}, facts_gate_reason={facts_gate_reason}"
                        )
                        facts_actions["F"] = True
                        error_message = (
                            f"Facts write failed: {skip_reason}. "
                            f"Check server logs for raw LLM response (message_uuid={current_message_uuid if current_message_uuid else 'N/A'})."
                        )
                        return {
                            "type": "assistant_message",
                            "content": error_message,
                            "meta": {
                                "fastPath": "facts_error",
                                "facts_error": True,
                                "facts_skip_reason": skip_reason,
                                "facts_actions": {"S": 0, "U": 0, "R": 0, "F": True},
                                "facts_provider": facts_provider,
                                "project_uuid": project_id,
                                "thread_id": thread_id,
                                "facts_gate_entered": facts_gate_entered,
                                "facts_gate_reason": facts_gate_reason or "unknown",
                                "write_intent_detected": True
                            },
                            "sources": [],
                            "model": "Facts-F",
                            "model_label": "Model: Facts-F",
                            "provider": "facts",
                            "created_at": datetime.now(timezone.utc).isoformat()
                        }
                    
                    # GUARD: "I don't have that stored yet" ONLY comes from Facts-R empty fastpath
                    # This is the ONLY place this message should be emitted
                    # Normal empty retrieval response (for non-write-intent queries)
                    # Extract canonicalization info for telemetry and model label
                    canonicalizer_used_empty_resp = canonicalization_result is not None
                    teacher_invoked_empty_resp = canonicalization_result.teacher_invoked if canonicalization_result else False
                    model_label_empty_resp = build_model_label(
                        facts_actions=facts_actions,
                        files_actions=files_actions,
                        index_status=index_status,
                        escalated=False,
                        nano_router_used=nano_router_used,
                        reasoning_required=routing_plan.reasoning_required if routing_plan else True,
                        canonicalizer_used=canonicalizer_used_empty_resp,
                        teacher_invoked=teacher_invoked_empty_resp
                    )
                    # Use response_text (which may include ordinal bounds messaging)
                    return {
                        "type": "assistant_message",
                        "content": response_text,  # May be "I don't have that stored yet." or ordinal bounds message
                        "meta": {
                            "usedFacts": True,
                            "factNotFound": True,
                            "fastPath": "facts_retrieval_empty",
                            "facts_actions": facts_actions,
                            "files_actions": files_actions,
                            "index_status": index_status,
                            "facts_provider": facts_provider,
                            "project_uuid": project_id,
                            "thread_id": thread_id,
                            "facts_gate_entered": facts_gate_entered,
                            "facts_gate_reason": facts_gate_reason or "unknown",
                            "write_intent_detected": is_write_intent,
                            # Canonicalization telemetry
                            "canonical_topic": canonicalization_result.canonical_topic if canonicalization_result else None,
                            "canonical_confidence": canonicalization_result.confidence if canonicalization_result else None,
                            "teacher_invoked": teacher_invoked_empty_resp,
                            "alias_source": canonicalization_result.source if canonicalization_result else None,
                            # Rank telemetry (from FactsAnswer)
                            "requested_rank": query_plan.rank if query_plan else None,
                            "detected_rank": query_plan.rank if query_plan else None,
                            "ordinal_parse_source": facts_answer.ordinal_parse_source,
                            "rank_applied": facts_answer.rank_applied,
                            "rank_result_found": facts_answer.rank_result_found,
                            "max_available_rank": facts_answer.max_available_rank
                        },
                        "model": model_label_empty_resp,
                        "model_label": f"Model: {model_label_empty_resp}",
                        "provider": "facts",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
            
            # If query plan is None but heuristic says retrieval, log warning and continue
            # (We'll fall through to Index/GPT, but this should be rare)
            elif is_retrieval_query_heuristic:
                logger.warning(
                    f"[FACTS-R] Retrieval query detected (heuristic) but query planning failed. "
                    f"Falling through to Index/GPT (this should be rare). "
                    f"message_uuid={current_message_uuid} project_id={project_id}"
                )
                # Log fallthrough
                logger.info(
                    f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=GPT5_FALLTHROUGH "
                    f"message_uuid={current_message_uuid} project_id={project_id} thread_id={thread_id} "
                    f"reason=query_plan_failed_for_retrieval_heuristic"
                )
        except Exception as e:
            logger.error(f"[FACTS-R] Exception during retrieval execution: {e}", exc_info=True)
            # If retrieval fails, log and continue (will fall through to Index/GPT)
            logger.info(
                f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=GPT5_FALLTHROUGH "
                f"message_uuid={current_message_uuid} project_id={project_id} thread_id={thread_id} "
                f"reason=retrieval_exception: {str(e)[:100]}"
            )
            
            # For non-ranked-list queries (exact key, prefix), convert facts to memory hits for GPT-5 context
            # Note: facts_answer may not be defined if exception occurred before execution
            from server.services.librarian import MemoryHit
            fact_hits = []
            try:
                if 'facts_answer' in locals() and facts_answer.facts:
                    for fact in facts_answer.facts:
                        # Convert fact dict to MemoryHit object
                        fact_hits.append(MemoryHit(
                            source_id=f"project-{project_id}",
                            message_id=fact.get("source_message_uuid", ""),
                            chat_id=None,
                            role="fact",
                            content=f"{fact.get('fact_key', '')} = {fact.get('value_text', '')}",
                            score=1.0,
                            source_type="fact",
                            file_path=None,
                            created_at=fact.get("created_at"),
                            metadata={
                                "is_fact": True,
                                "fact_key": fact.get("fact_key"),
                                "value_text": fact.get("value_text"),
                                "source_message_uuid": fact.get("source_message_uuid")
                            },
                            message_uuid=fact.get("source_message_uuid")
                        ))
            except Exception:
                pass  # Ignore errors in fact hit conversion
            
            # Also get non-fact memory hits from librarian (for Index domain)
            # This provides semantic search results alongside facts
            # Note: librarian.get_relevant_memory includes both facts and index hits
            # We'll filter out fact hits and only use index hits
            all_hits = librarian.get_relevant_memory(
                project_id=project_id,
                query=user_message,
                chat_id=None,
                max_hits=30,
                exclude_message_uuid=current_message_uuid
            )
            
            # Filter to only index hits (non-fact hits)
            index_hits = [
                hit for hit in all_hits 
                if not (hit.metadata and hit.metadata.get("is_fact"))
            ]
            
            # Combine fact hits (from query planner) and index hits
            hits = fact_hits + index_hits
            searched_memory = True
            has_memory = len(hits) > 0
            
            if has_memory:
                # Format hits into context string for GPT-5
                memory_context = librarian.format_hits_as_context(hits)
                logger.info(f"[MEMORY] Retrieved memory context: {len(fact_hits)} facts + {len(index_hits)} index hits")
                    
        except FactsLLMError as e:
                # Facts-R query planner failed - hard fail Facts-R but continue with Index
                logger.error(f"[FACTS-R] Query planner failed: {e}")
                facts_actions["R"] = 0
                facts_actions["F"] = True  # Mark Facts as failed
                
                # Fallback to Index-only memory retrieval
                hits = librarian.get_relevant_memory(
                    project_id=project_id,
                    query=user_message,
                    chat_id=None,
                    max_hits=30,
                    exclude_message_uuid=current_message_uuid
                )
                searched_memory = True
                has_memory = len(hits) > 0
                if has_memory:
                    memory_context = librarian.format_hits_as_context(hits)
                    
        except Exception as e:
            # Hard fail Facts-R if new system fails (no fallback)
            logger.error(f"[FACTS-R] Query planner failed with unexpected error: {e}", exc_info=True)
            facts_actions["R"] = 0
            facts_actions["F"] = True  # Mark Facts as failed
            
            # Still get Index hits for GPT-5 context (Facts failure doesn't block Index)
            hits = librarian.get_relevant_memory(
                project_id=project_id,
                query=user_message,
                chat_id=None,
                max_hits=30,
                exclude_message_uuid=current_message_uuid
            )
            searched_memory = True
            has_memory = len(hits) > 0
            if has_memory:
                memory_context = librarian.format_hits_as_context(hits)
            
            # REMOVED: Legacy topic extraction for facts retrieval
            # All Facts retrieval now goes through GPT-5 Nano query-to-plan (above)
            
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
                    # Determine kind: "chat" for chat messages/facts, "file" for file sources
                    kind = "file" if hit.file_path else "chat"
                    memory_source = {
                        "id": f"memory-{hit.source_id}-{idx}",
                        "title": title,
                        "description": description,
                        "sourceType": "memory",
                        "citationPrefix": "M",
                        "rank": idx,  # Rank within Memory group
                        "siteName": "Memory",
                        "meta": {
                            "kind": kind,  # "chat" or "file" for navigation
                            "chat_id": hit.chat_id,
                            "message_id": hit.message_id,
                            "message_uuid": hit.message_uuid,  # Stable UUID for deep-linking (chat/facts only)
                            "file_path": hit.file_path,  # File path (file sources only)
                            "file_id": hit.metadata.get("file_id") if hit.metadata else None,  # File ID (file sources only)
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
        # Only use GPT-5 if reasoning_required is True (per Nano router decision)
        used_web = False
        # Memory tag shows if memory was stored OR retrieved (Memory service was used)
        used_memory = has_memory or memory_stored
        
        # ENFORCE NANO ROUTING: Only call GPT-5 if reasoning_required is True
        if routing_plan.reasoning_required:
            # Always route to GPT-5 (never GPT-5 Mini)
            logger.info(f"[MEMORY] Routing to GPT-5 with Memory context ({len(hits) if hits else 0} hits)")
            
            # Log response path (GPT-5 fallthrough)
            logger.info(
                f"[FACTS-RESPONSE] FACTS_RESPONSE_PATH=GPT5_FALLTHROUGH "
                f"store_count={facts_actions.get('S', 0)} update_count={facts_actions.get('U', 0)} "
                f"facts_r_count={facts_actions.get('R', 0)} message_uuid={current_message_uuid}"
            )
            
            content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
                messages=messages,
                tools=tools,
                intent="general_chat",
                project_id=project_id,
                files_actions=files_actions
            )
        else:
            # No reasoning required - return simple confirmation
            logger.info(f"[NANO-ROUTER] Reasoning not required, skipping GPT-5 call")
            # For Facts-S/U, we already returned confirmation above
            # For other cases, return a simple acknowledgment
            content = "Done."
            model_id = "gpt-5-nano"
            provider_id = "openai-gpt5-nano"
        # Count distinct file sources from final sources list (before building model label)
        files_actions["R"] = count_distinct_file_sources(sources)
        
        # Build model label with new format
        model_display = build_model_label(
            facts_actions=facts_actions,
            files_actions=files_actions,
            index_status=index_status,
            escalated=True,
            nano_router_used=nano_router_used,
            reasoning_required=routing_plan.reasoning_required if routing_plan else True
        )
        logger.info(f"[MODEL] model label = {model_display}")
        
        # Build model_label and created_at BEFORE the thread_id check (needed for return statement)
        model_label = model_display  # No "Model: " prefix - format is locked
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                from server.services.memory_service_client import get_memory_client
                
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                message_index = len(history)
                
                # Add user message with timestamp
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                # Use constructed message_id to match indexing (enables UUID lookup)
                user_message_id = f"{thread_id}-user-{message_index}"
                user_msg = {
                    "id": user_message_id,  # Use constructed ID to match indexing
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at,
                    "uuid": current_message_uuid  # Include UUID for rehydration
                }
                # NOTE: Ranked lists are now stored in facts DB, not thread metadata
                history.append(user_msg)
                
                # Index user message into Memory Service for cross-chat search
                # NOTE: This is redundant since we index early (before memory search), but kept for safety
                # The early indexing ensures the message is available for immediate follow-up questions
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        # user_message_id already defined above
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
                
                # Enqueue assistant message for async indexing (non-blocking) BEFORE adding to history
                assistant_index_job_id = None
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                        logger.info(f"[MEMORY] Enqueueing assistant message for async indexing: {assistant_message_id} for project {project_id}")
                        success, job_id, _ = memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=thread_id,
                            message_id=assistant_message_id,  # This matches the "id" we'll save to history
                            role="assistant",
                            content=content,
                            timestamp=assistant_msg_created_at,
                            message_index=message_index + 1
                        )
                        if success:
                            assistant_index_job_id = job_id
                            logger.info(f"[MEMORY] ✅ Enqueued indexing job {job_id} for assistant message {assistant_message_id}")
                        else:
                            logger.warning(f"[MEMORY] ⚠️  Failed to enqueue indexing job for assistant message {assistant_message_id}")
                    except Exception as e:
                        logger.warning(f"[MEMORY] ❌ Exception enqueueing assistant message: {e}", exc_info=True)
                else:
                    logger.warning(f"[MEMORY] ⚠️  Skipping assistant message indexing: project_id is None (thread_id={thread_id})")
                
                # Add assistant message with timestamp and model_label (after enqueueing so job_id is available)
                # Use constructed message_id to match indexing (enables UUID lookup)
                assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                history.append({
                    "id": assistant_message_id,  # Use constructed ID to match indexing
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "model_label": model_label,
                    "provider": provider_id,
                    "sources": sources if sources else None,
                    "meta": {
                        "usedWebSearch": False,
                        "usedMemory": used_memory,
                        "facts_actions": facts_actions,
                        "files_actions": files_actions,
                        "index_status": index_status,
                        "index_job": {
                            "user_job_id": user_index_job_id if 'user_index_job_id' in locals() else None,
                            "assistant_job_id": assistant_index_job_id
                        } if (('user_index_job_id' in locals() and user_index_job_id) or assistant_index_job_id) else None
                    },
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
                "usedMemory": used_memory,
                "facts_actions": facts_actions,
                "files_actions": files_actions,
                "index_status": index_status,
                "index_job": {
                    "user_job_id": user_index_job_id if 'user_index_job_id' in locals() else None,
                    "assistant_job_id": assistant_index_job_id if 'assistant_index_job_id' in locals() else None
                } if ('user_index_job_id' in locals() and user_index_job_id) or ('assistant_index_job_id' in locals() and assistant_index_job_id) else None,
                "nano_routing_plan": {
                    "content_plane": routing_plan.content_plane if routing_plan else None,
                    "operation": routing_plan.operation if routing_plan else None,
                    "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                    "confidence": routing_plan.confidence if routing_plan else None
                },
                "nano_router_used": nano_router_used
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
            project_id=project_id,
            files_actions=files_actions
        )
        
        # Build model_label for this response
        model_label = f"Model: {model_display}"
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        
        # Save to memory store if thread_id is provided
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                # Use constructed message_id to match indexing (enables UUID lookup)
                message_index = len(history)
                user_message_id = f"{thread_id}-user-{message_index}"
                assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                history.append({
                    "id": user_message_id,  # Use constructed ID to match indexing
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at,
                    "uuid": current_message_uuid  # Include UUID for rehydration
                })
                history.append({
                    "id": assistant_message_id,  # Use constructed ID to match indexing
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
                "webSearchError": str(e),
                "facts_actions": facts_actions,
                "files_actions": files_actions,
                "index_status": index_status,
                "index_job": {
                    "user_job_id": user_index_job_id if 'user_index_job_id' in locals() else None,
                    "assistant_job_id": None
                } if 'user_index_job_id' in locals() and user_index_job_id else None
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
            project_id=project_id,
            files_actions=files_actions
        )
        
        # Save to memory store if thread_id is provided
        assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
        model_label = f"Model: {model_display}"
        if thread_id:
            try:
                history = memory_store.load_thread_history(target_name, thread_id, project_id=project_id)
                user_msg_created_at = datetime.now(timezone.utc).isoformat()
                # Use constructed message_id to match indexing (enables UUID lookup)
                message_index = len(history)
                user_message_id = f"{thread_id}-user-{message_index}"
                assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
                history.append({
                    "id": user_message_id,  # Use constructed ID to match indexing
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_created_at,
                    "uuid": current_message_uuid  # Include UUID for rehydration
                })
                history.append({
                    "id": assistant_message_id,  # Use constructed ID to match indexing
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
                "webSearchEmpty": True,
                "facts_actions": facts_actions,
                "files_actions": files_actions,
                "index_status": index_status,
                "index_job": {
                    "user_job_id": user_index_job_id if 'user_index_job_id' in locals() else None,
                    "assistant_job_id": None
                } if 'user_index_job_id' in locals() and user_index_job_id else None,
                "nano_routing_plan": {
                    "content_plane": routing_plan.content_plane if routing_plan else None,
                    "operation": routing_plan.operation if routing_plan else None,
                    "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                    "confidence": routing_plan.confidence if routing_plan else None
                },
                "nano_router_used": nano_router_used
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
    
    # ENFORCE NANO ROUTING: Only call GPT-5 if reasoning_required is True
    if routing_plan.reasoning_required:
        # Call GPT-5 with web search context (with tool loop processing)
        content, model_id, provider_id, model_display = await call_ai_router_with_tool_loop(
            messages=messages,
            tools=tools,
            intent="general_chat",
            project_id=project_id
        )
    else:
        # No reasoning required - return simple confirmation
        logger.info(f"[NANO-ROUTER] Reasoning not required, skipping GPT-5 call (web search path)")
        content = "Done."  # Simple confirmation
        model_id = "gpt-5-nano"
        provider_id = "openai-gpt5-nano"
        model_display = "GPT-5 Nano"
    
    # Save to memory store if thread_id is provided
    if thread_id:
        try:
            from server.services.memory_service_client import get_memory_client
            
            history = memory_store.load_thread_history(target_name, thread_id)
            message_index = len(history)
            
            # Add user message with timestamp
            from uuid import uuid4
            user_msg_created_at = datetime.now(timezone.utc).isoformat()
            # Use constructed message_id to match indexing (enables UUID lookup)
            user_message_id = f"{thread_id}-user-{message_index}"
            user_msg = {
                "id": user_message_id,  # Use constructed ID to match indexing
                "role": "user",
                "content": user_message,
                "created_at": user_msg_created_at,
                "uuid": current_message_uuid  # Include UUID for rehydration
            }
            # NOTE: Ranked lists are now stored in facts DB, not thread metadata
            history.append(user_msg)
            
            # Index user message into Memory Service for cross-chat search
            # NOTE: This is redundant since we index early (before memory search), but kept for safety
            # The early indexing ensures the message is available for immediate follow-up questions
            if project_id:
                try:
                    memory_client = get_memory_client()
                    # user_message_id already defined above
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
            
            # Count distinct file sources from final sources list (before building model label)
            files_actions["R"] = count_distinct_file_sources(all_sources)
            
            assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
            # Build model label with memory actions
            model_label = build_model_label(
                facts_actions=facts_actions,
                files_actions=files_actions,
                index_status=index_status,
                escalated=True,
                nano_router_used=nano_router_used,
                reasoning_required=routing_plan.reasoning_required if routing_plan else True
            )
            # Use constructed message_id to match indexing (enables UUID lookup)
            assistant_message_id = f"{thread_id}-assistant-{message_index + 1}"
            assistant_message = {
                "id": assistant_message_id,  # Use constructed ID to match indexing
                "role": "assistant",
                "content": content,
                "model": model_label.replace("Model: ", ""),  # Store without "Model: " prefix
                "model_label": model_label,
                "provider": provider_id,
                "sources": all_sources if all_sources else None,
                "meta": {
                    "usedWebSearch": True,
                    "webResultsPreview": web_results[:5],
                    "facts_actions": facts_actions,
                    "files_actions": files_actions,
                    "index_status": index_status,
                    "index_job": {
                        "user_job_id": user_index_job_id if 'user_index_job_id' in locals() else None,
                        "assistant_job_id": None
                    } if 'user_index_job_id' in locals() and user_index_job_id else None
                },
                "created_at": assistant_msg_created_at
            }
            history.append(assistant_message)
            memory_store.save_thread_history(target_name, thread_id, history, project_id=project_id)
            
            # Index assistant message into Memory Service for cross-chat search
            if project_id:
                try:
                    memory_client = get_memory_client()
                    # assistant_message_id already defined above
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
    
    # Count distinct file sources from final sources list (before building model label)
    files_actions["R"] = count_distinct_file_sources(all_sources)
    
    # Get created_at and model_label from saved message or generate
    assistant_msg_created_at = datetime.now(timezone.utc).isoformat()
    # Build model label with new format
    model_label = build_model_label(
        facts_actions=facts_actions,
        files_actions=files_actions,
        index_status=index_status,
        escalated=True,
        nano_router_used=nano_router_used,
                            reasoning_required=routing_plan.reasoning_required if routing_plan else True
    )
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
    
    # CRITICAL: Before returning final response, check if write-intent message bypassed Facts
    # If write-intent and Facts-S/U did not execute (counts are 0 and no Facts-F), return Facts-F
    if is_write_intent and facts_actions["S"] == 0 and facts_actions["U"] == 0 and not facts_actions["F"]:
        # Write-intent message but Facts didn't run - this should not happen if gate worked correctly
        # But if it did, we must return Facts-F to prevent silent fallthrough
        skip_reason = "Facts gate was skipped or Facts-S/U did not execute for write-intent message"
        logger.error(f"[FACTS] WRITE_INTENT_BYPASS_PREVENTED: write-intent message bypassed Facts gate, returning Facts-F (reason: {skip_reason})")
        facts_actions["F"] = True
        error_message = (
            f"Facts unavailable: {skip_reason}. "
            "Please ensure you have selected a project and are in a valid conversation."
        )
        return {
            "type": "assistant_message",
            "content": error_message,
            "meta": {
                "fastPath": "facts_error",
                "facts_error": True,
                "facts_skip_reason": skip_reason,
                "facts_actions": {"S": 0, "U": 0, "R": 0, "F": True},
                "facts_provider": facts_provider,
                "project_uuid": project_id,
                "thread_id": thread_id,
                "facts_gate_entered": facts_gate_entered,
                "facts_gate_reason": facts_gate_reason or "unknown",
                "write_intent_detected": True
            },
            "sources": [],
            "model": "Facts-F",
            "model_label": "Model: Facts-F",
            "provider": "facts",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    
    # Normal response - include comprehensive meta for debugging
    return {
        "type": "assistant_message",
        "content": content,
        "meta": {
            "usedWebSearch": True,
            "usedMemory": has_memory or memory_stored,  # Memory was stored or retrieved
            "webResultsPreview": web_results[:5],  # Top 5 for sources display
            "facts_actions": facts_actions,
            "files_actions": files_actions,
            "facts_provider": facts_provider,
            "project_uuid": project_id,
            "thread_id": thread_id,
            "facts_gate_entered": facts_gate_entered,
            "facts_gate_reason": facts_gate_reason or "unknown",
            "write_intent_detected": is_write_intent,
            "message_uuid": current_message_uuid,  # Echo back user message UUID for reconciliation
            "nano_routing_plan": {
                "content_plane": routing_plan.content_plane if routing_plan else None,
                "operation": routing_plan.operation if routing_plan else None,
                "reasoning_required": routing_plan.reasoning_required if routing_plan else None,
                "confidence": routing_plan.confidence if routing_plan else None
            },
            "nano_router_used": nano_router_used
        },
        "model": model_label.replace("Model: ", ""),  # Return without "Model: " prefix for backward compatibility
        "model_label": model_label,
        "provider": provider_id,
        "sources": all_sources if all_sources else None,
        "created_at": assistant_msg_created_at
    }

