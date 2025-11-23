"""
YouTube transcript service for Tier 1 (YouTube-only, Privacy OFF).
Uses youtube-transcript-api to get text transcripts directly.
No audio download or Whisper transcription.
"""
import logging
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    CouldNotRetrieveTranscript,
)

logger = logging.getLogger(__name__)


class YouTubeTranscriptError(Exception):
    """Raised when YouTube transcript cannot be retrieved."""
    pass


def _extract_youtube_video_id(url: str) -> str:
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
    
    if parsed.netloc.endswith("youtu.be"):
        # path is like "/VIDEO_ID"
        video_id = parsed.path.lstrip("/")
        if video_id:
            return video_id
    
    if parsed.netloc.endswith("youtube.com"):
        qs = parse_qs(parsed.query)
        vid_list = qs.get("v")
        if vid_list and vid_list[0]:
            return vid_list[0]
    
    raise YouTubeTranscriptError("Could not extract YouTube video id from URL.")


def get_youtube_transcript(url: str) -> str:
    """
    Get YouTube transcript using youtube-transcript-api.
    
    This is Tier 1: YouTube-only, text-based, no audio download.
    If this fails, we do NOT fall back to audio pipeline.
    
    Args:
        url: YouTube video URL
        
    Returns:
        Full transcript text as a single string
        
    Raises:
        YouTubeTranscriptError: If transcript cannot be retrieved
    """
    video_id = _extract_youtube_video_id(url)
    logger.info("get_youtube_transcript: fetching transcript for video_id=%s", video_id)
    
    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
    except (NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript) as e:
        logger.warning("get_youtube_transcript: transcript unavailable video_id=%s error=%s", video_id, e)
        raise YouTubeTranscriptError(f"YouTube transcript unavailable: {e}") from e
    except Exception as e:
        logger.exception("get_youtube_transcript: API error video_id=%s", video_id)
        raise YouTubeTranscriptError(f"YouTube transcript API error: {e}") from e
    
    # Concatenate all text segments into a single transcript string
    transcript_text = " ".join(s.get("text", "") for s in segments if s.get("text"))
    
    if not transcript_text.strip():
        raise YouTubeTranscriptError("YouTube transcript returned empty text")
    
    logger.info("get_youtube_transcript: success video_id=%s transcript_chars=%d", video_id, len(transcript_text))
    return transcript_text

