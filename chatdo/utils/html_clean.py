"""HTML cleaning utilities for ChatDO - removes HTML tags and entities from text"""
import re
import html

# Regex to match HTML tags
TAG_RE = re.compile(r"<[^>]+>")

def strip_tags(text: str) -> str:
    """
    Remove HTML tags and unescape HTML entities from text.
    
    Args:
        text: Input text that may contain HTML tags and entities
    
    Returns:
        Clean text with no HTML tags and unescaped entities
    """
    if not isinstance(text, str):
        return text
    
    # Remove HTML tags (including escaped ones like &lt;strong&gt;)
    no_tags = TAG_RE.sub("", text)
    
    # Remove escaped HTML tags (e.g., &lt;strong&gt; becomes empty)
    no_tags = re.sub(r'&lt;[^&]+&gt;', '', no_tags)
    
    # Unescape HTML entities (&#x27;, &amp;, etc.)
    return html.unescape(no_tags).strip()

