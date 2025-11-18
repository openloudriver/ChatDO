"""
URL scraping for ChatDO
Fetches HTML, strips boilerplate, saves as text
"""
from pathlib import Path
import httpx
import uuid


UPLOADS_BASE = Path(__file__).parent.parent / "uploads"


async def scrape_url(project_id: str, conversation_id: str, url: str) -> dict:
    """
    Scrape URL content, extract main text, save to uploads folder
    """
    # Create upload directory
    upload_dir = UPLOADS_BASE / project_id / conversation_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Fetch URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            html_content = response.text
        
        # Extract main content (strip boilerplate)
        text_content = extract_main_content(html_content, url)
        
        # Save as .txt
        text_filename = f"{uuid.uuid4()}.txt"
        text_path = upload_dir / text_filename
        
        async with aiofiles.open(text_path, 'w', encoding='utf-8') as f:
            await f.write(f"URL: {url}\n\n{text_content}")
        
        return {
            "url": url,
            "filename": text_filename,
            "path": str(text_path.relative_to(UPLOADS_BASE.parent)),
            "content_length": len(text_content),
            "status": "success"
        }
    
    except Exception as e:
        return {
            "url": url,
            "status": "error",
            "error": str(e)
        }


def extract_main_content(html: str, url: str) -> str:
    """
    Extract main content from HTML, stripping boilerplate
    Uses trafilatura or readability-lxml if available
    """
    # Try trafilatura first (best quality)
    try:
        import trafilatura
        extracted = trafilatura.extract(html, url=url)
        if extracted:
            return extracted
    except ImportError:
        pass
    
    # Fallback to readability-lxml
    try:
        from readability import Document
        doc = Document(html)
        return doc.summary()
    except ImportError:
        pass
    
    # Final fallback: basic BeautifulSoup extraction
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "header", "footer"]):
            script.decompose()
        
        # Get text
        text = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text
    except ImportError:
        # Last resort: return raw HTML (not ideal)
        return html


# Import aiofiles for async file operations
import aiofiles

