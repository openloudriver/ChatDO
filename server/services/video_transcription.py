"""
Video transcription service for Tier 2 (non-YouTube video hosts).
- Tier 2: yt-dlp → Whisper-small → GPT-5

Note: Tier 1 (YouTube-only) uses youtube-transcript-api directly
and does not call this service.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .video_source import download_video_audio, cleanup_file
from .whisper_service import transcribe_file as transcribe_with_whisper_small

logger = logging.getLogger(__name__)


async def get_transcript_from_url(url: str) -> str:
    """
    Tier 2: Download audio for a non-YouTube video URL and return its transcript.
    Uses yt-dlp to download audio, then local Whisper-small for transcription.
    
    Args:
        url: Video URL (Rumble, Bitchute, Archive.org, etc.)
    
    Returns:
        Full transcript text as a string
        
    Raises:
        RuntimeError: If download or transcription fails
    """
    audio_path: Optional[Path] = None
    try:
        # Download audio using yt-dlp
        audio_path = await download_video_audio(url)
        
        # Transcribe using local Whisper-small
        transcript = await transcribe_with_whisper_small(str(audio_path))
        
        if not transcript or not transcript.strip():
            raise RuntimeError("Transcription returned empty text")
        
        logger.info(
            "get_transcript_from_url: success url=%s transcript_chars=%d",
            url,
            len(transcript),
        )
        return transcript
        
    except Exception as e:
        logger.exception("get_transcript_from_url: failed url=%s", url)
        raise RuntimeError(f"Failed to obtain transcript for video: {e}") from e
    finally:
        # Clean up temporary audio file
        if audio_path:
            cleanup_file(audio_path)

