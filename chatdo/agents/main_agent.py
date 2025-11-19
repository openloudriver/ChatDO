from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
import os
import requests
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools
from ..memory import store as memory_store

# AI-Router HTTP client
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")

# Cache the model ID to avoid making a preliminary call on every request
_cached_model_id: Optional[str] = None

def classify_intent(text: str) -> str:
    """Classify user message intent for AI-Router routing."""
    t = text.lower()
    
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

def call_ai_router(messages: List[Dict[str, str]], intent: str = "general_chat") -> tuple[List[Dict[str, str]], str]:
    """
    Call the AI-Router HTTP service to get AI responses.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        intent: AI intent type (e.g., "general_chat", "long_planning", "code_edit")
    
    Returns:
        Tuple of (list of assistant messages from the router, model_id)
    """
    payload = {
        "role": "chatdo",
        "intent": intent,
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": messages,
        },
    }
    try:
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"AI-Router error: {data.get('error')}")
        model_id = data.get("modelId", "gpt-5")
        return data["output"]["messages"], model_id
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

def run_agent(target: TargetConfig, task: str, thread_id: Optional[str] = None) -> str:
    """
    Run ChatDO on a given task using AI-Router.
    If thread_id is provided, load/save conversation history so the agent has long-term context.
    """
    # Classify intent from user message
    intent = classify_intent(task)
    
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

When the user is exploring ideas, asking questions, or designing a solution:

- Respond conversationally.

- Propose clear, concrete plans.

- Explain which files and components you intend to touch.

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
    assistant_messages, _ = call_ai_router(messages, intent=intent)
    
    # Extract content from the last assistant message
    if assistant_messages and len(assistant_messages) > 0:
        final_content = assistant_messages[-1].get("content", "")
    else:
        final_content = ""
    
    # Update memory if thread_id is provided
    if thread_id:
        # We store only user/assistant messages, not system
        history = memory_store.load_thread_history(target.name, thread_id)
        history.append({"role": "user", "content": task})
        history.append({"role": "assistant", "content": final_content})
        memory_store.save_thread_history(target.name, thread_id, history)
    
    return final_content
