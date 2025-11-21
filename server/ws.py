"""
WebSocket streaming endpoint for ChatDO
Streams ChatDO replies chunk-by-chunk
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional
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
    message: str
):
    """
    Stream ChatDO response via WebSocket
    For now, we'll simulate streaming by chunking the response
    In the future, we can integrate with actual streaming from the LLM
    """
    try:
        # Check for multiple URLs in the message - route to multi-article summary
        urls = extract_urls(message)
        if len(urls) >= 2:
            # Call the multi-article summary logic directly to avoid circular imports
            import sys
            import os
            from pathlib import Path
            
            # Import article extraction and AI router functions
            from server.article_summary import extract_article
            import requests
            from datetime import datetime, timezone
            from chatdo.memory.store import load_thread_history, save_thread_history, add_thread_source
            from server.main import load_projects, ARTICLE_SUMMARY_SYSTEM_PROMPT
            
            # Extract articles
            articles_data = []
            article_texts = []
            
            for url in urls:
                if not url.startswith(("http://", "https://")):
                    continue
                
                article_data = extract_article(url)
                if article_data.get("error") or not article_data.get("text"):
                    continue
                
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                articles_data.append({
                    "url": url,
                    "title": article_data.get("title") or "Untitled",
                    "domain": domain,
                })
                
                article_texts.append(f"Article from {domain}:\n{article_data['text'][:5000]}")
            
            if len(articles_data) < 2:
                await websocket.send_json({
                    "type": "error",
                    "content": "Could not extract content from at least 2 URLs",
                    "done": True
                })
                return
            
            # Combine all article texts
            combined_text = "\n\n---\n\n".join(article_texts)
            
            # Build prompt for GPT-5
            user_prompt = f"""Please analyze and summarize the following {len(articles_data)} articles together:

{combined_text}

Provide:
1. A 3-5 sentence joint summary that captures the main themes across all articles
2. 3-5 key points where the articles agree or align
3. 3-5 key differences or contrasting perspectives between the articles
4. (Optional) 1-2 sentences on why this comparison matters or what insights emerge

Keep it concise, neutral, and factual. Focus on synthesis and comparison."""
            
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
            
            resp = requests.post(ai_router_url, json=payload, timeout=180)
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
            
            # Parse summary into sections
            lines = summary_text.split("\n")
            joint_summary = ""
            key_agreements = []
            key_differences = []
            why_matters = ""
            
            current_section = "summary"
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                if "agreement" in line.lower() or "align" in line.lower() or "agree" in line.lower():
                    current_section = "agreements"
                    continue
                elif "difference" in line.lower() or "contrast" in line.lower() or "differ" in line.lower():
                    current_section = "differences"
                    continue
                elif "why" in line.lower() and ("matter" in line.lower() or "insight" in line.lower()):
                    current_section = "why_matters"
                    continue
                
                if line.startswith("-") or line.startswith("•") or (line.startswith("*") and len(line) > 1):
                    bullet_text = line.lstrip("-•* ").strip()
                    if bullet_text:
                        if current_section == "agreements":
                            key_agreements.append(bullet_text)
                        elif current_section == "differences":
                            key_differences.append(bullet_text)
                elif current_section == "summary" and not joint_summary:
                    joint_summary = line
                elif current_section == "summary" and joint_summary:
                    joint_summary += " " + line
                elif current_section == "why_matters":
                    if why_matters:
                        why_matters += " " + line
                    else:
                        why_matters = line
            
            if not joint_summary:
                joint_summary = summary_text[:500]
            
            # Build message data
            message_data = {
                "articles": articles_data,
                "jointSummary": joint_summary,
                "keyAgreements": key_agreements if key_agreements else [],
                "keyDifferences": key_differences if key_differences else [],
                "whyMatters": why_matters if why_matters else None,
            }
            
            # Save to memory store if conversation_id is provided
            if conversation_id and project_id:
                try:
                    projects = load_projects()
                    project = next((p for p in projects if p.get("id") == project_id), None)
                    if project:
                        target_name = project.get("default_target", "general")
                        thread_id = conversation_id
                        
                        history = load_thread_history(target_name, thread_id)
                        user_message = f"Summarize these {len(articles_data)} articles together: {', '.join([a['url'] for a in articles_data])}"
                        history.append({"role": "user", "content": user_message})
                        
                        assistant_message = {
                            "role": "assistant",
                            "content": "",
                            "type": "multi_article_card",
                            "data": message_data,
                            "model": "Trafilatura + GPT-5",
                            "provider": "trafilatura-gpt5"
                        }
                        history.append(assistant_message)
                        save_thread_history(target_name, thread_id, history)
                        
                        # Add sources
                        import uuid as uuid_lib
                        for article in articles_data:
                            source = {
                                "id": str(uuid_lib.uuid4()),
                                "kind": "url",
                                "title": article["title"],
                                "url": article["url"],
                                "createdAt": datetime.now(timezone.utc).isoformat(),
                                "meta": {"domain": article["domain"]}
                            }
                            add_thread_source(target_name, thread_id, source)
                except Exception as e:
                    print(f"Warning: Failed to save multi-article summary to memory store: {e}")
            
            # Send multi-article card via WebSocket
            await websocket.send_json({
                "type": "multi_article_card",
                "data": message_data,
                "model": "Trafilatura + GPT-5",
                "provider": "trafilatura-gpt5",
                "done": True
            })
            return
        
        # Check for single URL with "summarize" keyword - route to article summary
        if len(urls) == 1 and ("summarize" in message.lower() or "summary" in message.lower()):
            # Call article summary logic directly to avoid circular imports
            from server.article_summary import extract_article
            import requests
            import os
            from datetime import datetime, timezone
            from chatdo.memory.store import load_thread_history, save_thread_history, add_thread_source
            from server.main import load_projects, ARTICLE_SUMMARY_SYSTEM_PROMPT
            
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
3. (Optional) 1–2 sentences on why this matters or context

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
                
                if line.startswith("-") or line.startswith("•") or (line.startswith("*") and len(line) > 1):
                    bullet_text = line.lstrip("-•* ").strip()
                    if bullet_text:
                        key_points.append(bullet_text)
                elif "why" in line.lower() and ("matter" in line.lower() or "context" in line.lower()):
                    current_section = "why_matters"
                elif current_section == "summary" and not summary_paragraph:
                    summary_paragraph = line
                elif current_section == "summary" and summary_paragraph:
                    summary_paragraph += " " + line
                elif current_section == "why_matters":
                    if why_matters:
                        why_matters += " " + line
                    else:
                        why_matters = line
            
            if not summary_paragraph:
                summary_paragraph = summary_text[:500]
            
            # Build message data
            message_data = {
                "url": article_data["url"],
                "title": article_data.get("title") or "Article",
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
                            "title": message_data.get("title") or "Article",
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
        
        # Load target configuration
        target_cfg = load_target(target_name)
        
        # Run ChatDO agent (this is synchronous, so we'll chunk the result)
        # TODO: In the future, integrate with streaming LLM responses
        raw_result, model_display, provider = run_agent(
            target=target_cfg,
            task=message,
            thread_id=conversation_id
        )
        
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

