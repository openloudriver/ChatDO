"""
Deterministic URL classification for video vs web page routing.
"""
from urllib.parse import urlparse

# Hardcoded list of video hosts - this is the single source of truth
VIDEO_HOSTS = [
    "youtube.com",
    "youtu.be",
    "bitchute.com",
    "rumble.com",
    "archive.org",
]


def is_video_host(url: str) -> bool:
    """
    Return True if the URL host matches one of the known video sites.
    
    We intentionally keep this list small and explicit for determinism.
    This should be the only place that knows what a "video site" is.
    In the future, we can safely update VIDEO_HOSTS without touching routing logic.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is from a known video host, False otherwise
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    
    # Allow for subdomains like www.youtube.com, m.youtube.com, etc.
    return any(h in host for h in VIDEO_HOSTS)

