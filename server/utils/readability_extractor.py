"""
Readability-based article extractor (Speedreader-style)
Uses readability-lxml to extract main article content from URLs
"""
import logging
from typing import Dict, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Try to import readability-lxml, but handle gracefully if not available
try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
    logger.warning("readability-lxml is not installed. Readability fallback will not work. Install with: pip install readability-lxml")


def extract_article_with_readability(url: str) -> Dict[str, Optional[str]]:
    """
    Extract article content and metadata using Readability (readability-lxml).
    This is a Speedreader-style extractor that works well on pages where
    Trafilatura fails.
    
    Args:
        url: The URL to extract from
        
    Returns:
        Dict with keys: url, title, site_name, author, published, text
        Returns error dict if extraction fails
    """
    if not READABILITY_AVAILABLE:
        return {
            "url": url,
            "title": None,
            "site_name": None,
            "author": None,
            "published": None,
            "text": None,
            "error": "Readability extractor is not available. Please install readability-lxml: pip install readability-lxml"
        }
    
    try:
        # Fetch the URL
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        html = response.text
        if not html:
            return {
                "url": url,
                "title": None,
                "site_name": None,
                "author": None,
                "published": None,
                "text": None,
                "error": "Could not fetch URL. The page may be blocked or require authentication."
            }
        
        # Use Readability to extract main content
        doc = Document(html)
        summary_html = doc.summary()
        
        if not summary_html:
            return {
                "url": url,
                "title": None,
                "site_name": None,
                "author": None,
                "published": None,
                "text": None,
                "error": "Could not extract article content. The page may not contain a readable article."
            }
        
        # Parse the summary HTML to get text content
        soup = BeautifulSoup(summary_html, 'html.parser')
        
        # Get text content
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Check if content is too short
        word_count = len(text.split())
        if not text or word_count < 50:
            return {
                "url": url,
                "title": None,
                "site_name": None,
                "author": None,
                "published": None,
                "text": None,
                "error": "Extracted content is too short or empty. The page may not be a readable article."
            }
        
        # Extract title from the original HTML (Readability doesn't always provide it)
        title = doc.title()
        if not title or title.strip() == "":
            # Fallback to BeautifulSoup extraction from original HTML
            original_soup = BeautifulSoup(html, 'html.parser')
            
            # Try <title> tag
            title_tag = original_soup.find('title')
            if title_tag and title_tag.get_text().strip():
                title = title_tag.get_text().strip()
                # Clean up common title suffixes
                if '|' in title:
                    parts = title.split('|')
                    title = parts[0].strip()
                elif ' - ' in title:
                    parts = title.split(' - ', 1)
                    if len(parts) == 2:
                        suffix = parts[1].strip()
                        if len(suffix) < 30 or suffix.isupper():
                            title = parts[0].strip()
            
            # Try meta og:title
            if not title or title.strip() == "":
                og_title = original_soup.find('meta', property='og:title')
                if og_title and og_title.get('content'):
                    title = og_title.get('content').strip()
            
            # Try <h1> tag
            if not title or title.strip() == "":
                h1_tag = original_soup.find('h1')
                if h1_tag and h1_tag.get_text().strip():
                    title = h1_tag.get_text().strip()
        
        # Get site name from URL
        parsed_url = urlparse(url)
        site_name = parsed_url.netloc.replace("www.", "")
        
        # Final fallback for title
        if not title or title.strip() == "":
            title = f"Article from {site_name}"
        
        # Try to extract author and published date from original HTML
        author = None
        published = None
        
        original_soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find author
        author_meta = original_soup.find('meta', attrs={"name": "author"})
        if author_meta and author_meta.get('content'):
            author = author_meta.get('content').strip()
        
        # Try to find published date
        published_meta = original_soup.find('meta', attrs={"property": "article:published_time"})
        if published_meta and published_meta.get('content'):
            published = published_meta.get('content').strip()
        else:
            published_meta = original_soup.find('meta', attrs={"name": "published"})
            if published_meta and published_meta.get('content'):
                published = published_meta.get('content').strip()
        
        return {
            "url": url,
            "title": title,
            "site_name": site_name,
            "author": author,
            "published": published,
            "text": text,
            "error": None
        }
        
    except requests.RequestException as e:
        logger.warning(f"Readability extraction failed (network error): {url} - {str(e)}")
        return {
            "url": url,
            "title": None,
            "site_name": None,
            "author": None,
            "published": None,
            "text": None,
            "error": f"Could not fetch URL: {str(e)}"
        }
    except Exception as e:
        logger.warning(f"Readability extraction failed: {url} - {str(e)}")
        return {
            "url": url,
            "title": None,
            "site_name": None,
            "author": None,
            "published": None,
            "text": None,
            "error": f"Error extracting article: {str(e)}"
        }

