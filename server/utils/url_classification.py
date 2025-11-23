"""
Deterministic URL classification for video vs web page routing.
Separates YouTube from other video hosts for 2-tier video pipeline.
"""
from urllib.parse import urlparse

YOUTUBE_HOSTS = [
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
]

OTHER_VIDEO_HOSTS = [
    "bitchute.com",
    "www.bitchute.com",
    "rumble.com",
    "www.rumble.com",
    "archive.org",
    "www.archive.org",
]


def _get_domain(url: str) -> str:
    """
    Extract and normalize the domain from a URL.
    
    Args:
        url: The URL to parse
        
    Returns:
        Normalized domain (lowercase, www. stripped) or empty string on error
    """
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Strip common prefixes like "www."
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def is_youtube_url(url: str) -> bool:
    """
    Return True if the URL is from YouTube.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is from YouTube, False otherwise
    """
    host = _get_domain(url)
    return host in {"youtube.com", "m.youtube.com", "youtu.be"}


def is_other_video_host(url: str) -> bool:
    """
    Return True if the URL is from a non-YouTube video host.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is from a non-YouTube video host, False otherwise
    """
    host = _get_domain(url)
    return host in {"bitchute.com", "rumble.com", "archive.org"}


def is_video_host(url: str) -> bool:
    """
    Return True if this URL is any video host we support.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is from any known video host, False otherwise
    """
    return is_youtube_url(url) or is_other_video_host(url)

