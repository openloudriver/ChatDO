"""
WebSocket streaming endpoint for ChatDO
Streams ChatDO replies chunk-by-chunk
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional, List
import sys
import re
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatdo.config import load_target
from chatdo.agents.main_agent import run_agent
from chatdo.executor import parse_tasks_block, apply_tasks

# Task execution constants
TASKS_START = "<TASKS>"
TASKS_END = "</TASKS>"


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return urls


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
    message: str,
    rag_file_ids: Optional[List[str]] = None
):
    """
    Stream ChatDO response via WebSocket
    For now, we'll simulate streaming by chunking the response
    In the future, we can integrate with actual streaming from the LLM
    """
    try:
        # Extract URLs to check for single article summary
        urls = extract_urls(message)
        
        # Check for single URL with "summarize" keyword - route to article summary
        if len(urls) == 1 and ("summarize" in message.lower() or "summary" in message.lower()):
            # Call article summary logic directly to avoid circular imports
            from server.article_summary import extract_article
            import requests
            import os
            from datetime import datetime, timezone
            from chatdo.memory.store import load_thread_history, save_thread_history, add_thread_source
            from server.main import load_projects
            from chatdo.agents.main_agent import ARTICLE_SUMMARY_SYSTEM_PROMPT
            
            url = urls[0]
            article_data = extract_article(url)
            
            if article_data.get("error"):
                await websocket.send_json({
                    "type": "error",
                    "content": article_data["error"],
                    "done": True
                })
                return
            
            if not article_data.get("text"):
                await websocket.send_json({
                    "type": "error",
                    "content": "Could not extract article text from URL",
                    "done": True
                })
                return
            
            # Truncate text
            article_text = article_data["text"][:10000]
            
            # Build prompt
            user_prompt = f"""Please summarize the following article:

{article_text}

Provide:
1. A 2–4 sentence summary paragraph
2. 3–5 key bullet points
3. 1–2 sentences on why this matters or its significance

Format your response clearly with the summary first, then key points (as bullet points), then "Why This Matters:" followed by your analysis.

Keep it concise, neutral, and factual."""
            
            # Call AI Router
            messages = [
                {"role": "system", "content": ARTICLE_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            ai_router_url = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")
            payload = {
                "role": "chatdo",
                "intent": "summarize_article",
                "priority": "high",
                "privacyLevel": "normal",
                "costTier": "standard",
                "input": {
                    "messages": messages,
                },
            }
            
            resp = requests.post(ai_router_url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("ok"):
                await websocket.send_json({
                    "type": "error",
                    "content": f"AI Router error: {data.get('error')}",
                    "done": True
                })
                return
            
            assistant_messages = data["output"]["messages"]
            if not assistant_messages or len(assistant_messages) == 0:
                await websocket.send_json({
                    "type": "error",
                    "content": "No response from AI Router",
                    "done": True
                })
                return
            
            summary_text = assistant_messages[0].get("content", "")
            
            # Parse summary
            lines = summary_text.split("\n")
            summary_paragraph = ""
            key_points = []
            why_matters = ""
            
            current_section = "summary"
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                line_lower = line.lower()
                
                # Detect "why this matters" section - be more flexible
                if ("why" in line_lower and ("matter" in line_lower or "context" in line_lower or "significance" in line_lower)):
                    current_section = "why_matters"
                    # If the line has content after a colon, extract it
                    if ":" in line:
                        content = line.split(":", 1)[1].strip()
                        if content:
                            why_matters = content
                    continue
                
                if line.startswith("-") or line.startswith("•") or (line.startswith("*") and len(line) > 1):
                    bullet_text = line.lstrip("-•* ").strip()
                    if bullet_text:
                        if current_section == "why_matters":
                            # Bullet point in why_matters section
                            if why_matters:
                                why_matters += " " + bullet_text
                            else:
                                why_matters = bullet_text
                        else:
                            key_points.append(bullet_text)
                elif current_section == "summary":
                    if not summary_paragraph:
                        summary_paragraph = line
                    else:
                        summary_paragraph += " " + line
                elif current_section == "why_matters":
                    if why_matters:
                        why_matters += " " + line
                    else:
                        why_matters = line
            
            if not summary_paragraph:
                summary_paragraph = summary_text[:500]
            
            # Get title with proper fallback
            title = article_data.get("title")
            if not title or title.strip() == "":
                from urllib.parse import urlparse
                domain = urlparse(article_data["url"]).netloc.replace("www.", "")
                title = f"Article from {domain}"
            
            # Build message data
            message_data = {
                "url": article_data["url"],
                "title": title,
                "siteName": article_data.get("site_name") or "",
                "published": article_data.get("published") or None,
                "summary": summary_paragraph,
                "keyPoints": key_points if key_points else [],
                "whyMatters": why_matters if why_matters else None,
            }
            
            # Save to memory store
            if conversation_id and project_id:
                try:
                    projects = load_projects()
                    project = next((p for p in projects if p.get("id") == project_id), None)
                    if project:
                        target_name = project.get("default_target", "general")
                        thread_id = conversation_id
                        
                        history = load_thread_history(target_name, thread_id)
                        history.append({"role": "user", "content": f"Summarize: {url}"})
                        
                        assistant_message = {
                            "role": "assistant",
                            "content": "",
                            "type": "article_card",
                            "data": message_data,
                            "model": "Trafilatura + GPT-5",
                            "provider": "trafilatura-gpt5"
                        }
                        history.append(assistant_message)
                        save_thread_history(target_name, thread_id, history)
                        
                        # Add source
                        import uuid as uuid_lib
                        source = {
                            "id": str(uuid_lib.uuid4()),
                            "kind": "url",
                            "title": message_data.get("title") or title,
                            "description": summary_paragraph[:200] if summary_paragraph else None,
                            "url": article_data["url"],
                            "createdAt": datetime.now(timezone.utc).isoformat(),
                            "meta": {
                                "siteName": article_data.get("site_name"),
                                "published": article_data.get("published"),
                            }
                        }
                        add_thread_source(target_name, thread_id, source)
                except Exception as e:
                    print(f"Warning: Failed to save article summary to memory store: {e}")
            
            # Send article card via WebSocket
            await websocket.send_json({
                "type": "article_card",
                "data": message_data,
                "model": "Trafilatura + GPT-5",
                "provider": "trafilatura-gpt5",
                "done": True
            })
            return
        
        # Build RAG context if RAG files are provided
        user_message = message
        has_rag_context = False
        if rag_file_ids:
            print(f"[RAG] Building context for {len(rag_file_ids)} files in WebSocket handler")
            from server.main import build_rag_context
            rag_context = build_rag_context(rag_file_ids, message, chat_id=conversation_id)
            if rag_context:
                user_message = f"{rag_context}\n\nUser question: {message}"
                has_rag_context = True
                print(f"[RAG] Context built successfully, length: {len(rag_context)}")
            else:
                print(f"[RAG] Warning: No context was built despite {len(rag_file_ids)} file IDs provided")
        
        # Load target configuration
        target_cfg = load_target(target_name)
        
        # Run ChatDO agent (this is synchronous, so we'll chunk the result)
        # TODO: In the future, integrate with streaming LLM responses
        # Pass has_rag_context flag to skip web search when RAG is available
        # Pass thread_id so run_agent can load history for context and save messages
        raw_result, model_display, provider = run_agent(
            target=target_cfg,
            task=user_message,  # This includes RAG context
            thread_id=conversation_id if conversation_id else None,  # Load history for context
            skip_web_search=has_rag_context
        )
        
        # NOTE: run_agent now filters out RAG context automatically, so we don't need to fix it here
        # But we'll keep this as a safety net in case any RAG context slips through
        if has_rag_context and conversation_id:
            print(f"[DIAG] WebSocket: RAG context was used, but run_agent should have filtered it. Verifying...")
            try:
                target_name_save = target_cfg.name
                thread_id = conversation_id
                history = load_thread_history(target_name_save, thread_id)
                
                # Check if last user message still has RAG context
                if len(history) >= 2:
                    user_idx = len(history) - 2
                    if history[user_idx].get("role") == "user":
                        user_content = history[user_idx].get("content", "")
                        # Check if it contains RAG context markers
                        if "You have access to the following reference documents" in user_content or "----\nSource:" in user_content:
                            print(f"[DIAG] WebSocket: WARNING - User message still contains RAG context! Fixing now...")
                            history[user_idx]["content"] = message
                            save_thread_history(target_name_save, thread_id, history)
                            print(f"[DIAG] WebSocket: ✅ FIXED user message (removed RAG context)")
            except Exception as e:
                print(f"[DIAG] WebSocket: Error verifying/fixing user message: {e}")
        
        # Check if result is structured (web_search_results or article_card)
        if isinstance(raw_result, dict):
            if raw_result.get("type") == "web_search_results":
                # Send structured web search results
                await websocket.send_json({
                    "type": "web_search_results",
                    "data": raw_result,
                    "model": model_display,
                    "provider": provider,
                    "done": True
                })
                return
            elif raw_result.get("type") == "article_card":
                # Send structured article card results
                await websocket.send_json({
                    "type": "article_card",
                    "data": raw_result,
                    "model": model_display,
                    "provider": provider,
                    "done": True
                })
                return
        
        # Split out any <TASKS> block
        human_text, tasks_json = split_tasks_block(raw_result)
        
        # If RAG context was used, send as structured rag_response
        if has_rag_context and not tasks_json:
            # Extract source file names from RAG context
            # IMPORTANT: Return sources in the SAME ORDER as rag_file_ids to match RAG tray numbering
            from server.main import load_rag_files
            from chatdo.memory.store import load_thread_history, save_thread_history
            from server.main import load_projects
            
            rag_files = load_rag_files(conversation_id) if rag_file_ids else []
            # Create a lookup dict for fast access
            rag_files_by_id = {f.get("id"): f for f in rag_files}
            # Return sources in the order of rag_file_ids (matches RAG tray order)
            source_files = [rag_files_by_id.get(fid, {}).get("filename", "") 
                          for fid in (rag_file_ids or [])
                          if fid in rag_files_by_id and rag_files_by_id[fid].get("text_extracted")]
            
            # Log raw RAG output to verify markdown headings are present
            print(f"[RAG] Raw RAG output (first 500 chars):\n{human_text[:500]}")
            if "###" in human_text:
                print("[RAG] ✅ Markdown headings (###) detected in response")
            else:
                print("[RAG] ⚠️  WARNING: No markdown headings (###) found in response")
            
            # Update the last message in memory store to have structured type
            # (run_agent already saved it as a regular message, so we update it)
            if conversation_id and project_id:
                try:
                    projects = load_projects()
                    project = next((p for p in projects if p.get("id") == project_id), None)
                    if project:
                        target_name = project.get("default_target", "general")
                        thread_id = conversation_id
                        
                        history = load_thread_history(target_name, thread_id)
                        # Find the last assistant message (saved by run_agent) and update it with structured type
                        updated = False
                        for i in range(len(history) - 1, -1, -1):
                            if history[i].get("role") == "assistant":
                                # Update existing message with structured type
                                history[i]["type"] = "rag_response"
                                history[i]["data"] = {
                                    "content": human_text,
                                    "sources": source_files
                                }
                                history[i]["model"] = model_display
                                history[i]["provider"] = provider
                                updated = True
                                print(f"[RAG] Updated message at index {i} with type=rag_response, data keys: {list(history[i].get('data', {}).keys())}")
                                break
                        if updated:
                            save_thread_history(target_name, thread_id, history)
                            print(f"[RAG] Saved updated history with {len(history)} messages")
                        else:
                            print(f"[RAG] Warning: Could not find assistant message to update in history of {len(history)} messages")
                except Exception as e:
                    print(f"Warning: Failed to update RAG response in memory store: {e}")
            
            await websocket.send_json({
                "type": "rag_response",
                "data": {
                    "content": human_text,
                    "sources": source_files
                },
                "model": model_display,
                "provider": provider,
                "done": True
            })
            return
        
        # Stream human text in chunks (simulate streaming for now)
        # Note: run_agent already saved the assistant message, so we don't need to save it again
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
        
        # Send completion message with model/provider info
        await websocket.send_json({
            "type": "done",
            "content": "",
            "model": model_display,
            "provider": provider,
            "done": True
        })
    
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()  # Print full traceback to server logs
        
        # Ensure error is sent even if it's a timeout or network issue
        try:
            await websocket.send_json({
                "type": "error",
                "content": error_detail,
                "done": True
            })
        except Exception:
            # WebSocket may be closed, but we tried
            pass


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
            rag_file_ids = data.get("rag_file_ids")  # Optional RAG file IDs
            print(f"[RAG] WebSocket received rag_file_ids: {rag_file_ids}")
            
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
                message,
                rag_file_ids=rag_file_ids
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

