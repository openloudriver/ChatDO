"""
WebSocket streaming endpoint for ChatDO
Streams ChatDO replies chunk-by-chunk
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional, List, Dict, Any
import sys
import re
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatdo.config import load_target
from chatdo.agents.ai_router import run_agent
from chatdo.executor import parse_tasks_block, apply_tasks

# Task execution constants
TASKS_START = "<TASKS>"
TASKS_END = "</TASKS>"


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return urls


# Web policy decision logic moved to server/services/web_policy.py


def fetch_web_sources(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch web search results and convert to Source format.
    
    Returns:
        List of Source dictionaries with title, url, description, siteName, rank
    """
    from chatdo.tools import web_search
    
    try:
        search_results = web_search.search_web(query, max_results=max_results)
        sources = []
        
        for index, result in enumerate(search_results):
            # Extract domain for siteName
            site_name = None
            if result.get('url'):
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(result['url'])
                    site_name = parsed.netloc.replace('www.', '')
                except:
                    pass
            
            source = {
                'id': f'web-{index}',
                'title': result.get('title', 'Untitled'),
                'url': result.get('url'),
                'description': result.get('snippet', ''),
                'siteName': site_name,
                'rank': index,
                'sourceType': 'web'
            }
            sources.append(source)
        
        return sources
    except Exception as e:
        print(f"[WEB] Web search failed: {e}")
        return []


def build_web_context_prompt(sources: List[Dict[str, Any]]) -> str:
    """
    Build a system prompt that includes web sources and instructs GPT to cite them.
    """
    if not sources:
        return ''
    
    lines = []
    for i, source in enumerate(sources):
        n = i + 1
        url = source.get('url', '')
        url_str = f" ({url})" if url else ""
        title = source.get('title', 'Untitled')
        description = source.get('description', '')
        
        lines.append(f"{n}. {title}{url_str}\n{description}".strip())
    
    prompt = [
        'You have access to the following up-to-date web sources.',
        'When you use a specific fact from a source, add a citation like [1] or [2] at the end of the relevant sentence.',
        'Use these sources only when needed; otherwise, answer normally.',
        '',
        '\n\n'.join(lines)
    ]
    
    return '\n'.join(prompt)


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
    target_name: str,  # This is now determined from project_id, but kept for backward compatibility
    message: str,
    rag_file_ids: Optional[List[str]] = None,
    web_mode: str = 'auto',
    force_search: bool = False
):
    # Ensure target_name is correct by getting it from project_id
    # This ensures we always use the project-based folder structure
    from server.main import load_projects, get_target_name_from_project
    projects = load_projects()
    project = next((p for p in projects if p.get("id") == project_id), None)
    if project:
        target_name = get_target_name_from_project(project)
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
            from chatdo.agents.ai_router import ARTICLE_SUMMARY_SYSTEM_PROMPT
            
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
                        from server.main import get_target_name_from_project
                        target_name = get_target_name_from_project(project)
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
            # Update chat's updated_at timestamp
            if conversation_id:
                from server.main import update_chat_timestamp
                update_chat_timestamp(conversation_id)
            
            await websocket.send_json({
                "type": "article_card",
                "data": message_data,
                "model": "Trafilatura + GPT-5",
                "provider": "trafilatura-gpt5",
                "done": True
            })
            return
        
        # Determine if web search should be used using centralized policy
        from server.services.web_policy import should_use_web
        
        # Normalize web_mode
        web_toggle: str = web_mode if web_mode in ("auto", "on") else "auto"
        
        use_web = should_use_web(
            message_text=message,
            web_mode=web_toggle
        )
        
        # Fetch web sources if needed
        sources: List[Dict[str, Any]] = []
        web_context_prompt = ""
        
        if use_web:
            try:
                sources = fetch_web_sources(message, max_results=5)
                if sources:
                    web_context_prompt = build_web_context_prompt(sources)
            except Exception as e:
                print(f"[WEB] Web search failed, falling back to GPT only: {e}")
                sources = []
                web_context_prompt = ""
        
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
        
        # If force_search is true, route to run_agent which will return Top Results card
        if force_search and not has_rag_context:
            print(f"[FORCE_SEARCH] force_search=True, message='{message[:100]}...'")
            from chatdo.agents.ai_router import run_agent
            from chatdo.tools import web_search
            
            # Prepend "search for" to ensure it gets classified as web_search intent
            search_message = message if message.lower().startswith(("search", "find", "look for")) else f"search for {message}"
            print(f"[FORCE_SEARCH] Modified message to: '{search_message[:100]}...'")
            
            raw_result, model_display, provider = run_agent(
                target=target_cfg,
                task=search_message,
                thread_id=conversation_id if conversation_id else None,
                skip_web_search=False,  # Don't skip web search when force_search is true
                thread_target_name=target_name  # Use project-based target name for thread storage
            )
            
            print(f"[FORCE_SEARCH] run_agent returned: type={type(raw_result)}, model={model_display}, provider={provider}")
            if isinstance(raw_result, dict):
                print(f"[FORCE_SEARCH] Result dict keys: {raw_result.keys()}, type={raw_result.get('type')}")
            
            # Check if result is structured (web_search_results)
            if isinstance(raw_result, dict) and raw_result.get("type") == "web_search_results":
                print(f"[FORCE_SEARCH] ✅ Returning web_search_results")
                # Send structured web search results
                await websocket.send_json({
                    "type": "web_search_results",
                    "data": raw_result,
                    "model": model_display,
                    "provider": provider,
                    "done": True
                })
                # Update chat's updated_at timestamp
                if conversation_id:
                    from server.main import update_chat_timestamp
                    update_chat_timestamp(conversation_id)
                return
            else:
                # If run_agent didn't return web_search_results, force it directly
                print(f"[FORCE_SEARCH] ⚠️ run_agent didn't return web_search_results, forcing direct web search")
                try:
                    # Perform web search directly (no freshness filter for force_search)
                    search_results = web_search.search_web(message, max_results=10, freshness=None)
                    if search_results and len(search_results) > 0:
                        structured_result = {
                            "type": "web_search_results",
                            "query": message,
                            "provider": "brave",
                            "results": search_results
                        }
                        print(f"[FORCE_SEARCH] ✅ Direct web search succeeded, returning {len(search_results)} results")
                        await websocket.send_json({
                            "type": "web_search_results",
                            "data": structured_result,
                            "model": "Brave Search",
                            "provider": "brave_search",
                            "done": True
                        })
                        # Update chat's updated_at timestamp
                        if conversation_id:
                            from server.main import update_chat_timestamp
                            update_chat_timestamp(conversation_id)
                        return
                    else:
                        print(f"[FORCE_SEARCH] ❌ Direct web search returned no results")
                        await websocket.send_json({
                            "type": "error",
                            "content": "No search results found. Please try a different query.",
                            "done": True
                        })
                        return
                except Exception as e:
                    print(f"[FORCE_SEARCH] ❌ Direct web search failed: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Web search failed: {str(e)}",
                        "done": True
                    })
                    return
        
        # If web is used and no RAG context, handle web + GPT flow directly
        if use_web and sources and not has_rag_context:
            # Use web sources as context for GPT
            from chatdo.memory.store import load_thread_history
            from chatdo.agents.ai_router import call_ai_router
            from chatdo.prompts import CHATDO_SYSTEM_PROMPT
            import os
            import requests
            
            # Get conversation history
            conversation_history = []
            if conversation_id:
                conversation_history = load_thread_history(target_cfg.name, conversation_id)
                # Filter to only user/assistant/system messages with content
                conversation_history = [
                    {"role": msg.get("role"), "content": msg.get("content", "")}
                    for msg in conversation_history
                    if msg.get("role") in ["user", "assistant", "system"] and msg.get("content")
                ]
            
            # Build messages with web context
            messages = conversation_history.copy()
            
            # Add system prompt with web context
            system_prompt = f"{web_context_prompt}\n\n{CHATDO_SYSTEM_PROMPT}\n\nWhen you use a fact from the web sources above, add inline citations like [1], [2], or [1, 3] at the end of the sentence. If the answer does not require web sources, you may answer without citations."
            
            if not any(msg.get("role") == "system" for msg in messages):
                messages.insert(0, {"role": "system", "content": system_prompt})
            else:
                # Replace existing system message
                for i, msg in enumerate(messages):
                    if msg.get("role") == "system":
                        messages[i] = {"role": "system", "content": system_prompt}
                        break
            
            messages.append({"role": "user", "content": message})
            
            # Call AI Router
            ai_router_url = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")
            payload = {
                "role": "chatdo",
                "intent": "general_chat",
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
            
            content = assistant_messages[0].get("content", "")
            model_display = "Web + GPT-5"
            provider = data.get("provider", "openai-gpt5")
            
            # Save to memory store
            if conversation_id:
                from datetime import datetime, timezone
                from server.services.memory_service_client import get_memory_client
                from chatdo.memory.store import save_thread_history
                
                history = load_thread_history(target_cfg.name, conversation_id)
                message_index = len(history)
                
                history.append({"role": "user", "content": message})
                history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model_display,
                    "provider": provider,
                    "sources": sources
                })
                save_thread_history(target_cfg.name, conversation_id, history)
                
                # Index messages into Memory Service for cross-chat search
                if project_id:
                    try:
                        memory_client = get_memory_client()
                        now = datetime.now(timezone.utc).isoformat()
                        
                        # Index user message
                        user_message_id = f"{conversation_id}-user-{message_index}"
                        memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=conversation_id,
                            message_id=user_message_id,
                            role="user",
                            content=message,
                            timestamp=now,
                            message_index=message_index
                        )
                        
                        # Index assistant message
                        assistant_message_id = f"{conversation_id}-assistant-{message_index + 1}"
                        memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=conversation_id,
                            message_id=assistant_message_id,
                            role="assistant",
                            content=content,
                            timestamp=now,
                            message_index=message_index + 1
                        )
                    except Exception as e:
                        print(f"[MEMORY] Warning: Failed to index messages: {e}", exc_info=True)
            
            # Stream the response as chunks
            chunk_size = 50
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                await websocket.send_json({
                    "type": "chunk",
                    "content": chunk
                })
            
            # Send done message with sources
            await websocket.send_json({
                "type": "done",
                "model": model_display,
                "provider": provider,
                "sources": sources,
                "meta": {"usedWebSearch": True}
            })
            return
        
        # If RAG context is available, use run_agent (preserves existing behavior)
        # Otherwise, use chat_with_smart_search for normal chat (consistent with REST endpoint)
        if has_rag_context:
            # Run ChatDO agent (this is synchronous, so we'll chunk the result)
            # TODO: In the future, integrate with streaming LLM responses
            # Pass has_rag_context flag to skip web search when RAG is available
            # Pass thread_id so run_agent can load history for context and save messages
            raw_result, model_display, provider = run_agent(
                target=target_cfg,
                task=user_message,  # This includes RAG context
                thread_id=conversation_id if conversation_id else None,  # Load history for context
                skip_web_search=has_rag_context,
                thread_target_name=target_name  # Use project-based target name for thread storage
            )
        else:
            # Use chat_with_smart_search for normal chat (consistent with REST endpoint)
            from server.services.chat_with_smart_search import chat_with_smart_search
            from chatdo.memory.store import load_thread_history
            
            # Get conversation history for context
            conversation_history = []
            if conversation_id:
                conversation_history = load_thread_history(target_cfg.name, conversation_id)
            
            # Call smart chat service
            result = await chat_with_smart_search(
                user_message=message,
                target_name=target_cfg.name,
                thread_id=conversation_id if conversation_id else None,
                conversation_history=conversation_history,
                project_id=project_id
            )
            
            # Extract response content
            raw_result = result.get("content", "")
            model_display = result.get("model", "GPT-5")
            provider = result.get("provider", "openai-gpt5")
            meta = result.get("meta", {})
            sources = result.get("sources")
            
            # Stream the response as chunks (simulate streaming)
            chunk_size = 50  # Characters per chunk
            for i in range(0, len(raw_result), chunk_size):
                chunk = raw_result[i:i + chunk_size]
                await websocket.send_json({
                    "type": "chunk",
                    "content": chunk
                })
            
            # Send done message with meta
            await websocket.send_json({
                "type": "done",
                "model": model_display,
                "provider": provider,
                "sources": sources,
                "meta": meta
            })
            return
        
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
                        from server.main import get_target_name_from_project
                        target_name = get_target_name_from_project(project)
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
                                # Add RAG sources
                                history[i]["sources"] = ["RAG-Upload"] if source_files else None
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
            
            # Update chat's updated_at timestamp
            if conversation_id:
                update_chat_timestamp(conversation_id)
            
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
        
        # Index messages into Memory Service for cross-chat search
        # Note: run_agent already saved messages to thread history
        if conversation_id and project_id:
            try:
                from datetime import datetime, timezone
                from server.services.memory_service_client import get_memory_client
                from chatdo.memory.store import load_thread_history
                
                # Load the history that run_agent just saved
                history = load_thread_history(target_cfg.name, conversation_id)
                
                # Find the last user and assistant messages (just added by run_agent)
                # We need to index both if they exist
                user_msg_idx = None
                assistant_msg_idx = None
                for i in range(len(history) - 1, -1, -1):
                    if history[i].get("role") == "assistant" and assistant_msg_idx is None:
                        assistant_msg_idx = i
                    elif history[i].get("role") == "user" and user_msg_idx is None:
                        user_msg_idx = i
                    if user_msg_idx is not None and assistant_msg_idx is not None:
                        break
                
                memory_client = get_memory_client()
                now = datetime.now(timezone.utc).isoformat()
                
                # Index user message
                if user_msg_idx is not None:
                    user_msg = history[user_msg_idx]
                    user_content = user_msg.get("content", "")
                    if user_content:
                        user_message_id = f"{conversation_id}-user-{user_msg_idx}"
                        memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=conversation_id,
                            message_id=user_message_id,
                            role="user",
                            content=user_content,
                            timestamp=now,
                            message_index=user_msg_idx
                        )
                
                # Index assistant message
                if assistant_msg_idx is not None:
                    assistant_msg = history[assistant_msg_idx]
                    assistant_content = assistant_msg.get("content", "")
                    if assistant_content:
                        assistant_message_id = f"{conversation_id}-assistant-{assistant_msg_idx}"
                        memory_client.index_chat_message(
                            project_id=project_id,
                            chat_id=conversation_id,
                            message_id=assistant_message_id,
                            role="assistant",
                            content=assistant_content,
                            timestamp=now,
                            message_index=assistant_msg_idx
                        )
            except Exception as e:
                print(f"[MEMORY] Warning: Failed to index messages for cross-chat search: {e}", exc_info=True)
        
        # Update chat's updated_at timestamp
        if conversation_id:
            from server.main import update_chat_timestamp
            update_chat_timestamp(conversation_id)
        
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
            message = data.get("message")
            rag_file_ids = data.get("rag_file_ids")  # Optional RAG file IDs
            web_mode = data.get("web_mode", "auto")  # Web mode: 'auto' or 'on'
            force_search = data.get("force_search", False)  # Force web search (Top Results card)
            print(f"[RAG] WebSocket received rag_file_ids: {rag_file_ids}")
            print(f"[WEB] WebSocket received force_search: {force_search}")
            
            if not all([project_id, conversation_id, message]):
                await websocket.send_json({
                    "type": "error",
                    "content": "Missing required fields: project_id, conversation_id, message",
                    "done": True
                })
                continue
            
            # Determine target_name from project_id (don't trust client)
            from server.main import load_projects, get_target_name_from_project
            projects = load_projects()
            project = next((p for p in projects if p.get("id") == project_id), None)
            if not project:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Project not found: {project_id}",
                    "done": True
                })
                continue
            target_name = get_target_name_from_project(project)
            
            # Stream response
            await stream_chat_response(
                websocket,
                project_id,
                conversation_id,
                target_name,
                message,
                rag_file_ids=rag_file_ids,
                web_mode=web_mode,
                force_search=force_search
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

