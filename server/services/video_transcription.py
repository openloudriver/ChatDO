"""
Video transcription service for Tier 2 (non-YouTube video hosts).
- Tier 2: yt-dlp → Whisper-small-FP16 → GPT-5

Optimized for M1 Mac (FP16 + Metal acceleration) but portable.
Supports long-form audio (podcasts, webcasts) with chunking when needed.

Note: Tier 1 (YouTube-only) uses youtube-transcript-api directly
and does not call this service.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .video_source import download_video_audio, cleanup_file
from .whisper_service import transcribe_audio_with_whisper_small_fp16

logger = logging.getLogger(__name__)


async def get_transcript_from_url(url: str) -> str:
    """
    Tier 2: Download audio for a non-YouTube video URL and return its transcript.
    
    Pipeline: yt-dlp → Whisper-small-FP16 (M1-optimized) → GPT-5
    
    Optimized for M1 Mac with FP16 compute type and Metal acceleration.
    Handles long-form audio (podcasts, webcasts) efficiently.
    
    Args:
        url: Video URL (Rumble, Bitchute, Archive.org, etc.)
    
    Returns:
        Full transcript text as a string
        
    Raises:
        RuntimeError: If download or transcription fails
        ValueError: If URL is invalid or unsupported
    """
    audio_path: Optional[Path] = None
    try:
        # Parse URL for logging
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "").lower()
        
        logger.info(
            "get_transcript_from_url: starting Tier 2 pipeline url=%s host=%s",
            url,
            host,
        )
        
        # Download audio using yt-dlp
        audio_path = await download_video_audio(url)
        
        if not audio_path or not audio_path.exists():
            raise RuntimeError("yt-dlp did not produce a valid audio file")
        
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info(
            "get_transcript_from_url: audio downloaded url=%s size_mb=%.2f path=%s",
            url,
            file_size_mb,
            audio_path,
        )
        
        # Transcribe using local Whisper-small-FP16 (M1-optimized)
        # The whisper service handles FP16, Metal acceleration, and chunking internally
        transcript = await transcribe_audio_with_whisper_small_fp16(str(audio_path))
        
        if not transcript or not transcript.strip():
            raise RuntimeError("Transcription returned empty text")
        
        logger.info(
            "get_transcript_from_url: Tier 2 success url=%s host=%s transcript_chars=%d",
            url,
            host,
            len(transcript),
        )
        return transcript
        
    except Exception as e:
        logger.exception("get_transcript_from_url: Tier 2 failed url=%s", url)
        raise RuntimeError(f"Failed to obtain transcript for video: {e}") from e
    finally:
        # Clean up temporary audio file
        if audio_path:
            cleanup_file(audio_path)

