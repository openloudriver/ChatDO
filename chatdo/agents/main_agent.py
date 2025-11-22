from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Union
import os
import re
import requests
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools
from ..tools import web_search
from ..memory import store as memory_store
from ..utils.html_clean import strip_tags
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root (in case it's not loaded by the server)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# AI-Router HTTP client
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")

# Article Summary System Prompt - Clean summary format
ARTICLE_SUMMARY_SYSTEM_PROMPT = """You are ChatDO's Article Summarizer.

When summarizing an article, produce a clean, concise summary with:

1. A 2–4 sentence summary paragraph
2. 3–5 key bullet points
3. (Optional) 1–2 sentences on why this matters or context

Keep it concise, neutral, and factual. Do not include the source URL in the summary text (it's already displayed separately)."""

# File/Document Summary System Prompt - Clean summary format
FILE_SUMMARY_SYSTEM_PROMPT = """You are ChatDO's Document Summarizer.

When summarizing a document, produce a clean, concise summary with:

1. A 2–4 sentence summary paragraph
2. 3–5 key bullet points
3. 1–2 sentences on why this matters or its significance

Format your response clearly with the summary first, then key points (as bullet points), then "Why This Matters:" followed by your analysis.

Keep it concise, neutral, and factual."""

# Cache the model ID to avoid making a preliminary call on every request
_cached_model_id: Optional[str] = None

def _format_model_name(provider_id: str, model_id: str) -> str:
    """Format provider and model ID into a display-friendly name."""
    provider_labels = {
        "openai-gpt5": "GPT-5",
        "anthropic-claude-sonnet": "Claude",
        "grok-code": "Grok",
        "gemini-pro": "Gemini",
        "mistral-large": "Mistral",
        "llama-local": "Llama",
    }
    provider_label = provider_labels.get(provider_id, provider_id)
    
    
    # For others, just use the provider label or model ID if it's more descriptive
    if provider_id == "openai-gpt5":
        return model_id  # e.g., "gpt-5" or "gpt-5.1"
    
    return provider_label

def classify_intent(text: str) -> str:
    """Classify user message intent for AI-Router routing."""
    t = text.lower()
    
    # Article summarization - user provides URLs to summarize (handled by separate endpoint)
    # No intent classification needed - handled by /api/article/summary endpoint
    
    # Web search - user wants to search for information, use Brave Search + GPT-5
    if ("search" in t or "find" in t or "look for" in t or "top headlines" in t or "latest" in t or 
        "current" in t or "today" in t or "recent" in t or "discover" in t or "what are" in t or
        "what's going on" in t or "what is going on" in t or "what's happening" in t or "what is happening" in t or
        "news" in t or "news articles" in t or "news article" in t or "headlines" in t or
        "tell me about" in t or "what about" in t or "update" in t or "updates" in t):
        return "web_search"
    if "refactor" in t or "fix" in t or "edit code" in t:
        return "code_edit"
    if "generate code" in t or "write a function" in t:
        return "code_gen"
    if "plan" in t or "architecture" in t or "roadmap" in t:
        return "long_planning"
    if "summarize" in t:
        return "summarize"
    if "draft" in t or "write" in t or "readme" in t or "policy" in t:
        return "doc_draft"
    
    return "general_chat"

def call_ai_router(messages: List[Dict[str, str]], intent: str = "general_chat", system_prompt_override: Optional[str] = None) -> tuple[List[Dict[str, str]], str, str, str]:
    """
    Call the AI-Router HTTP service to get AI responses.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        intent: AI intent type (e.g., "general_chat", "long_planning", "code_edit")
        system_prompt_override: Optional system prompt to override the default
    
    Returns:
        Tuple of (list of assistant messages from the router, model_id, provider_id, model_display_name)
    """
    # If system_prompt_override is provided, replace the system message
    router_messages = messages.copy()
    if system_prompt_override:
        # Find and replace system message, or add it if not present
        system_found = False
        for i, msg in enumerate(router_messages):
            if msg.get("role") == "system":
                router_messages[i] = {"role": "system", "content": system_prompt_override}
                system_found = True
                break
        if not system_found:
            router_messages.insert(0, {"role": "system", "content": system_prompt_override})
    
    payload = {
        "role": "chatdo",
        "intent": intent,
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": router_messages,
        },
    }
    try:
        # Increase timeout for complex reasoning queries (GPT-5 can take longer)
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"AI-Router error: {data.get('error')}")
        model_id = data.get("modelId", "gpt-5")
        provider_id = data.get("providerId", "openai-gpt5")
        # Create a display-friendly model name
        model_display = _format_model_name(provider_id, model_id)
        return data["output"]["messages"], model_id, provider_id, model_display
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Failed to connect to AI-Router at {AI_ROUTER_URL}. "
            f"Is the AI-Router server running? Error: {str(e)}"
        )
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"AI-Router request timed out: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"AI-Router request failed: {str(e)}")

# OLD MODEL ROUTING CODE - Now using AI-Router instead
# Keeping for reference but not used
# LEGACY MODEL ROUTING CODE (unused) — AI-Router now handles all routing
def choose_model(task: str) -> str:
    """Legacy model router (deprecated — AI-Router handles all routing)."""
    tl = task.lower()

    # Long-form, reproducible design / governance / threat-model work
    # Uses gpt-5 for these tasks
    if any(word in tl for word in [
        "whitepaper", "white paper", "spec", "specification", "design doc",
        "requirements", "threat model", "governance", "constitution",
        "bylaws", "policy", "architecture doc", "roadmap"
    ]):
        return "gpt-5"

    # High-level architecture / strategy / planning / product thinking
    if any(word in tl for word in [
        "architecture", "architect", "system design", "strategy",
        "roadmap", "plan", "planning", "high level", "overview",
        "meta", "vision"
    ]):
        return "gpt-5"

    # All tasks use gpt-5 (code tasks included)
    # Fallback general model
    return "gpt-5"

# OLD MODEL BUILDING CODE - Now using AI-Router instead
# Keeping for reference but not used
def build_model(task: str):
    """
    Build the chat model for this run, using the model router to
    pick an appropriate model based on the task description.
    
    OLD: Used ChatOpenAI with use_responses_api=True for older model versions.
    NOW: All models use standard chat completions API.
    """
    model_name = choose_model(task)
    return ChatOpenAI(model=model_name, temperature=0.2)

def build_tools(target: TargetConfig):
    # Wrap repo tools so deepagents can call them
    def list_files_wrapper(glob: str) -> list:
        """List files matching the glob pattern in the target repo.
        
        Args:
            glob: A glob pattern like 'packages/core/**/*' or '*.py' to find files.
                 Use '**/*' to recursively list all files.
        
        Returns:
            A list of relative file paths from the repo root.
        """
        return repo_tools.list_files(target.path, glob)
    
    def read_file_wrapper(rel_path: str) -> dict:
        """Read a file from the target repo."""
        file_obj = repo_tools.read_file(target.path, rel_path)
        return {"path": file_obj.path, "content": file_obj.content}
    
    def write_file_wrapper(rel_path: str, content: str) -> str:
        """Write content to a file in the target repo."""
        repo_tools.write_file(target.path, rel_path, content)
        return f"Wrote {rel_path}"
    
    return [
        list_files_wrapper,
        read_file_wrapper,
        write_file_wrapper,
    ]

# OLD AGENT BUILDING CODE - Now using AI-Router instead
# Keeping for reference but not used
# Note: Tools functionality would need to be added to AI-Router if needed
def build_agent(target: TargetConfig, task: str):
    model = build_model(task)
    tools = build_tools(target)
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=CHATDO_SYSTEM_PROMPT,
    )
    return agent

def run_agent(target: TargetConfig, task: str, thread_id: Optional[str] = None, skip_web_search: bool = False) -> tuple[Union[str, Dict[str, Any]], str, str]:
    """
    Run ChatDO on a given task using AI-Router.
    If thread_id is provided, load/save conversation history so the agent has long-term context.
    If skip_web_search is True, skip web search even if intent is web_search (e.g., when RAG context is provided).
    """
    # Classify intent from user message
    intent = classify_intent(task)
    print(f"[INTENT] Classified '{task[:100]}...' as intent: {intent}, skip_web_search: {skip_web_search}")
    
    
    # Handle web search - use Brave Search API, return structured results (no LLM by default)
    # Skip web search if RAG context is provided (skip_web_search=True)
    if intent == "web_search":
        if skip_web_search:
            print(f"[WEB_SEARCH] Skipping web search (RAG context provided)")
        else:
            print(f"[WEB_SEARCH] Triggering web search for query: {task}")
    else:
        print(f"[WEB_SEARCH] Intent is '{intent}', not 'web_search' - will use general chat")
    
    if intent == "web_search" and not skip_web_search:
        # Extract search query from task
        search_query = task
        for prefix in ["find", "search for", "look for", "what are", "show me", "get me"]:
            if task.lower().startswith(prefix):
                search_query = task[len(prefix):].strip()
                break
        
        # Perform web search using Brave Search API
        try:
            search_results = web_search.search_web(search_query, max_results=10)
            if search_results and len(search_results) > 0:
                # Return structured results (no LLM call, no summarization)
                structured_result = {
                    "type": "web_search_results",
                    "query": search_query,
                    "provider": "brave",
                    "results": search_results
                }
                
                # Set model/provider for web search
                model_display = "Brave Search"
                provider = "brave_search"
                
                # Save to memory store if thread_id is provided
                if thread_id:
                    history = memory_store.load_thread_history(target.name, thread_id)
                    # Add user message
                    history.append({"role": "user", "content": task})
                    # Add assistant message with structured data
                    assistant_message = {
                        "role": "assistant",
                        "content": "",  # Empty content for structured messages
                        "type": "web_search_results",
                        "data": structured_result,
                        "model": model_display,
                        "provider": provider
                    }
                    history.append(assistant_message)
                    memory_store.save_thread_history(target.name, thread_id, history)
                
                return structured_result, model_display, provider
            else:
                error_msg = "No search results found. Please try a different query."
                # Save to memory store if thread_id is provided
                if thread_id:
                    history = memory_store.load_thread_history(target.name, thread_id)
                    history.append({"role": "user", "content": task})
                    history.append({"role": "assistant", "content": error_msg})
                    memory_store.save_thread_history(target.name, thread_id, history)
                return error_msg, "Brave Search", "brave_search"
        except ValueError as e:
            # If API key is missing or invalid, return helpful error message
            error_msg = f"Web search is not configured. {str(e)}"
            # Save to memory store if thread_id is provided
            if thread_id:
                history = memory_store.load_thread_history(target.name, thread_id)
                history.append({"role": "user", "content": task})
                history.append({"role": "assistant", "content": error_msg})
                memory_store.save_thread_history(target.name, thread_id, history)
            return error_msg, "Brave Search", "brave_search"
        except Exception as e:
            # If search fails for other reasons, return error
            error_msg = f"Web search failed: {str(e)}. Please try again or check your BRAVE_SEARCH_API_KEY configuration."
            # Save to memory store if thread_id is provided
            if thread_id:
                history = memory_store.load_thread_history(target.name, thread_id)
                history.append({"role": "user", "content": task})
                history.append({"role": "assistant", "content": error_msg})
                memory_store.save_thread_history(target.name, thread_id, history)
            return error_msg, "Brave Search", "brave_search"
    
    # Build message history
    messages: List[Dict[str, str]] = []
    
    # Get the actual model ID (cached to avoid extra API calls)
    # This allows us to include it in the system prompt so the model knows its exact identifier
    global _cached_model_id
    if _cached_model_id is None:
        try:
            _, _cached_model_id = call_ai_router(
                [{"role": "system", "content": "test"}, {"role": "user", "content": "ping"}],
                intent="general_chat"
            )
        except Exception:
            # Fallback if we can't get model ID
            _cached_model_id = "gpt-5"
    
    model_id = _cached_model_id
    
    # Include model ID in system prompt so model can see it
    system_prompt = f"""{CHATDO_SYSTEM_PROMPT}

IMPORTANT: Your exact backend model identifier is: {model_id}
When asked about your specific model, you should state this exact identifier: {model_id}

You are ChatDO, the Director for the user's local codebase.

Behavior rules:

- The human is always the Owner. Never ask who they are or what role they are in.

- You are responsible for planning and coordinating changes to the repository.

- Cursor (the IDE) is the Executor that actually edits files and runs commands.

File handling:
- When the user uploads a file and includes its content in the message (marked with [File: filename] followed by the content), the content is already extracted and available to you.
- You should process the content directly without asking for permission or mentioning file paths.
- If the user asks you to summarize, analyze, or work with uploaded file content, do so immediately and conversationally.
- Only reference the filename, not internal file paths or storage locations.

When the user is exploring ideas, asking questions, or designing a solution:

- Respond conversationally.

- Propose clear, concrete plans.

- Explain which files and components you intend to touch.

Web Search & Information Discovery:
- **IMPORTANT: When the user asks about current events, news, latest information, or anything requiring up-to-date data, you should automatically use web search. Do NOT ask for permission - just search and provide results.**
- When the user asks you to search the web, find information, discover websites, or get current information, use your web search capabilities immediately.
- For queries like "find XYZ", "what are the top headlines", "search for zkSNARK websites", "latest news", "current events", provide comprehensive, up-to-date information.
- You can search for current events, recent developments, and discover relevant websites or resources.
- **CRITICAL: When providing information from web search or article summaries, you MUST cite the source URL for every fact, claim, or piece of information you mention.**
- Format citations clearly: use [Source: URL] or (Source: URL) after each relevant statement.
- If information comes from multiple sources, cite each source separately.
- Always include the full URL so users can verify the information themselves.

When the user clearly asks you to APPLY or IMPLEMENT changes (for example: "yes, do it", "apply this", "make those changes", "go ahead and implement that plan"):

1. Briefly confirm what you are about to do in plain language.

2. THEN emit a <TASKS> block containing ONLY a JSON object describing the work you want the Executor to perform.

The <TASKS> block MUST follow these rules:

- Start with the literal line: <TASKS>

- Then a single JSON object on the following lines.

- Then a line with: </TASKS>

- Do NOT wrap the JSON in markdown code fences.

- Do NOT add commentary inside the <TASKS> block.

- Outside the <TASKS> block, you may speak normally.

The JSON object MUST have this shape:

{{
  "tasks": [
    {{
      "type": "edit_file",
      "path": "relative/path/from/repo/root.ext",
      "intent": "Short description of the change",
      "before": "Snippet or anchor text to replace",
      "after": "Full replacement snippet that should appear instead"
    }},
    {{
      "type": "create_file",
      "path": "relative/path/from/repo/root.ext",
      "content": "Full file content"
    }},
    {{
      "type": "run_command",
      "cwd": "relative/working/dir/or_dot",
      "command": "shell command to run, e.g. 'pnpm test -- AiSpendIndicator.test.tsx'"
    }}
  ]
}}

Notes:

- "before" in edit_file should be an exact snippet or a very clear anchor that actually exists in the target file.

- "after" should be the full replacement for that snippet, not a diff.

- Use as few tasks as possible to implement the requested changes cleanly.

- If you are not confident a snippet exists, first ask the user for confirmation or suggest a different anchor.
"""
    
    # System message is always first
    messages.append({"role": "system", "content": system_prompt})
    
    if thread_id:
        prior = memory_store.load_thread_history(target.name, thread_id)
        # Prior history should not include system message; only user/assistant.
        # We append after the system message.
        messages.extend(prior)
    
    # Current user turn
    messages.append({"role": "user", "content": task})
    
    # Call AI-Router instead of direct model
    assistant_messages, model_id, provider_id, model_display = call_ai_router(messages, intent=intent)
    
    # Extract content from the last assistant message
    if assistant_messages and len(assistant_messages) > 0:
        final_content = assistant_messages[-1].get("content", "")
    else:
        final_content = ""
    
    # Update memory if thread_id is provided
    # CRITICAL: Never save RAG context preamble or system metadata to history
    # Only save actual user messages and assistant responses
    if thread_id:
        # We store only user/assistant messages, not system
        history = memory_store.load_thread_history(target.name, thread_id)
        print(f"[DIAG] run_agent: Before saving, history has {len(history)} messages")
        
        # Check if task contains RAG context preamble (should be filtered by caller, but double-check)
        # RAG context typically starts with "You have access to the following reference documents"
        # or contains "----\nSource:" markers
        task_to_save = task
        if "You have access to the following reference documents" in task or "----\nSource:" in task or "User question:" in task:
            # Extract just the user question part (after "User question:")
            if "User question:" in task:
                task_to_save = task.split("User question:")[-1].strip()
                print(f"[DIAG] run_agent: Detected RAG context in task, extracted user question (length: {len(task_to_save)} vs {len(task)})")
            else:
                # If we can't extract, don't save this message - it's RAG metadata
                print(f"[DIAG] run_agent: WARNING - Task contains RAG context but no 'User question:' marker. NOT saving to history.")
                print(f"[DIAG] run_agent: Task preview: {task[:200]}...")
                # Don't save the user message, only save assistant response
                history.append({"role": "assistant", "content": final_content})
                memory_store.save_thread_history(target.name, thread_id, history)
                print(f"[DIAG] run_agent: Saved only assistant message (skipped RAG context user message)")
                return final_content, model_display, provider_id
        
        # Only save if message is reasonable length (not a full document dump)
        if len(task_to_save) > 5000:
            print(f"[DIAG] run_agent: WARNING - Task is too long ({len(task_to_save)} chars), likely contains full document text. NOT saving to history.")
            # Don't save the user message, only save assistant response
            history.append({"role": "assistant", "content": final_content})
            memory_store.save_thread_history(target.name, thread_id, history)
            print(f"[DIAG] run_agent: Saved only assistant message (skipped oversized user message)")
            return final_content, model_display, provider_id
        
        history.append({"role": "user", "content": task_to_save})
        history.append({"role": "assistant", "content": final_content})
        print(f"[DIAG] run_agent: Saving user message (length={len(task_to_save)}), assistant message (length={len(final_content)})")
        print(f"[DIAG] run_agent: User message preview: {task_to_save[:100]}...")
        memory_store.save_thread_history(target.name, thread_id, history)
        print(f"[DIAG] run_agent: After saving, history has {len(history)} messages")
    
    return final_content, model_display, provider_id
