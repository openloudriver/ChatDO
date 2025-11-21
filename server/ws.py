"""
WebSocket streaming endpoint for ChatDO
Streams ChatDO replies chunk-by-chunk
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatdo.config import load_target
from chatdo.agents.main_agent import run_agent
from chatdo.executor import parse_tasks_block, apply_tasks

# Task execution constants
TASKS_START = "<TASKS>"
TASKS_END = "</TASKS>"


def split_tasks_block(text: str) -> tuple[str, Optional[str]]:
    """
    Split a ChatDO response into (human_text, tasks_json_str | None).
    
    - human_text: original text with any <TASKS>...</TASKS> block removed.
    - tasks_json_str: the raw JSON string inside the <TASKS> block, or None.
    """
    start = text.find(TASKS_START)
    end = text.find(TASKS_END)
    
    if start == -1 or end == -1:
        return text, None
    
    json_str = text[start + len(TASKS_START) : end].strip()
    
    # Remove the block from the human-facing text
    human = (text[:start] + text[end + len(TASKS_END) :]).strip()
    
    return human, json_str


async def stream_chat_response(
    websocket: WebSocket,
    project_id: str,
    conversation_id: str,
    target_name: str,
    message: str
):
    """
    Stream ChatDO response via WebSocket
    For now, we'll simulate streaming by chunking the response
    In the future, we can integrate with actual streaming from the LLM
    """
    try:
        # Load target configuration
        target_cfg = load_target(target_name)
        
        # Run ChatDO agent (this is synchronous, so we'll chunk the result)
        # TODO: In the future, integrate with streaming LLM responses
        raw_result = run_agent(
            target=target_cfg,
            task=message,
            thread_id=conversation_id
        )
        
        # Check if result is structured (web_search_results)
        if isinstance(raw_result, dict) and raw_result.get("type") == "web_search_results":
            # Send structured web search results
            await websocket.send_json({
                "type": "web_search_results",
                "data": raw_result,
                "done": True
            })
            return
        
        # Split out any <TASKS> block
        human_text, tasks_json = split_tasks_block(raw_result)
        
        # Stream human text in chunks (simulate streaming for now)
        chunk_size = 50  # characters per chunk
        for i in range(0, len(human_text), chunk_size):
            chunk = human_text[i:i + chunk_size]
            await websocket.send_json({
                "type": "chunk",
                "content": chunk,
                "done": False
            })
        
        # If there are tasks, execute them and send summary
        if tasks_json:
            try:
                tasks = parse_tasks_block(tasks_json)
                exec_result = apply_tasks(target_cfg, tasks)
                
                # Build summary
                summary_lines = [exec_result.summary()]
                for r in exec_result.results:
                    prefix = "✅" if r.status == "success" else "❌"
                    summary_lines.append(f"{prefix} {r.message}")
                
                summary_text = "\n".join(summary_lines)
                executor_message = "\n\n---\nExecutor summary:\n" + summary_text
                
                # Stream executor summary
                for i in range(0, len(executor_message), chunk_size):
                    chunk = executor_message[i:i + chunk_size]
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk,
                        "done": False
                    })
            except Exception as e:
                # If task execution fails, send error message
                error_note = f"\n\n---\nExecutor error: {e}"
                await websocket.send_json({
                    "type": "chunk",
                    "content": error_note,
                    "done": False
                })
        
        # Send completion message
        await websocket.send_json({
            "type": "done",
            "content": "",
            "done": True
        })
    
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()  # Print full traceback to server logs
        await websocket.send_json({
            "type": "error",
            "content": error_detail,
            "done": True
        })


async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint handler
    Expects JSON messages with: project_id, conversation_id, target_name, message
    """
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            project_id = data.get("project_id")
            conversation_id = data.get("conversation_id")
            target_name = data.get("target_name")
            message = data.get("message")
            
            if not all([project_id, conversation_id, target_name, message]):
                await websocket.send_json({
                    "type": "error",
                    "content": "Missing required fields: project_id, conversation_id, target_name, message",
                    "done": True
                })
                continue
            
            # Stream response
            await stream_chat_response(
                websocket,
                project_id,
                conversation_id,
                target_name,
                message
            )
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()  # Print full traceback to server logs
        try:
            await websocket.send_json({
                "type": "error",
                "content": error_detail,
                "done": True
            })
        except:
            pass  # WebSocket may already be closed

