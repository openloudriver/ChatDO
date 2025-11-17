from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI  # or ChatOllama
from pathlib import Path
from typing import Callable
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools

def build_model():
    # For now, assume OpenAI. You can swap to ChatOllama if you want local later.
    # Requires OPENAI_API_KEY in env.
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

def build_agent(target: TargetConfig):
    model = build_model()
    
    # Create wrapper functions for our repo tools
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
    
    tools = [
        list_files_wrapper,
        read_file_wrapper,
        write_file_wrapper,
    ]
    
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=CHATDO_SYSTEM_PROMPT,
    )
    return agent

def run_agent(target: TargetConfig, task: str) -> str:
    agent = build_agent(target)
    # create_deep_agent returns a CompiledStateGraph which can be invoked
    result = agent.invoke({"messages": [("user", task)]})
    # Extract the final message from the result
    if isinstance(result, dict) and "messages" in result:
        messages = result["messages"]
        if messages:
            return str(messages[-1].content if hasattr(messages[-1], "content") else messages[-1])
    return str(result)

