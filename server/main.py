"""
FastAPI server for ChatDO v1.5
Provides REST API and WebSocket endpoints for the ChatGPT-style UI
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path to import chatdo
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatdo.config import load_target
from chatdo.agents.main_agent import run_agent
from .uploads import handle_file_upload
from .scraper import scrape_url
from .ws import websocket_endpoint

app = FastAPI(title="ChatDO API", version="1.5.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    project_id: str
    conversation_id: str
    target_name: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    model_used: Optional[str] = None


class NewConversationRequest(BaseModel):
    project_id: str


class NewConversationResponse(BaseModel):
    conversation_id: str


@app.get("/")
async def root():
    return {"message": "ChatDO API v1.5", "status": "running"}


@app.get("/api/projects")
async def get_projects():
    """Return list of available projects"""
    projects_path = Path(__file__).parent / "data" / "projects.json"
    if not projects_path.exists():
        return JSONResponse(content=[], status_code=200)
    
    import json
    with open(projects_path, "r") as f:
        projects = json.load(f)
    return projects


@app.post("/api/new_conversation", response_model=NewConversationResponse)
async def new_conversation(request: NewConversationRequest):
    """Create a new conversation thread"""
    import uuid
    conversation_id = str(uuid.uuid4())
    return NewConversationResponse(conversation_id=conversation_id)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint - calls ChatDO's run_agent()
    """
    try:
        # Load target configuration
        target_cfg = load_target(request.target_name)
        
        # Run ChatDO agent with thread_id for memory
        reply = run_agent(
            target=target_cfg,
            task=request.message,
            thread_id=request.conversation_id
        )
        
        return ChatResponse(reply=reply)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
async def upload_file(
    project_id: str = Form(...),
    conversation_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Handle file uploads
    Saves to uploads/<project_id>/<conversation_id>/<uuid>.<ext>
    Extracts text if PDF/Word/Excel/PPT/image
    """
    try:
        result = await handle_file_upload(project_id, conversation_id, file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/url")
async def scrape_url_endpoint(
    project_id: str,
    conversation_id: str,
    url: str
):
    """
    Scrape URL content and save to uploads folder
    """
    try:
        result = await scrape_url(project_id, conversation_id, url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/api/chat/stream")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat responses
    """
    await websocket_endpoint(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

