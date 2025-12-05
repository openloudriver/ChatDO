"""
Article extraction service with fallback logic
Tries Trafilatura first, falls back to Readability if needed
"""
import logging
from typing import Dict, Optional, Literal, Any
from server.article_summary import extract_article
from server.utils.readability_extractor import extract_article_with_readability

logger = logging.getLogger(__name__)

ExtractorName = Literal["Trafilatura", "Readability", "BeautifulSoup"]


def get_article_text_with_fallback(url: str) -> Dict[str, Any]:
    """
    Attempts to extract article text using Trafilatura first.
    If that fails or returns too little content, falls back to
    Readability, then BeautifulSoup as a final fallback.
    
    Args:
        url: The URL to extract from
        
    Returns:
        Dict with keys: text, title, site_name, author, published, extractor
        extractor will be "Trafilatura", "Readability", or "BeautifulSoup"
        
    Raises:
        ValueError: If all extractors fail, with detailed error message
    """
    errors = []  # Track errors from each extractor
    
    # 1. Try Trafilatura first
    trafilatura_error = None
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
                trafilatura_error = f"Trafilatura returned too little content ({word_count} words)"
                logger.info(f"{trafilatura_error}, falling back to Readability: {url}")
        else:
            trafilatura_error = article_data.get("error", "Trafilatura could not extract content")
            logger.info(f"Trafilatura extraction failed: {trafilatura_error}, falling back to Readability: {url}")
    except Exception as e:
        trafilatura_error = f"Trafilatura failed with exception: {str(e)}"
        logger.warning(f"{trafilatura_error}, falling back to Readability: {url}")
    
    if trafilatura_error:
        errors.append(f"Trafilatura: {trafilatura_error}")
    
    # 2. Fallback: Readability-based extractor
    readability_error = None
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
                readability_error = f"Readability returned too little content ({word_count} words)"
                logger.warning(f"{readability_error}: {url}")
        else:
            readability_error = article_data.get("error", "Readability could not extract content")
            logger.warning(f"Readability extraction failed: {readability_error}: {url}")
    except Exception as e:
        readability_error = f"Readability failed with exception: {str(e)}"
        logger.warning(f"{readability_error}: {url}")
    
    if readability_error:
        errors.append(f"Readability: {readability_error}")
    
    # 3. Final fallback: Basic BeautifulSoup extraction
    beautifulsoup_error = None
    try:
        import requests
        from bs4 import BeautifulSoup
        
        # Enhanced headers to avoid bot detection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
        
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Check if we got blocked
        if 'permission' in response.text.lower() or 'access denied' in response.text.lower() or 'blocked' in response.text.lower():
            beautifulsoup_error = "The website is blocking automated access (anti-bot protection detected)"
            logger.warning(f"BeautifulSoup fallback: Site appears to be blocking automated access: {url}")
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script, style, nav, header, footer elements
            for element in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
                element.decompose()
            
            # Try to find main content areas (common article selectors)
            main_content = None
            # Try more specific selectors first
            for selector in [
                'article', 
                'main', 
                '[role="main"]', 
                '.article-content',
                '.article-body',
                '.post-content',
                '.entry-content',
                '.article',
                '.content',
                '.post',
                '.entry',
                '#article',
                '#content',
                '#main-content',
                '.main-content'
            ]:
                main_content = soup.select_one(selector)
                if main_content:
                    logger.info(f"BeautifulSoup found content with selector: {selector}")
                    break
            
            # If no main content found, use body but filter out common non-content elements
            if not main_content:
                body = soup.find('body')
                if body:
                    # Remove common sidebar/nav elements from body
                    for element in body.select('nav, aside, .sidebar, .navigation, .menu, .header, .footer'):
                        element.decompose()
                    main_content = body
            
            if main_content:
                text = main_content.get_text(separator=' ', strip=True)
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)
                
                # Remove very short lines (likely navigation/menu items)
                text_lines = [line for line in text.split('\n') if len(line.strip()) > 10]
                text = '\n'.join(text_lines)
                
                word_count = len(text.split())
                if text and word_count >= 50:
                    # Try to extract title
                    title = None
                    title_tag = soup.find('title')
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                    elif soup.find('h1'):
                        title = soup.find('h1').get_text(strip=True)
                    
                    # Extract site name from URL
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    site_name = parsed.netloc.replace('www.', '')
                    
                    logger.info(f"BeautifulSoup fallback succeeded with {word_count} words: {url}")
                    return {
                        "text": text,
                        "title": title,
                        "site_name": site_name,
                        "author": None,
                        "published": None,
                        "extractor": "BeautifulSoup"
                    }
                else:
                    beautifulsoup_error = f"BeautifulSoup returned too little content ({word_count} words)"
                    logger.warning(f"{beautifulsoup_error}: {url}")
                    # Log a sample of what we got for debugging
                    logger.debug(f"Sample text: {text[:200]}")
            else:
                beautifulsoup_error = "BeautifulSoup could not find main content area in the page"
                logger.warning(f"{beautifulsoup_error}: {url}")
    except requests.RequestException as e:
        beautifulsoup_error = f"Could not fetch the page: {str(e)}"
        logger.warning(f"BeautifulSoup fallback: Request failed: {url} - {str(e)}")
    except ValueError as e:
        # Re-raise blocking detection errors immediately (they're already clear)
        raise
    except Exception as e:
        beautifulsoup_error = f"BeautifulSoup failed with exception: {str(e)}"
        logger.warning(f"BeautifulSoup fallback failed: {url} - {str(e)}")
        import traceback
        logger.debug(f"BeautifulSoup fallback traceback: {traceback.format_exc()}")
    
    if beautifulsoup_error:
        errors.append(f"BeautifulSoup: {beautifulsoup_error}")
    
    # All three extractors failed - build detailed error message
    error_details = " • ".join(errors)  # Use bullet separator for single-line display
    
    # Determine the most likely cause
    blocking_indicators = ['permission', 'access denied', 'blocked', 'bot', 'captcha', 'cloudflare']
    is_blocked = any(indicator in str(errors).lower() for indicator in blocking_indicators)
    
    if is_blocked:
        main_message = "Could not extract article content. The website appears to be blocking automated access (anti-bot protection)."
        suggestion = "This page may require JavaScript to render content or may have security measures that prevent automated extraction."
    else:
        main_message = "Could not extract article content from this page after trying multiple extraction methods."
        suggestion = "The page may not contain a readable article, may require JavaScript to render content, or may have an unusual structure."
    
    # Format for UI display (single line with separators)
    full_error = f"{main_message} Attempted: {error_details}. {suggestion}"
    
    raise ValueError(full_error)

