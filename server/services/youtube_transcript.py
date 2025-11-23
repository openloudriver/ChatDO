"""
YouTube transcript service for Tier 1 (YouTube-only, Privacy OFF).
Uses youtube-transcript-api to get text transcripts directly.
No audio download or Whisper transcription.
"""
from __future__ import annotations

import logging
from typing import List
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)

logger = logging.getLogger(__name__)


class YouTubeTranscriptError(Exception):
    """Raised when YouTube transcript cannot be retrieved."""
    pass


def extract_youtube_video_id(url: str) -> str:
    """
    Extract YouTube video ID from various URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://m.youtube.com/watch?v=VIDEO_ID
    
    Args:
        url: YouTube URL
        
    Returns:
        Video ID string
        
    Raises:
        YouTubeTranscriptError: If video ID cannot be extracted
    """
    parsed = urlparse(url)
    
    # Standard watch URL
    if "youtube.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        video_id_list = query.get("v")
        if video_id_list and video_id_list[0]:
            return video_id_list[0]
    
    # Short youtu.be URL
    if "youtu.be" in parsed.netloc:
        # path is like "/VIDEO_ID"
        video_id = parsed.path.lstrip("/")
        if video_id:
            return video_id
    
    raise YouTubeTranscriptError(f"Could not extract YouTube video ID from URL: {url}")


def get_youtube_transcript(url: str, languages: List[str] | None = None) -> str:
    """
    Tier 1: Fetches transcript text for a YouTube video using youtube-transcript-api.
    
    NO fallbacks. Raises YouTubeTranscriptError if anything fails.
    
    Args:
        url: YouTube video URL
        languages: List of language codes to try (default: ["en", "en-US", "en-GB"])
        
    Returns:
        Full transcript text as a single string
        
    Raises:
        YouTubeTranscriptError: If transcript cannot be retrieved
    """
    if languages is None:
        languages = ["en", "en-US", "en-GB"]
    
    try:
        video_id = extract_youtube_video_id(url)
    except YouTubeTranscriptError:
        raise
    
    logger.info("get_youtube_transcript: fetching transcript for video_id=%s", video_id)
    
    try:
        # Create API instance and fetch transcript
        # The API uses fetch() method which returns a FetchedTranscript object
        api = YouTubeTranscriptApi()
        fetched_transcript = api.fetch(video_id, languages=languages)
        
    except (NoTranscriptFound, TranscriptsDisabled) as e:
        logger.warning("get_youtube_transcript: transcript unavailable video_id=%s error=%s", video_id, e)
        raise YouTubeTranscriptError(f"No transcript available for this video: {e}") from e
    except Exception as e:
        logger.exception("get_youtube_transcript: API error video_id=%s", video_id)
        raise YouTubeTranscriptError(f"YouTube transcript API error: {e}") from e
    
    # Join snippet texts into a single block for GPT-5
    # FetchedTranscript.snippets is a list of snippet objects with .text attribute
    transcript_text = " ".join(snippet.text for snippet in fetched_transcript.snippets if snippet.text)
    
    if not transcript_text.strip():
        raise YouTubeTranscriptError("YouTube transcript returned empty text")
    
    logger.info("get_youtube_transcript: success video_id=%s transcript_chars=%d", video_id, len(transcript_text))
    return transcript_text

