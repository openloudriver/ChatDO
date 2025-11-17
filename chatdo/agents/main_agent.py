from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools
from ..memory import store as memory_store

def build_model():
    # Default: fast, cheap reasoning for day-to-day work.
    return ChatOpenAI(model="gpt-5.1-codex-mini", temperature=0.2)

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

def build_agent(target: TargetConfig):
    model = build_model()
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
    agent = build_agent(target)
    
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
                final_content = last.content
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

