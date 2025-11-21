"""
FastAPI server for ChatDO v1.5
Provides REST API and WebSocket endpoints for the ChatGPT-style UI
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import json
import uuid
import re
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables from .env file in project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Add parent directory to path to import chatdo
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatdo.config import load_target, TargetConfig
from chatdo.agents.main_agent import run_agent
from chatdo.memory.store import delete_thread_history, load_thread_history
from chatdo.executor import parse_tasks_block, apply_tasks
from server.uploads import handle_file_upload
from server.scraper import scrape_url
from server.ws import websocket_endpoint

# Retention settings
RETENTION_DAYS = int(os.getenv("CHATDO_TRASH_RETENTION_DAYS", "30"))

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


# Chat metadata models
class Chat(BaseModel):
    id: str
    project_id: str
    title: str
    thread_id: str
    created_at: str
    updated_at: str
    trashed: bool = False
    trashed_at: Optional[str] = None


class ChatCreate(BaseModel):
    project_id: str
    title: str
    thread_id: str


class ChatUpdate(BaseModel):
    title: Optional[str] = None


# Helper functions for chat persistence
def get_chats_path() -> Path:
    """Get the path to chats.json"""
    return Path(__file__).parent / "data" / "chats.json"


def load_chats() -> List[dict]:
    """Load chats from chats.json"""
    chats_path = get_chats_path()
    if not chats_path.exists():
        return []
    
    with open(chats_path, "r") as f:
        return json.load(f)


def save_chats(chats: List[dict]) -> None:
    """Save chats to chats.json"""
    chats_path = get_chats_path()
    chats_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(chats_path, "w") as f:
        json.dump(chats, f, indent=2)


def get_active_chats(chats: List[dict]) -> List[dict]:
    """Get chats that are not trashed"""
    return [c for c in chats if not c.get("trashed", False)]


def get_trashed_chats(chats: List[dict]) -> List[dict]:
    """Get chats that are trashed"""
    return [c for c in chats if c.get("trashed", False)]


def now_iso() -> str:
    """Get current UTC time as ISO8601 string"""
    return datetime.now(timezone.utc).isoformat()


def purge_trashed_chats() -> int:
    """
    Permanently delete chats that have been in trash longer than RETENTION_DAYS.
    Returns the number of chats purged.
    """
    chats = load_chats()
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    purged_count = 0
    
    chats_to_purge = []
    for chat in chats:
        if chat.get("trashed", False) and chat.get("trashed_at"):
            try:
                trashed_at = datetime.fromisoformat(chat["trashed_at"].replace("Z", "+00:00"))
                if trashed_at < cutoff_date:
                    chats_to_purge.append(chat)
            except (ValueError, KeyError):
                # Invalid date format, skip
                continue
    
    # Purge each chat
    for chat in chats_to_purge:
        # Delete thread history
        project = None
        projects = load_projects()
        for p in projects:
            if p.get("id") == chat.get("project_id"):
                project = p
                break
        
        if project:
            target_name = project.get("default_target", "general")
            thread_id = chat.get("thread_id")
            if thread_id:
                try:
                    delete_thread_history(target_name, thread_id)
                except Exception as e:
                    print(f"Warning: Failed to delete thread history for {thread_id}: {e}")
        
        # Remove from chats list
        chats = [c for c in chats if c.get("id") != chat.get("id")]
        purged_count += 1
    
    if purged_count > 0:
        save_chats(chats)
    
    return purged_count


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: purge old trashed chats
    purged = purge_trashed_chats()
    if purged > 0:
        print(f"Purged {purged} trashed chats older than {RETENTION_DAYS} days")
    yield
    # Shutdown (if needed)


app = FastAPI(title="ChatDO API", version="1.5.0", lifespan=lifespan)

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
    provider: Optional[str] = None
    message_type: Optional[str] = None  # 'text' (default) or 'web_search_results'
    message_data: Optional[Dict[str, Any]] = None  # Structured data for special message types


class NewConversationRequest(BaseModel):
    project_id: str


class NewConversationResponse(BaseModel):
    conversation_id: str


class Project(BaseModel):
    id: str
    name: str
    default_target: str
    sort_index: int = 0


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: str


# Helper functions for project persistence
def get_projects_path() -> Path:
    """Get the path to projects.json"""
    return Path(__file__).parent / "data" / "projects.json"


def load_projects() -> List[dict]:
    """Load projects from projects.json, ensuring sort_index exists and sorting by it"""
    projects_path = get_projects_path()
    if not projects_path.exists():
        return []
    
    with open(projects_path, "r") as f:
        projects = json.load(f)
    
    # Ensure all projects have sort_index (assign based on current order if missing)
    needs_save = False
    for i, project in enumerate(projects):
        if "sort_index" not in project:
            project["sort_index"] = i
            needs_save = True
    
    # Sort by sort_index, then by name as tie-breaker
    projects.sort(key=lambda p: (p.get("sort_index", 0), p.get("name", "")))
    
    # Save if we added sort_index to any projects
    if needs_save:
        save_projects(projects)
    
    return projects


def save_projects(projects: List[dict]) -> None:
    """Save projects to projects.json"""
    projects_path = get_projects_path()
    projects_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(projects_path, "w") as f:
        json.dump(projects, f, indent=2)


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name"""
    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def generate_project_id() -> str:
    """Generate a unique project ID"""
    return str(uuid.uuid4())


@app.get("/")
async def root():
    return {"message": "ChatDO API v1.5", "status": "running"}


@app.get("/api/projects", response_model=List[Project])
async def get_projects():
    """Return list of available projects, ensuring General exists"""
    projects = load_projects()
    
    # Ensure General project exists
    general_project = next((p for p in projects if p.get("name") == "General"), None)
    if not general_project:
        # Create General project
        general_project = {
            "id": str(uuid.uuid4()),
            "name": "General",
            "default_target": "general",
            "sort_index": 0,
            "created_at": now_iso(),
            "updated_at": now_iso()
        }
        projects.insert(0, general_project)
        save_projects(projects)
    
    return projects


@app.post("/api/projects", response_model=Project)
async def create_project(project_data: ProjectCreate):
    """Create a new project"""
    projects = load_projects()
    
    # Generate ID and slug
    project_id = generate_project_id()
    slug = generate_slug(project_data.name)
    
    # Create new project with sort_index at the end
    new_project = {
        "id": project_id,
        "name": project_data.name.strip(),
        "default_target": "general",  # Default target for new projects
        "sort_index": len(projects)  # Add at the end
    }
    
    projects.append(new_project)
    save_projects(projects)
    
    return new_project


@app.patch("/api/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, project_data: ProjectUpdate):
    """Update an existing project"""
    projects = load_projects()
    
    # Find project by ID
    project_index = None
    for i, p in enumerate(projects):
        if p.get("id") == project_id:
            project_index = i
            break
    
    if project_index is None:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Update project name
    projects[project_index]["name"] = project_data.name.strip()
    save_projects(projects)
    
    return projects[project_index]


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project"""
    projects = load_projects()
    
    # Find and remove project
    original_count = len(projects)
    projects = [p for p in projects if p.get("id") != project_id]
    
    if len(projects) == original_count:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Reindex remaining projects to maintain sequential sort_index
    for i, project in enumerate(projects):
        project["sort_index"] = i
    
    save_projects(projects)
    return {"success": True}


@app.post("/api/projects/reorder", response_model=List[Project])
async def reorder_projects(order: List[str]):
    """
    Reorder projects based on the provided array of project IDs.
    Updates sort_index for each project to match the new order.
    """
    projects = load_projects()
    
    # Create a map of project ID to project for quick lookup
    project_map = {p.get("id"): p for p in projects}
    
    # Update sort_index for projects in the order list
    reordered_projects = []
    for index, project_id in enumerate(order):
        if project_id in project_map:
            project = project_map[project_id]
            project["sort_index"] = index
            reordered_projects.append(project)
    
    # Add any projects not in the order list (defensive - shouldn't happen)
    for project in projects:
        if project.get("id") not in order:
            project["sort_index"] = len(reordered_projects)
            reordered_projects.append(project)
    
    # Sort to ensure consistency
    reordered_projects.sort(key=lambda p: (p.get("sort_index", 0), p.get("name", "")))
    
    save_projects(reordered_projects)
    return reordered_projects


@app.post("/api/new_conversation", response_model=NewConversationResponse)
async def new_conversation(request: NewConversationRequest):
    """Create a new conversation thread"""
    conversation_id = str(uuid.uuid4())
    
    # Create chat metadata entry
    chats = load_chats()
    projects = load_projects()
    project = next((p for p in projects if p.get("id") == request.project_id), None)
    target_name = project.get("default_target", "general") if project else "general"
    
    new_chat = {
        "id": conversation_id,
        "project_id": request.project_id,
        "title": "New Chat",
        "thread_id": conversation_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "trashed": False,
        "trashed_at": None
    }
    
    chats.append(new_chat)
    save_chats(chats)
    
    return NewConversationResponse(conversation_id=conversation_id)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint - calls ChatDO's run_agent()
    """
    try:
        # Load target configuration
        target_cfg = load_target(request.target_name)
        
        # 1) Get raw response from ChatDO (may include <TASKS> block or structured results)
        raw_result, model_display, provider = run_agent(
            target=target_cfg,
            task=request.message,
            thread_id=request.conversation_id
        )
        
        # 2) Check if result is structured (web_search_results)
        if isinstance(raw_result, dict) and raw_result.get("type") == "web_search_results":
            # Return structured web search results
            return ChatResponse(
                reply="",  # Empty reply for structured messages
                message_type="web_search_results",
                message_data=raw_result,
                model_used=model_display,
                provider=provider
            )
        
        # 3) Split out any <TASKS> block
        human_text, tasks_json = split_tasks_block(raw_result)
        
        # 4) If no tasks, behave exactly like before
        if not tasks_json:
            return ChatResponse(reply=human_text, model_used=model_display, provider=provider)
        
        # 5) Parse tasks from JSON
        try:
            tasks = parse_tasks_block(tasks_json)
        except Exception as e:
            # If parsing fails, show error but still return the human text
            error_note = f"\n\n---\nExecutor error: could not parse tasks JSON ({e})."
            return ChatResponse(reply=human_text + error_note)
        
        # 6) Execute tasks against the target repo
        exec_result = apply_tasks(target_cfg, tasks)
        
        # 7) Build a human-readable summary
        summary_lines = [exec_result.summary()]
        for r in exec_result.results:
            prefix = "✅" if r.status == "success" else "❌"
            summary_lines.append(f"{prefix} {r.message}")
        
        summary_text = "\n".join(summary_lines)
        
        # 8) Append summary to what the user sees
        final_message = human_text + "\n\n---\nExecutor summary:\n" + summary_text
        
        return ChatResponse(reply=final_message, model_used=model_display, provider=provider)
    
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()  # Print full traceback to server logs
        raise HTTPException(status_code=500, detail=error_detail)


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


@app.get("/uploads/{file_path:path}")
async def serve_uploaded_file(file_path: str):
    """
    Serve uploaded files for preview
    """
    from fastapi.responses import FileResponse
    
    uploads_dir = Path(__file__).parent.parent / "uploads"
    file_full_path = uploads_dir / file_path
    
    # Security: ensure file is within uploads directory
    try:
        file_full_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_full_path)


@app.get("/api/pptx-preview/{file_path:path}")
async def preview_pptx(file_path: str):
    """
    Convert PPTX to PDF for browser preview (same beautiful experience as PDFs!)
    Returns the PDF file for iframe display
    """
    from fastapi.responses import FileResponse
    import subprocess
    import tempfile
    
    uploads_dir = Path(__file__).parent.parent / "uploads"
    file_full_path = uploads_dir / file_path
    
    # Security check
    try:
        file_full_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_full_path.exists() or not file_full_path.suffix.lower() in ['.pptx', '.ppt']:
        raise HTTPException(status_code=404, detail="File not found or not a PowerPoint file")
    
    # Check if we already have a converted PDF cached
    pdf_path = file_full_path.with_suffix('.pdf')
    if pdf_path.exists():
        return FileResponse(pdf_path, media_type='application/pdf')
    
    # Try to convert PPTX to PDF using LibreOffice (best quality)
    try:
        # Try multiple possible LibreOffice command paths
        libreoffice_commands = [
            '/opt/homebrew/bin/soffice',  # Homebrew on Apple Silicon (most common)
            '/usr/local/bin/soffice',  # Homebrew on Intel
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',  # macOS app bundle
            'soffice',  # If in PATH
            'libreoffice',  # Alternative command name
        ]
        
        libreoffice_cmd = None
        for cmd in libreoffice_commands:
            try:
                # Check if command exists
                if cmd.startswith('/'):
                    # Absolute path - check if file exists
                    import os
                    if os.path.exists(cmd) and os.access(cmd, os.X_OK):
                        libreoffice_cmd = cmd
                        break
                else:
                    # Command name - use which
                    result = subprocess.run(
                        ['which', cmd],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        libreoffice_cmd = result.stdout.decode().strip()
                        break
            except:
                continue
        
        if libreoffice_cmd:
            try:
                # Use LibreOffice headless to convert
                result = subprocess.run(
                    [
                        libreoffice_cmd,
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', str(pdf_path.parent),
                        str(file_full_path)
                    ],
                    capture_output=True,
                    timeout=60,
                    check=False
                )
                
                if result.returncode == 0 and pdf_path.exists():
                    return FileResponse(pdf_path, media_type='application/pdf')
                else:
                    # Conversion failed - log error but continue to fallback
                    error_msg = result.stderr.decode() if result.stderr else result.stdout.decode() if result.stdout else 'Unknown error'
                    print(f"LibreOffice conversion failed (code {result.returncode}): {error_msg}")
            except Exception as e:
                print(f"LibreOffice conversion error: {e}")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        # Fallback: Try python-pptx + reportlab (limited but works)
        try:
            from pptx import Presentation
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.units import inch
            
            prs = Presentation(file_full_path)
            
            # Create PDF
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            width, height = letter
            
            for slide_num, slide in enumerate(prs.slides, 1):
                if slide_num > 1:
                    c.showPage()
                
                y = height - 50
                # Add slide number
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, y, f"Slide {slide_num}")
                y -= 30
                
                # Extract and add title
                if slide.shapes.title and slide.shapes.title.text:
                    c.setFont("Helvetica-Bold", 14)
                    title_lines = slide.shapes.title.text.split('\n')
                    for line in title_lines[:3]:  # Limit to 3 lines
                        if y < 100:
                            break
                        c.drawString(50, y, line[:80])  # Limit width
                        y -= 20
                    y -= 10
                
                # Add text content
                c.setFont("Helvetica", 11)
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text and shape != slide.shapes.title:
                        text = shape.text.strip()
                        if text and y > 100:
                            # Wrap text
                            lines = text.split('\n')
                            for line in lines[:10]:  # Limit lines per slide
                                if y < 100:
                                    break
                                # Simple word wrap
                                words = line.split()
                                current_line = ""
                                for word in words:
                                    if len(current_line + word) < 80:
                                        current_line += word + " "
                                    else:
                                        if current_line:
                                            c.drawString(70, y, current_line.strip())
                                            y -= 15
                                        current_line = word + " "
                                if current_line and y > 100:
                                    c.drawString(70, y, current_line.strip())
                                    y -= 15
                                y -= 5
                
            c.save()
            
            if pdf_path.exists():
                return FileResponse(pdf_path, media_type='application/pdf')
            else:
                raise Exception("PDF creation failed")
                
        except ImportError:
            # No conversion libraries available
            raise HTTPException(
                status_code=501, 
                detail="PPTX to PDF conversion not available. Install LibreOffice or python libraries (reportlab, python-pptx) for preview support."
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error converting PPTX to PDF: {str(e)}")


@app.get("/api/xlsx-preview/{file_path:path}")
async def preview_xlsx(file_path: str):
    """
    Convert Excel (.xlsx, .xls) to PDF for browser preview (same beautiful experience as PDFs!)
    Returns the PDF file for iframe display
    """
    from fastapi.responses import FileResponse
    import subprocess
    
    uploads_dir = Path(__file__).parent.parent / "uploads"
    file_full_path = uploads_dir / file_path
    
    # Security check
    try:
        file_full_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_full_path.exists() or not file_full_path.suffix.lower() in ['.xlsx', '.xls']:
        raise HTTPException(status_code=404, detail="File not found or not an Excel file")
    
    # Check if we already have a converted PDF cached
    pdf_path = file_full_path.with_suffix('.pdf')
    if pdf_path.exists():
        return FileResponse(pdf_path, media_type='application/pdf')
    
    # Try to convert Excel to PDF using LibreOffice (best quality)
    try:
        # Try multiple possible LibreOffice command paths
        libreoffice_commands = [
            '/opt/homebrew/bin/soffice',  # Homebrew on Apple Silicon (most common)
            '/usr/local/bin/soffice',  # Homebrew on Intel
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',  # macOS app bundle
            'soffice',  # If in PATH
            'libreoffice',  # Alternative command name
        ]
        
        libreoffice_cmd = None
        for cmd in libreoffice_commands:
            try:
                # Check if command exists
                if cmd.startswith('/'):
                    # Absolute path - check if file exists
                    import os
                    if os.path.exists(cmd) and os.access(cmd, os.X_OK):
                        libreoffice_cmd = cmd
                        break
                else:
                    # Command name - use which
                    result = subprocess.run(
                        ['which', cmd],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        libreoffice_cmd = result.stdout.decode().strip()
                        break
            except:
                continue
        
        if libreoffice_cmd:
            try:
                # Use LibreOffice headless to convert
                result = subprocess.run(
                    [
                        libreoffice_cmd,
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', str(pdf_path.parent),
                        str(file_full_path)
                    ],
                    capture_output=True,
                    timeout=60,
                    check=False
                )
                
                if result.returncode == 0 and pdf_path.exists():
                    return FileResponse(pdf_path, media_type='application/pdf')
                else:
                    # Conversion failed - log error but continue to fallback
                    error_msg = result.stderr.decode() if result.stderr else result.stdout.decode() if result.stdout else 'Unknown error'
                    print(f"LibreOffice Excel conversion failed (code {result.returncode}): {error_msg}")
            except Exception as e:
                print(f"LibreOffice Excel conversion error: {e}")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        pass
    
    # If all conversion attempts failed, return error
    raise HTTPException(status_code=500, detail="Excel to PDF conversion not available. Install LibreOffice for preview support.")


@app.get("/api/docx-preview/{file_path:path}")
async def preview_docx(file_path: str):
    """
    Convert Word (.docx, .doc) to PDF for browser preview (same beautiful experience as PDFs!)
    Returns the PDF file for iframe display
    """
    from fastapi.responses import FileResponse
    import subprocess
    
    uploads_dir = Path(__file__).parent.parent / "uploads"
    file_full_path = uploads_dir / file_path
    
    # Security check
    try:
        file_full_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_full_path.exists() or not file_full_path.suffix.lower() in ['.docx', '.doc']:
        raise HTTPException(status_code=404, detail="File not found or not a Word document")
    
    # Check if we already have a converted PDF cached
    pdf_path = file_full_path.with_suffix('.pdf')
    if pdf_path.exists():
        return FileResponse(pdf_path, media_type='application/pdf')
    
    # Try to convert Word to PDF using LibreOffice (best quality)
    try:
        # Try multiple possible LibreOffice command paths
        libreoffice_commands = [
            '/opt/homebrew/bin/soffice',  # Homebrew on Apple Silicon (most common)
            '/usr/local/bin/soffice',  # Homebrew on Intel
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',  # macOS app bundle
            'soffice',  # If in PATH
            'libreoffice',  # Alternative command name
        ]
        
        libreoffice_cmd = None
        for cmd in libreoffice_commands:
            try:
                # Check if command exists
                if cmd.startswith('/'):
                    # Absolute path - check if file exists
                    import os
                    if os.path.exists(cmd) and os.access(cmd, os.X_OK):
                        libreoffice_cmd = cmd
                        break
                else:
                    # Command name - use which
                    result = subprocess.run(
                        ['which', cmd],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        libreoffice_cmd = result.stdout.decode().strip()
                        break
            except:
                continue
        
        if libreoffice_cmd:
            try:
                # Use LibreOffice headless to convert
                result = subprocess.run(
                    [
                        libreoffice_cmd,
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', str(pdf_path.parent),
                        str(file_full_path)
                    ],
                    capture_output=True,
                    timeout=60,
                    check=False
                )
                
                if result.returncode == 0 and pdf_path.exists():
                    return FileResponse(pdf_path, media_type='application/pdf')
                else:
                    # Conversion failed - log error but continue to fallback
                    error_msg = result.stderr.decode() if result.stderr else result.stdout.decode() if result.stdout else 'Unknown error'
                    print(f"LibreOffice Word conversion failed (code {result.returncode}): {error_msg}")
            except Exception as e:
                print(f"LibreOffice Word conversion error: {e}")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        pass
    
    # If all conversion attempts failed, return error
    raise HTTPException(status_code=500, detail="Word to PDF conversion not available. Install LibreOffice for preview support.")


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


@app.get("/api/chats", response_model=List[Chat])
async def get_chats(
    project_id: Optional[str] = Query(None),
    include_trashed: bool = Query(False)
):
    """Get chats, optionally filtered by project and including trashed"""
    chats = load_chats()
    projects = load_projects()
    
    # Ensure General project exists
    general_project = next((p for p in projects if p.get("name") == "General"), None)
    if not general_project:
        general_project = {
            "id": str(uuid.uuid4()),
            "name": "General",
            "default_target": "general",
            "sort_index": 0,
            "created_at": now_iso(),
            "updated_at": now_iso()
        }
        projects.insert(0, general_project)
        save_projects(projects)
    
    # Assign orphaned chats (without project_id) to General
    needs_save = False
    for chat in chats:
        if not chat.get("project_id"):
            chat["project_id"] = general_project["id"]
            chat["updated_at"] = now_iso()
            needs_save = True
    
    if needs_save:
        save_chats(chats)
    
    # Filter by project if specified
    if project_id:
        chats = [c for c in chats if c.get("project_id") == project_id]
    
    # Filter trashed if not including them
    if not include_trashed:
        chats = get_active_chats(chats)
    
    return chats


@app.get("/api/chats/{chat_id}/messages")
async def get_chat_messages(chat_id: str, limit: Optional[int] = None):
    """Get messages for a specific chat conversation
    
    Args:
        chat_id: The chat ID
        limit: Optional limit on number of messages to return (for previews)
    """
    chats = load_chats()
    chat = next((c for c in chats if c.get("id") == chat_id), None)
    
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Get project to find target_name
    projects = load_projects()
    project = next((p for p in projects if p.get("id") == chat.get("project_id")), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    target_name = project.get("default_target", "general")
    thread_id = chat.get("thread_id")
    
    if not thread_id:
        return {"messages": []}
    
    # Load messages from memory store
    history = load_thread_history(target_name, thread_id)
    
    # Convert to frontend format
    messages = []
    for msg in history:
        # Skip system messages for display
        if msg.get("role") == "system":
            continue
        messages.append({
            "role": msg.get("role"),
            "content": msg.get("content", "")
        })
    
    # If limit is specified, return only the last N messages (for previews)
    if limit and limit > 0:
        messages = messages[-limit:]
    
    return {"messages": messages}


@app.patch("/api/chats/{chat_id}", response_model=Chat)
async def update_chat(chat_id: str, chat_data: ChatUpdate):
    """Update a chat (e.g., rename)"""
    chats = load_chats()
    
    # Find chat by ID
    chat_index = None
    for i, c in enumerate(chats):
        if c.get("id") == chat_id:
            chat_index = i
            break
    
    if chat_index is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Update chat fields
    if chat_data.title is not None:
        chats[chat_index]["title"] = chat_data.title.strip()
        chats[chat_index]["updated_at"] = now_iso()
    
    save_chats(chats)
    return chats[chat_index]


@app.delete("/api/chats/{chat_id}", response_model=Chat)
async def soft_delete_chat(chat_id: str):
    """Soft delete a chat (move to trash)"""
    chats = load_chats()
    
    # Find chat by ID
    chat_index = None
    for i, c in enumerate(chats):
        if c.get("id") == chat_id:
            chat_index = i
            break
    
    if chat_index is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Soft delete
    chats[chat_index]["trashed"] = True
    chats[chat_index]["trashed_at"] = now_iso()
    chats[chat_index]["updated_at"] = now_iso()
    
    save_chats(chats)
    return chats[chat_index]


@app.post("/api/chats/{chat_id}/restore", response_model=Chat)
async def restore_chat(chat_id: str):
    """Restore a chat from trash"""
    chats = load_chats()
    
    # Find chat by ID
    chat_index = None
    for i, c in enumerate(chats):
        if c.get("id") == chat_id:
            chat_index = i
            break
    
    if chat_index is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Restore
    chats[chat_index]["trashed"] = False
    chats[chat_index]["trashed_at"] = None
    chats[chat_index]["updated_at"] = now_iso()
    
    save_chats(chats)
    return chats[chat_index]


@app.post("/api/chats/{chat_id}/purge")
async def purge_chat(chat_id: str):
    """Permanently delete a chat and its thread history"""
    chats = load_chats()
    
    # Find chat by ID
    chat = None
    for c in chats:
        if c.get("id") == chat_id:
            chat = c
            break
    
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Delete thread history
    project_id = chat.get("project_id")
    thread_id = chat.get("thread_id")
    
    if project_id and thread_id:
        projects = load_projects()
        project = next((p for p in projects if p.get("id") == project_id), None)
        if project:
            target_name = project.get("default_target", "general")
            try:
                delete_thread_history(target_name, thread_id)
            except Exception as e:
                print(f"Warning: Failed to delete thread history for {thread_id}: {e}")
    
    # Remove from chats list
    chats = [c for c in chats if c.get("id") != chat_id]
    save_chats(chats)
    
    return {"success": True}


@app.post("/api/chats/purge_trashed")
async def purge_trashed_endpoint():
    """Manually trigger purge of old trashed chats"""
    purged_count = purge_trashed_chats()
    return {"success": True, "purged_count": purged_count}


@app.post("/api/chats/purge_all_trashed")
async def purge_all_trashed():
    """Permanently delete ALL trashed chats (regardless of age)"""
    chats = load_chats()
    projects = load_projects()
    
    # Find all trashed chats
    trashed_chat_ids = []
    for chat in chats:
        if chat.get("trashed", False):
            trashed_chat_ids.append(chat.get("id"))
            # Get project to find target_name for thread deletion
            project = next((p for p in projects if p.get("id") == chat.get("project_id")), None)
            target_name = project.get("default_target", "general") if project else "general"
            thread_id = chat.get("thread_id")
            
            # Delete thread history if it exists
            if thread_id:
                try:
                    delete_thread_history(target_name, thread_id)
                except Exception as e:
                    print(f"Warning: Failed to delete thread history for {thread_id}: {e}")
    
    # Remove all trashed chats from the list
    chats = [c for c in chats if not c.get("trashed", False)]
    save_chats(chats)
    
    return {"success": True, "purged_count": len(trashed_chat_ids)}


@app.websocket("/api/chat/stream")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat responses
    """
    await websocket_endpoint(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

