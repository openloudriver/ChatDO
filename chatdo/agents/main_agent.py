from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Union
import os
import re
import requests
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ..config import TargetConfig
from ..prompts import CHATDO_SYSTEM_PROMPT
from ..tools import repo_tools
from ..tools import web_search
from ..memory import store as memory_store
from ..utils.html_clean import strip_tags
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root (in case it's not loaded by the server)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# AI-Router HTTP client
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")

# Web Scraping System Prompt - Intel-brief style formatting
WEB_SCRAPE_SYSTEM_PROMPT = """You are ChatDO's Web Scrape Analyst.

When scraping a URL, your job is to take the extracted text and produce a clean, well-structured, intelligence-style brief with perfect formatting.

Follow this EXACT output format:

## {Article Title}

**Source:** {URL}  

**Outlet:** {Domain name if known}  

**Published:** {Extracted date if present, otherwise omit}

---

### TL;DR (3–5 bullet points)

- Short bullets summarizing the core findings

- Use plain English

- Include only the most important facts

- NEVER include full sentences from the article

---

### Key Details

Organize information into structured sections (only include sections that exist):

**Context**  

- Bullet

**Events / Timeline**  

- Bullet

**Actors / Parties Involved**  

- Bullet

**Capabilities / Assets**  

- Bullet

**Statements / Claims**  

- Bullet

**Risks / Implications**  

- Bullet

---

### Confidence

A short 1–2 sentence note about:

- How complete the scraped article seemed  

- Whether important context might be missing

DO NOT:

- Repeat the source URL multiple times  

- Put [Source: ...] after every bullet  

- Output raw HTML tags  

- Output `<strong>` or `<span>` tags  

- Hallucinate details not present in the text  

If the scraped text is incomplete OR the article is behind a paywall, state so clearly.

Always return clean, beautiful markdown."""

# Cache the model ID to avoid making a preliminary call on every request
_cached_model_id: Optional[str] = None

def _format_model_name(provider_id: str, model_id: str) -> str:
    """Format provider and model ID into a display-friendly name."""
    provider_labels = {
        "openai-gpt5": "GPT-5",
        "gab-ai": "Gab AI",
        "ollama-local": "Ollama",
        "anthropic-claude-sonnet": "Claude",
        "grok-code": "Grok",
        "gemini-pro": "Gemini",
        "mistral-large": "Mistral",
        "llama-local": "Llama",
    }
    provider_label = provider_labels.get(provider_id, provider_id)
    
    # For Ollama, include the model name
    if provider_id == "ollama-local":
        return f"{provider_label} {model_id}"
    
    # For others, just use the provider label or model ID if it's more descriptive
    if provider_id == "openai-gpt5":
        return model_id  # e.g., "gpt-5" or "gpt-5.1"
    
    return provider_label

def classify_intent(text: str) -> str:
    """Classify user message intent for AI-Router routing."""
    t = text.lower()
    
    # Web scraping - user provides URLs to scrape, use Gab AI
    if ("scrape" in t or "web scraping" in t or "scrape website" in t or "scrape url" in t or "scrape page" in t):
        return "web_scraping"
    
    # Web search - user wants to search for information, use Brave Search + GPT-5
    if ("search" in t or "find" in t or "look for" in t or "top headlines" in t or "latest" in t or 
        "current" in t or "today" in t or "recent" in t or "discover" in t or "what are" in t or
        "what's going on" in t or "what is going on" in t or "what's happening" in t or "what is happening" in t or
        "news" in t or "news articles" in t or "news article" in t or "headlines" in t or
        "tell me about" in t or "what about" in t or "update" in t or "updates" in t):
        return "web_search"
    if "refactor" in t or "fix" in t or "edit code" in t:
        return "code_edit"
    if "generate code" in t or "write a function" in t:
        return "code_gen"
    if "plan" in t or "architecture" in t or "roadmap" in t:
        return "long_planning"
    if "summarize" in t:
        return "summarize"
    if "draft" in t or "write" in t or "readme" in t or "policy" in t:
        return "doc_draft"
    
    return "general_chat"

def call_ai_router(messages: List[Dict[str, str]], intent: str = "general_chat", system_prompt_override: Optional[str] = None) -> tuple[List[Dict[str, str]], str, str, str]:
    """
    Call the AI-Router HTTP service to get AI responses.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        intent: AI intent type (e.g., "general_chat", "long_planning", "code_edit")
        system_prompt_override: Optional system prompt to override the default
    
    Returns:
        Tuple of (list of assistant messages from the router, model_id, provider_id, model_display_name)
    """
    # If system_prompt_override is provided, replace the system message
    router_messages = messages.copy()
    if system_prompt_override:
        # Find and replace system message, or add it if not present
        system_found = False
        for i, msg in enumerate(router_messages):
            if msg.get("role") == "system":
                router_messages[i] = {"role": "system", "content": system_prompt_override}
                system_found = True
                break
        if not system_found:
            router_messages.insert(0, {"role": "system", "content": system_prompt_override})
    
    payload = {
        "role": "chatdo",
        "intent": intent,
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": router_messages,
        },
    }
    try:
        # Increase timeout for complex reasoning queries (GPT-5 can take longer)
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"AI-Router error: {data.get('error')}")
        model_id = data.get("modelId", "gpt-5")
        provider_id = data.get("providerId", "openai-gpt5")
        # Create a display-friendly model name
        model_display = _format_model_name(provider_id, model_id)
        return data["output"]["messages"], model_id, provider_id, model_display
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Failed to connect to AI-Router at {AI_ROUTER_URL}. "
            f"Is the AI-Router server running? Error: {str(e)}"
        )
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"AI-Router request timed out: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"AI-Router request failed: {str(e)}")

# OLD MODEL ROUTING CODE - Now using AI-Router instead
# Keeping for reference but not used
# LEGACY MODEL ROUTING CODE (unused) — AI-Router now handles all routing
def choose_model(task: str) -> str:
    """Legacy model router (deprecated — AI-Router handles all routing)."""
    tl = task.lower()

    # Long-form, reproducible design / governance / threat-model work
    # Uses gpt-5 for these tasks
    if any(word in tl for word in [
        "whitepaper", "white paper", "spec", "specification", "design doc",
        "requirements", "threat model", "governance", "constitution",
        "bylaws", "policy", "architecture doc", "roadmap"
    ]):
        return "gpt-5"

    # High-level architecture / strategy / planning / product thinking
    if any(word in tl for word in [
        "architecture", "architect", "system design", "strategy",
        "roadmap", "plan", "planning", "high level", "overview",
        "meta", "vision"
    ]):
        return "gpt-5"

    # All tasks use gpt-5 (code tasks included)
    # Fallback general model
    return "gpt-5"

# OLD MODEL BUILDING CODE - Now using AI-Router instead
# Keeping for reference but not used
def build_model(task: str):
    """
    Build the chat model for this run, using the model router to
    pick an appropriate model based on the task description.
    
    OLD: Used ChatOpenAI with use_responses_api=True for older model versions.
    NOW: All models use standard chat completions API.
    """
    model_name = choose_model(task)
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

# OLD AGENT BUILDING CODE - Now using AI-Router instead
# Keeping for reference but not used
# Note: Tools functionality would need to be added to AI-Router if needed
def build_agent(target: TargetConfig, task: str):
    model = build_model(task)
    tools = build_tools(target)
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=CHATDO_SYSTEM_PROMPT,
    )
    return agent

def run_agent(target: TargetConfig, task: str, thread_id: Optional[str] = None) -> tuple[Union[str, Dict[str, Any]], str, str]:
    """
    Run ChatDO on a given task using AI-Router.
    If thread_id is provided, load/save conversation history so the agent has long-term context.
    """
    # Classify intent from user message
    intent = classify_intent(task)
    
    # Special handling: if summarize intent but query seems to need current info, do web search first
    if intent == "summarize":
        # Check if this is a summary request that needs current information (web search)
        task_lower = task.lower()
        needs_web_search = any(phrase in task_lower for phrase in [
            "what's going on", "what is happening", "current", "latest", "recent", 
            "today", "now", "headlines", "news", "update"
        ])
        
        if needs_web_search:
            # Treat as web_search with summary request
            intent = "web_search"
    
    # Handle web search - use Brave Search API, return structured results (no LLM by default)
    if intent == "web_search":
        # Extract search query from task
        search_query = task
        for prefix in ["find", "search for", "look for", "what are", "show me", "get me"]:
            if task.lower().startswith(prefix):
                search_query = task[len(prefix):].strip()
                break
        
        # Check if user wants a summary
        wants_summary = any(word in task.lower() for word in ["summarize", "summary", "bullet points", "in a few points"])
        
        # Perform web search using Brave Search API
        try:
            search_results = web_search.search_web(search_query, max_results=10)
            if search_results and len(search_results) > 0:
                # Return structured results (no LLM call)
                structured_result = {
                    "type": "web_search_results",
                    "query": search_query,
                    "provider": "brave",
                    "results": search_results,
                    "wants_summary": wants_summary
                }
                
                # If user wants a summary, call Ollama via AI Router
                if wants_summary:
                    try:
                        # Build prompt for Ollama
                        results_text = "\n".join([
                            f"{i+1}. {r.get('title', 'No title')}\n   {r.get('snippet', 'No description')}"
                            for i, r in enumerate(search_results[:5])  # Use top 5 for summary
                        ])
                        system_prompt = "You are a neutral summarizer. Using only the provided headlines and snippets from Brave Search, summarize the main themes in 3 bullet points. Do not hallucinate or add external facts."
                        user_prompt = f"Summarize these search results:\n\n{results_text}"
                        
                        # Call Ollama via AI Router
                        ai_router_url = os.getenv("AI_ROUTER_URL", "http://localhost:8081")
                        ollama_url = f"{ai_router_url}/v1/ai/ollama/summarize"
                        ollama_response = requests.post(
                            ollama_url,
                            json={"systemPrompt": system_prompt, "userPrompt": user_prompt},
                            timeout=30
                        )
                        ollama_response.raise_for_status()
                        ollama_data = ollama_response.json()
                        
                        if ollama_data.get("ok") and ollama_data.get("summary"):
                            structured_result["summary"] = ollama_data["summary"]
                            # Update model display to include Ollama
                            model_display = "Brave Search + Ollama llama3.1:8b"
                            provider = "brave_search+ollama"
                    except Exception as e:
                        # If Ollama fails, just return results without summary
                        print(f"Ollama summary failed: {e}")
                
                # Set model/provider for web search (default, may be updated above if summary added)
                if wants_summary and "summary" in structured_result:
                    pass  # Already set above
                else:
                    model_display = "Brave Search"
                    provider = "brave_search"
                
                return structured_result, model_display, provider
            else:
                return "No search results found. Please try a different query.", "Brave Search", "brave_search"
        except ValueError as e:
            # If API key is missing or invalid, return helpful error message
            return f"Web search is not configured. {str(e)}", "Brave Search", "brave_search"
        except Exception as e:
            # If search fails for other reasons, return error
            return f"Web search failed: {str(e)}. Please try again or check your BRAVE_SEARCH_API_KEY configuration.", "Brave Search", "brave_search"
    
    # Handle web scraping - user provides URLs, scrape them, send to Gab AI
    if intent == "web_scraping":
        # Check if user provided a direct URL to scrape
        # Handle both plain URLs and [URL scraped: ...] format from frontend
        url_pattern = re.compile(r'https?://[^\s\]]+')
        urls_in_task = url_pattern.findall(task)
        
        # Also check for [URL scraped: ...] format (from frontend link button)
        url_scraped_pattern = re.compile(r'\[URL scraped:\s*(https?://[^\]]+)\]')
        scraped_urls = url_scraped_pattern.findall(task)
        if scraped_urls:
            # Add scraped URLs, avoiding duplicates
            for url in scraped_urls:
                if url not in urls_in_task:
                    urls_in_task.append(url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls_in_task:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        urls_in_task = unique_urls
        
        if urls_in_task:
            # User provided URLs directly - scrape them
            scraped_content = []
            for url in urls_in_task[:5]:  # Limit to 5 URLs
                try:
                    # Fetch and scrape URL content (10s timeout - reduced for faster failure)
                    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                        try:
                            response = client.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}, timeout=10.0)
                            response.raise_for_status()
                        except httpx.TimeoutException:
                            raise Exception(f"Request timed out after 10 seconds. The website may be slow or blocking requests.")
                        except httpx.HTTPStatusError as e:
                            raise Exception(f"HTTP {e.response.status_code}: {e.response.reason_phrase}")
                        except httpx.RequestError as e:
                            raise Exception(f"Network error: {str(e)}")
                        
                        # Check if we got redirected to an unwanted domain (like Canva)
                        final_url = str(response.url)
                        if 'canva.com' in final_url.lower():
                            raise Exception(f"URL redirected to Canva: {final_url}")
                        
                        # Check for blocking/access denied
                        if response.status_code == 403 or response.status_code == 401:
                            raise Exception(f"Access denied (HTTP {response.status_code})")
                        
                        html = response.text
                    
                    # Extract main content
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Check if the page content looks like a login/landing page
                    page_text = soup.get_text()[:500].lower()
                    if any(indicator in page_text for indicator in ['please enable', 'access denied', 'blocked', 'login required', 'sign in', 'create account']):
                        raise Exception("Page appears to be blocked or requires login")
                    
                    for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                        script.decompose()
                    text = soup.get_text()
                    # Clean up whitespace
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    clean_text = '\n'.join(chunk for chunk in chunks if chunk)
                    
                    # Only use scraped content if it's substantial
                    if len(clean_text) > 100:
                        # Clean HTML tags and entities from scraped text
                        final_text = strip_tags(clean_text[:2000])  # Limit to 2000 chars per URL
                        scraped_content.append(f"=== Source: {url} ===\n{final_text}\n")
                    else:
                        raise Exception("Scraped content too short (likely redirect/block page)")
                except Exception as e:
                    scraped_content.append(f"=== Error scraping {url}: {str(e)} ===\n")
            
            if scraped_content:
                # Extract the first URL for metadata
                first_url = unique_urls[0] if unique_urls else ""
                domain = urlparse(first_url).netloc.replace("www.", "") if first_url else ""
                
                # Build user prompt with scraped content
                # Limit total content size to avoid huge payloads
                total_content = ''.join(scraped_content)
                if len(total_content) > 8000:  # Limit to 8000 chars total
                    total_content = total_content[:8000] + "\n\n[Content truncated due to size...]"
                
                user_prompt = f"Scraped Web Content from the following sources:\n\n{total_content}\n\nBased on the above scraped content, please analyze and format it according to the instructions in your system prompt."
                
                # Build message history for web scraping
                messages = [
                    {"role": "system", "content": WEB_SCRAPE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ]
                
                # Call AI Router with web_scraping intent and custom system prompt
                # Use shorter timeout for web scraping (45s instead of 60s for faster failure)
                try:
                    # Temporarily override AI_ROUTER_URL timeout by making direct request
                    ai_router_url = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")
                    payload = {
                        "role": "chatdo",
                        "intent": "web_scraping",
                        "priority": "high",
                        "privacyLevel": "normal",
                        "costTier": "standard",
                        "input": {
                            "messages": messages,
                        },
                    }
                    # Use 30s timeout for faster failure detection (reduced from 45s)
                    resp = requests.post(ai_router_url, json=payload, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    if not data.get("ok"):
                        raise RuntimeError(f"AI-Router error: {data.get('error')}")
                    model_id = data.get("modelId", "arya")
                    provider_id = data.get("providerId", "gab-ai")
                    model_display = _format_model_name(provider_id, model_id)
                    assistant_messages = data["output"]["messages"]
                    
                    # Extract the formatted response
                    if assistant_messages and len(assistant_messages) > 0:
                        formatted_content = assistant_messages[0].get("content", "")
                        
                        # Return structured web_scrape response
                        return {
                            "type": "web_scrape",
                            "url": first_url,
                            "domain": domain,
                            "content": formatted_content
                        }, model_display, provider_id
                    else:
                        return "Failed to generate formatted response from scraped content.", "Gab AI", "gab-ai"
                except requests.exceptions.Timeout as e:
                    # Ensure timeout errors are immediately returned
                    error_msg = f"Error: AI Router request timed out after 30 seconds. The scraped content may be too large or Gab AI is slow. Try scraping a shorter article or a different URL."
                    return error_msg, "Gab AI", "gab-ai"
                except requests.exceptions.ConnectionError as e:
                    error_msg = f"Error: Failed to connect to AI Router. Is the AI Router server running? {str(e)}"
                    return error_msg, "Gab AI", "gab-ai"
                except requests.exceptions.RequestException as e:
                    error_msg = f"Error: Network error communicating with AI Router: {str(e)}"
                    return error_msg, "Gab AI", "gab-ai"
                except Exception as e:
                    error_msg = f"Error processing scraped content: {type(e).__name__}: {str(e)}"
                    return error_msg, "Gab AI", "gab-ai"
            else:
                return "No URLs found to scrape. Please provide URLs in your message (e.g., 'scrape https://example.com').", "Gab AI", "gab-ai"
    
    # Build message history
    messages: List[Dict[str, str]] = []
    
    # Get the actual model ID (cached to avoid extra API calls)
    # This allows us to include it in the system prompt so the model knows its exact identifier
    global _cached_model_id
    if _cached_model_id is None:
        try:
            _, _cached_model_id = call_ai_router(
                [{"role": "system", "content": "test"}, {"role": "user", "content": "ping"}],
                intent="general_chat"
            )
        except Exception:
            # Fallback if we can't get model ID
            _cached_model_id = "gpt-5"
    
    model_id = _cached_model_id
    
    # Include model ID in system prompt so model can see it
    system_prompt = f"""{CHATDO_SYSTEM_PROMPT}

IMPORTANT: Your exact backend model identifier is: {model_id}
When asked about your specific model, you should state this exact identifier: {model_id}

You are ChatDO, the Director for the user's local codebase.

Behavior rules:

- The human is always the Owner. Never ask who they are or what role they are in.

- You are responsible for planning and coordinating changes to the repository.

- Cursor (the IDE) is the Executor that actually edits files and runs commands.

File handling:
- When the user uploads a file and includes its content in the message (marked with [File: filename] followed by the content), the content is already extracted and available to you.
- You should process the content directly without asking for permission or mentioning file paths.
- If the user asks you to summarize, analyze, or work with uploaded file content, do so immediately and conversationally.
- Only reference the filename, not internal file paths or storage locations.

When the user is exploring ideas, asking questions, or designing a solution:

- Respond conversationally.

- Propose clear, concrete plans.

- Explain which files and components you intend to touch.

Web Search & Information Discovery:
- When the user asks you to search the web, find information, discover websites, or get current information, use your web search capabilities.
- For queries like "find XYZ", "what are the top headlines", "search for zkSNARK websites", provide comprehensive, up-to-date information.
- You can search for current events, recent developments, and discover relevant websites or resources.
- **CRITICAL: When providing information from scraped web content, you MUST cite the source URL for every fact, claim, or piece of information you mention.**
- Format citations clearly: use [Source: URL] or (Source: URL) after each relevant statement.
- If information comes from multiple sources, cite each source separately.
- Always include the full URL so users can verify the information themselves.

When the user clearly asks you to APPLY or IMPLEMENT changes (for example: "yes, do it", "apply this", "make those changes", "go ahead and implement that plan"):

1. Briefly confirm what you are about to do in plain language.

2. THEN emit a <TASKS> block containing ONLY a JSON object describing the work you want the Executor to perform.

The <TASKS> block MUST follow these rules:

- Start with the literal line: <TASKS>

- Then a single JSON object on the following lines.

- Then a line with: </TASKS>

- Do NOT wrap the JSON in markdown code fences.

- Do NOT add commentary inside the <TASKS> block.

- Outside the <TASKS> block, you may speak normally.

The JSON object MUST have this shape:

{{
  "tasks": [
    {{
      "type": "edit_file",
      "path": "relative/path/from/repo/root.ext",
      "intent": "Short description of the change",
      "before": "Snippet or anchor text to replace",
      "after": "Full replacement snippet that should appear instead"
    }},
    {{
      "type": "create_file",
      "path": "relative/path/from/repo/root.ext",
      "content": "Full file content"
    }},
    {{
      "type": "run_command",
      "cwd": "relative/working/dir/or_dot",
      "command": "shell command to run, e.g. 'pnpm test -- AiSpendIndicator.test.tsx'"
    }}
  ]
}}

Notes:

- "before" in edit_file should be an exact snippet or a very clear anchor that actually exists in the target file.

- "after" should be the full replacement for that snippet, not a diff.

- Use as few tasks as possible to implement the requested changes cleanly.

- If you are not confident a snippet exists, first ask the user for confirmation or suggest a different anchor.
"""
    
    # System message is always first
    messages.append({"role": "system", "content": system_prompt})
    
    if thread_id:
        prior = memory_store.load_thread_history(target.name, thread_id)
        # Prior history should not include system message; only user/assistant.
        # We append after the system message.
        messages.extend(prior)
    
    # Current user turn
    messages.append({"role": "user", "content": task})
    
    # Call AI-Router instead of direct model
    assistant_messages, model_id, provider_id, model_display = call_ai_router(messages, intent=intent)
    
    # Extract content from the last assistant message
    if assistant_messages and len(assistant_messages) > 0:
        final_content = assistant_messages[-1].get("content", "")
    else:
        final_content = ""
    
    # Update memory if thread_id is provided
    if thread_id:
        # We store only user/assistant messages, not system
        history = memory_store.load_thread_history(target.name, thread_id)
        history.append({"role": "user", "content": task})
        history.append({"role": "assistant", "content": final_content})
        memory_store.save_thread_history(target.name, thread_id, history)
    
    return final_content, model_display, provider_id
