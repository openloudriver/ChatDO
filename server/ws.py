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
        reply = run_agent(
            target=target_cfg,
            task=message,
            thread_id=conversation_id
        )
        
        # Stream reply in chunks (simulate streaming for now)
        chunk_size = 50  # characters per chunk
        for i in range(0, len(reply), chunk_size):
            chunk = reply[i:i + chunk_size]
            await websocket.send_json({
                "type": "chunk",
                "content": chunk,
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

