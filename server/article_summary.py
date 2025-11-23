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
        
        # Extract metadata first (includes date, author, title)
        metadata = trafilatura.extract_metadata(downloaded)
        metadata_date = None
        metadata_author = None
        metadata_title = None
        if metadata:
            metadata_date = metadata.date if hasattr(metadata, 'date') and metadata.date else None
            metadata_author = metadata.author if hasattr(metadata, 'author') and metadata.author else None
            metadata_title = metadata.title if hasattr(metadata, 'title') and metadata.title else None
        
        # Extract with metadata - include formatting to get better title extraction
        extracted = trafilatura.extract(
            downloaded,
            url=url,
            output_format="json",
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=False,
            include_formatting=True,  # Helps with title extraction
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
        
        # Extract fields - prefer metadata values if available
        title = metadata_title or data.get("title") or None
        text = data.get("text") or None
        author = metadata_author or data.get("author") or None
        date = metadata_date or data.get("date") or None
        
        # If Trafilatura didn't extract a title, try BeautifulSoup fallback
        if not title or title.strip() == "":
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(downloaded, 'html.parser')
                
                # Try <title> tag first
                title_tag = soup.find('title')
                if title_tag and title_tag.get_text().strip():
                    title = title_tag.get_text().strip()
                    # Clean up common title suffixes like " | Site Name" or " - Site Name"
                    # But be smarter - only remove if it's clearly a site name suffix
                    if '|' in title:
                        parts = title.split('|')
                        title = parts[0].strip()
                    elif ' - ' in title:
                        # Check if the part after " - " looks like a site name (short, uppercase, or common patterns)
                        parts = title.split(' - ', 1)
                        if len(parts) == 2:
                            suffix = parts[1].strip()
                            # If suffix is short (< 30 chars) or looks like a site name, remove it
                            if len(suffix) < 30 or suffix.isupper() or any(word in suffix.lower() for word in ['times', 'post', 'news', 'daily', 'tribune']):
                                title = parts[0].strip()
                            else:
                                title = title  # Keep the full title if it doesn't look like a suffix
                    else:
                        title = title.strip()
                
                # Try meta og:title (often more reliable than <title>)
                if not title or title.strip() == "":
                    og_title = soup.find('meta', property='og:title')
                    if og_title and og_title.get('content'):
                        title = og_title.get('content').strip()
                
                # Try <h1> tag (often the main article headline)
                if not title or title.strip() == "":
                    h1_tag = soup.find('h1')
                    if h1_tag and h1_tag.get_text().strip():
                        title = h1_tag.get_text().strip()
                
                # Try data-testid or other common article title attributes
                if not title or title.strip() == "":
                    # NYTimes and other sites use data attributes
                    title_elem = soup.find(attrs={"data-testid": lambda x: x and "headline" in x.lower()})
                    if not title_elem:
                        title_elem = soup.find(attrs={"data-testid": lambda x: x and "title" in x.lower()})
                    if not title_elem:
                        title_elem = soup.find(class_=lambda x: x and ("headline" in x.lower() or "article-title" in x.lower()))
                    if title_elem and title_elem.get_text().strip():
                        title = title_elem.get_text().strip()
                
                # Try article headline meta tags
                if not title or title.strip() == "":
                    headline_meta = soup.find('meta', attrs={"name": "headline"})
                    if headline_meta and headline_meta.get('content'):
                        title = headline_meta.get('content').strip()
                
            except Exception:
                pass  # If BeautifulSoup fails, we'll use the fallback below
        
        # Get site name from URL
        parsed_url = urlparse(url)
        site_name = parsed_url.netloc.replace("www.", "")
        
        # Final fallback for title - only use "Article from {domain}" if we truly have no title
        if not title or title.strip() == "":
            title = f"Article from {site_name}"
        
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

