"""Web search tools for ChatDO - Brave Search API only"""
from typing import List, Dict, Optional
import os
import requests
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse
from ..utils.html_clean import strip_tags

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

def search_web(query: str, max_results: int = 10, freshness: str = None) -> List[Dict[str, str]]:
    """
    Search the web using Brave Search API (same search engine as Brave Browser).
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 10)
        freshness: Optional freshness filter - "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year)
                  If None, no freshness filter is applied (searches all time)
    
    Returns:
        List of dictionaries with 'title', 'url', and 'snippet' keys
    
    Raises:
        ValueError: If BRAVE_SEARCH_API_KEY is not set
    """
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    
    if not brave_api_key:
        raise ValueError(
            "BRAVE_SEARCH_API_KEY environment variable is not set. "
            "Please get your API key from https://brave.com/search/api/ and set it in your environment. "
            "See BRAVE_SEARCH_SETUP.md for instructions."
        )
    
    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": brave_api_key
        }
        params = {
            "q": query,
            "count": min(max_results, 20),  # Brave API max is 20
            "search_lang": "en",
            "country": "US",
            "safesearch": "moderate"
        }
        # Only add freshness parameter if specified (for time-sensitive queries)
        if freshness:
            params["freshness"] = freshness
        
        # Use a shorter timeout for faster failure - Brave Search API should respond quickly
        response = requests.get(url, headers=headers, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        results = []
        if "web" in data and "results" in data["web"]:
            for r in data["web"]["results"][:max_results]:
                # Clean HTML tags and entities from title and snippet
                clean_title = strip_tags(r.get("title", ""))
                clean_snippet = strip_tags(r.get("description", ""))
                
                result = {
                    "title": clean_title,
                    "url": r.get("url", ""),
                    "snippet": clean_snippet
                }
                
                # Extract date information if available
                # Brave Search API may return: age, page_age, or published_at
                if "age" in r:
                    result["age"] = r.get("age")
                if "page_age" in r:
                    result["page_age"] = r.get("page_age")
                if "published_at" in r:
                    result["published_at"] = r.get("published_at")
                
                results.append(result)
        
        return results
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise ValueError(
                "Invalid BRAVE_SEARCH_API_KEY. Please check your API key at https://brave.com/search/api/"
            )
        elif e.response.status_code == 429:
            raise ValueError(
                "Brave Search API rate limit exceeded. Please check your plan limits at https://brave.com/search/api/"
            )
        else:
            raise ValueError(f"Brave Search API error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise ValueError(f"Brave Search API request failed: {str(e)}")


def _extract_domain(url: str) -> str:
    """Extract domain from URL for citations."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain
    except:
        return url


def brave_summarize(query: str) -> Optional[Dict[str, any]]:
    """
    Get a Brave-only summary for a search query using Brave's Chat Completions API.
    This uses Brave's OpenAI-compatible endpoint which provides AI-generated summaries
    grounded in web search results. This does NOT use GPT-5 - it's purely Brave's AI.
    
    Args:
        query: Search query string
        
    Returns:
        Dictionary with 'text' (summary text) and optional 'citations' array, or None if unavailable
    """
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    
    if not brave_api_key:
        print(f"[BRAVE_SUMMARY] No API key found")
        return None
    
    try:
        # Use Brave's OpenAI-compatible chat completions endpoint
        # This is simpler and more reliable than the polling approach
        chat_url = "https://api.search.brave.com/res/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {brave_api_key}",
            "X-Subscription-Token": brave_api_key  # Some endpoints use this instead
        }
        
        payload = {
            "model": "brave-pro",  # Use Pro AI model for summaries
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "stream": False
        }
        
        # Try with Authorization header first
        response = requests.post(chat_url, headers=headers, json=payload, timeout=15)
        
        # If that fails, try with X-Subscription-Token only
        if response.status_code == 401:
            headers = {
                "Content-Type": "application/json",
                "X-Subscription-Token": brave_api_key
            }
            response = requests.post(chat_url, headers=headers, json=payload, timeout=15)
        
        response.raise_for_status()
        data = response.json()
        
        # DEBUG: Log full response structure to investigate what's available
        print(f"[BRAVE_SUMMARY] Full response keys: {list(data.keys())}")
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            print(f"[BRAVE_SUMMARY] Choice keys: {list(choice.keys())}")
            if "message" in choice:
                print(f"[BRAVE_SUMMARY] Message keys: {list(choice['message'].keys())}")
        
        # Extract the summary text from the response
        if "choices" in data and len(data["choices"]) > 0:
            summary_text = data["choices"][0].get("message", {}).get("content", "").strip()
            
            if summary_text:
                print(f"[BRAVE_SUMMARY] Successfully generated summary ({len(summary_text)} chars)")
                
                # Record cost: $0.009 per Brave-Pro AI API call
                try:
                    cost_record_url = "http://localhost:8081/v1/ai/spend/record"
                    cost_payload = {
                        "providerId": "brave-pro",
                        "modelId": "brave-pro",
                        "costUsd": 0.009
                    }
                    requests.post(cost_record_url, json=cost_payload, timeout=2)
                except Exception as e:
                    # Don't fail if cost tracking fails - just log it
                    print(f"[BRAVE_SUMMARY] Failed to record cost: {e}")
                
                # Extract citations if available (Brave may include source references)
                citations = []
                # Note: Brave's chat completions may not always include explicit citations
                # in the same format, but the summary is grounded in web search results
                
                result = {"text": summary_text}
                if citations:
                    result["citations"] = citations
                return result
            else:
                print(f"[BRAVE_SUMMARY] Empty summary in response")
                return None
        else:
            print(f"[BRAVE_SUMMARY] No choices in response. Response keys: {list(data.keys())}")
            return None
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print(f"[BRAVE_SUMMARY] Authentication failed - check API key")
        elif e.response.status_code == 402:
            print(f"[BRAVE_SUMMARY] Payment required - Pro AI plan required for summaries")
        else:
            print(f"[BRAVE_SUMMARY] HTTP error {e.response.status_code}: {e.response.text[:200]}")
        import traceback
        traceback.print_exc()
        return None
    except Exception as e:
        # Don't raise - summary is optional, search results should still work
        print(f"[BRAVE_SUMMARY] Summary failed: {e}")
        import traceback
        traceback.print_exc()
        return None

