"""Web search tools for ChatDO"""
from typing import List, Dict
try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

def search_web(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Search the web using DuckDuckGo (free, no API key needed).
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 10)
    
    Returns:
        List of dictionaries with 'title', 'url', and 'snippet' keys
    """
    if not DDGS_AVAILABLE:
        return [{
            "title": "Search Error",
            "url": "",
            "snippet": "ddgs library not installed. Install it with: pip install ddgs"
        }]
    
    try:
        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
            return results
    except Exception as e:
        # Fallback: return error message
        return [{
            "title": "Search Error",
            "url": "",
            "snippet": f"Web search failed: {str(e)}. Please try a different query or check your internet connection."
        }]


