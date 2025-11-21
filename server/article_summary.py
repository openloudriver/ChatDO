"""
Article summarization using Trafilatura + GPT-5
Extracts article content and generates summaries
"""
import trafilatura
from typing import Dict, Optional
from urllib.parse import urlparse


def extract_article(url: str) -> Dict[str, Optional[str]]:
    """
    Extract article content and metadata using Trafilatura.
    
    Args:
        url: The URL to extract from
        
    Returns:
        Dict with keys: url, title, site_name, author, published, text
        Returns error dict if extraction fails
    """
    try:
        # Fetch and extract using Trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {
                "url": url,
                "title": None,
                "site_name": None,
                "author": None,
                "published": None,
                "text": None,
                "error": "Could not fetch URL. The page may be blocked or require authentication."
            }
        
        # Extract with metadata
        extracted = trafilatura.extract(
            downloaded,
            url=url,
            output_format="json",
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=False,
        )
        
        if not extracted:
            return {
                "url": url,
                "title": None,
                "site_name": None,
                "author": None,
                "published": None,
                "text": None,
                "error": "Could not extract article content. The page may not contain a readable article."
            }
        
        # Parse JSON result
        import json
        if isinstance(extracted, str):
            data = json.loads(extracted)
        else:
            data = extracted
        
        # Extract fields
        title = data.get("title") or None
        text = data.get("text") or None
        author = data.get("author") or None
        date = data.get("date") or None
        
        # Get site name from URL
        parsed_url = urlparse(url)
        site_name = parsed_url.netloc.replace("www.", "")
        
        if not text or len(text.strip()) < 100:
            return {
                "url": url,
                "title": title,
                "site_name": site_name,
                "author": author,
                "published": date,
                "text": None,
                "error": "Extracted content is too short or empty. The page may not be a readable article."
            }
        
        return {
            "url": url,
            "title": title,
            "site_name": site_name,
            "author": author,
            "published": date,
            "text": text,
            "error": None
        }
        
    except Exception as e:
        return {
            "url": url,
            "title": None,
            "site_name": None,
            "author": None,
            "published": None,
            "text": None,
            "error": f"Error extracting article: {str(e)}"
        }

