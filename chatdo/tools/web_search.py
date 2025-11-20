"""Web search tools for ChatDO"""
import requests
from typing import List, Dict, Optional
import json

def search_web(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Search the web using DuckDuckGo Instant Answer API (free, no API key needed).
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 10)
    
    Returns:
        List of dictionaries with 'title', 'url', and 'snippet' keys
    """
    try:
        # Use DuckDuckGo HTML search (no API key required)
        # We'll use the instant answer API first, then fall back to HTML scraping if needed
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1"
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        
        # Add instant answer if available
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "snippet": data.get("AbstractText", "")
            })
        
        # Add related topics
        for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append({
                    "title": topic.get("Text", "").split(" - ")[0] if " - " in topic.get("Text", "") else topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", "")
                })
        
        # If we don't have enough results, use DuckDuckGo HTML search as fallback
        if len(results) < max_results:
            html_results = _search_duckduckgo_html(query, max_results - len(results))
            results.extend(html_results)
        
        return results[:max_results]
    
    except Exception as e:
        # Fallback: return error message
        return [{
            "title": "Search Error",
            "url": "",
            "snippet": f"Web search failed: {str(e)}. Please try a different query or check your internet connection."
        }]

def _search_duckduckgo_html(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Fallback HTML search using DuckDuckGo (simpler, less reliable but works without API).
    """
    try:
        from bs4 import BeautifulSoup
        
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # DuckDuckGo HTML results are in result divs
        for result in soup.find_all("div", class_="result")[:max_results]:
            title_elem = result.find("a", class_="result__a")
            snippet_elem = result.find("a", class_="result__snippet")
            
            if title_elem:
                results.append({
                    "title": title_elem.get_text(strip=True),
                    "url": title_elem.get("href", ""),
                    "snippet": snippet_elem.get_text(strip=True) if snippet_elem else ""
                })
        
        return results
    
    except Exception:
        return []

