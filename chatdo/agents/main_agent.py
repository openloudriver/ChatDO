from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools
from ..memory import store as memory_store

def choose_model(task: str) -> str:
    """Choose which OpenAI model to use based on the task description.

    Routing rules (heuristic, cheap-first where possible):

    - gpt-5.1-2025-11-13
      Heavy, long-form reasoning where you care about reproducibility
      (whitepapers, long specs, governance docs, threat models).

    - gpt-5.1-chat-latest
      High-level architecture / strategy / product design / planning.

    - gpt-5.1-codex
      Non-trivial coding, refactors, tests, debugging.

    - gpt-5.1-codex-mini
      Fast, cheap, day-to-day repo work and small edits.

    - gpt-5.1
      Fallback general model if nothing else matches.
    """
    tl = task.lower()

    # Long-form, reproducible design / governance / threat-model work
    if any(word in tl for word in [
        "whitepaper", "white paper", "spec", "specification", "design doc",
        "requirements", "threat model", "governance", "constitution",
        "bylaws", "policy", "architecture doc", "roadmap"
    ]):
        return "gpt-5.1-2025-11-13"

    # High-level architecture / strategy / planning / product thinking
    if any(word in tl for word in [
        "architecture", "architect", "system design", "strategy",
        "roadmap", "plan", "planning", "high level", "overview",
        "meta", "vision"
    ]):
        return "gpt-5.1-chat-latest"

    # Code-heavy tasks, refactors, testing, debugging
    if any(word in tl for word in [
        "refactor", "rewrite", "migrate", "unit test", "tests", "test suite",
        "bug", "error", "traceback", "stack trace", "lint", "type error",
        "implement", "function", "class", "typescript", "python", "javascript",
        "react", "terraform", "dockerfile", "cursor", "monorepo"
    ]):
        return "gpt-5.1-codex"

    # Default: fast/cheap mini model for small tasks and light edits
    # (most day-to-day repo work should fall back here)
    if len(task) < 400 and "design" not in tl and "architecture" not in tl:
        return "gpt-5.1-codex-mini"

    # Fallback general model
    return "gpt-5.1"

def build_model(task: str):
    """
    Build the chat model for this run, using the model router to
    pick an appropriate model based on the task description.
    
    Uses ChatOpenAI with use_responses_api=True for gpt-5.1 models that require
    the v1/responses endpoint instead of v1/chat/completions.
    """
    model_name = choose_model(task)
    
    # Check if this is a gpt-5.1 model that needs the responses endpoint
    if model_name.startswith("gpt-5.1"):
        return ChatOpenAI(model=model_name, temperature=0.2, use_responses_api=True)
    else:
        # Use standard ChatOpenAI for other models
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
    Run ChatDO on a given task. If thread_id is provided, load/save conversation history
    so the agent has long-term context.
    """
    agent = build_agent(target, task)
    
    # Build message history
    messages: List[Dict[str, Any]] = []
    
    # System message is always first
    messages.append({"role": "system", "content": CHATDO_SYSTEM_PROMPT})
    
    if thread_id:
        prior = memory_store.load_thread_history(target.name, thread_id)
        # Prior history should not include system message; only user/assistant.
        # We append after the system message.
        messages.extend(prior)
    
    # Current user turn
    messages.append({"role": "user", "content": task})
    
    # deepagents expects a structure like {"messages": [...]}
    result = agent.invoke({"messages": messages})
    
    # Extract final assistant message
    final_content = ""
    if isinstance(result, dict) and "messages" in result:
        # result["messages"] is usually a list of LangChain messages
        msgs = result["messages"]
        if msgs:
            last = msgs[-1]
            # handle both LC messages and plain dict-like
            if hasattr(last, "content"):
                content = last.content
                # Handle responses API format which returns a list
                if isinstance(content, list):
                    # Extract text from the list of response objects
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text" and "text" in item:
                                text_parts.append(item["text"])
                            elif "text" in item:
                                text_parts.append(item["text"])
                        elif isinstance(item, str):
                            text_parts.append(item)
                    final_content = " ".join(text_parts) if text_parts else str(content)
                else:
                    final_content = content
            else:
                final_content = str(last)
    else:
        final_content = str(result)
    
    # Update memory if thread_id is provided
    if thread_id:
        # We store only user/assistant messages, not system
        history = memory_store.load_thread_history(target.name, thread_id)
        history.append({"role": "user", "content": task})
        history.append({"role": "assistant", "content": final_content})
        memory_store.save_thread_history(target.name, thread_id, history)
    
    return final_content
