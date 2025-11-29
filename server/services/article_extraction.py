"""
Article extraction service with fallback logic
Tries Trafilatura first, falls back to Readability if needed
"""
import logging
from typing import Dict, Optional, Literal, Any
from server.article_summary import extract_article
from server.utils.readability_extractor import extract_article_with_readability

logger = logging.getLogger(__name__)

ExtractorName = Literal["Trafilatura", "Readability"]


def get_article_text_with_fallback(url: str) -> Dict[str, Any]:
    """
    Attempts to extract article text using Trafilatura first.
    If that fails or returns too little content, falls back to
    a Readability-based "Speedreader" extractor.
    
    Args:
        url: The URL to extract from
        
    Returns:
        Dict with keys: text, title, site_name, author, published, extractor
        extractor will be "Trafilatura" or "Readability"
        
    Raises:
        ValueError: If both extractors fail
    """
    # 1. Try Trafilatura first
    try:
        article_data = extract_article(url)
        
        # Check if Trafilatura succeeded
        if not article_data.get("error") and article_data.get("text"):
            text = article_data["text"].strip()
            word_count = len(text.split())
            
            # If Trafilatura returned a decent amount of text, use it
            if text and word_count >= 50:
                return {
                    "text": text,
                    "title": article_data.get("title"),
                    "site_name": article_data.get("site_name"),
                    "author": article_data.get("author"),
                    "published": article_data.get("published"),
                    "extractor": "Trafilatura"
                }
            else:
                logger.info(f"Trafilatura returned too little content ({word_count} words), falling back to Readability: {url}")
        else:
            logger.info(f"Trafilatura extraction failed, falling back to Readability: {url}")
    except Exception as e:
        logger.warning(f"Trafilatura extraction failed with exception, falling back to Readability: {url} - {str(e)}")
    
    # 2. Fallback: Readability-based extractor
    try:
        article_data = extract_article_with_readability(url)
        
        if not article_data.get("error") and article_data.get("text"):
            text = article_data["text"].strip()
            word_count = len(text.split())
            
            if text and word_count >= 50:
                return {
                    "text": text,
                    "title": article_data.get("title"),
                    "site_name": article_data.get("site_name"),
                    "author": article_data.get("author"),
                    "published": article_data.get("published"),
                    "extractor": "Readability"
                }
            else:
                logger.warning(f"Readability returned too little content ({word_count} words): {url}")
        else:
            logger.warning(f"Readability extraction failed: {url} - {article_data.get('error', 'Unknown error')}")
    except Exception as e:
        logger.warning(f"Readability extraction failed with exception: {url} - {str(e)}")
    
    # 3. Both failed
    raise ValueError("Could not extract article content from this page after multiple attempts. The page may not contain a readable article.")

