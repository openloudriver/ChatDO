"""Web search tools for ChatDO - Brave Search API only"""
from typing import List, Dict
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

def search_web(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Search the web using Brave Search API (same search engine as Brave Browser).
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 10)
    
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
            "safesearch": "moderate",
            "freshness": "pd"  # Past day for recent results
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        if "web" in data and "results" in data["web"]:
            for r in data["web"]["results"][:max_results]:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", "")
                })
        
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


