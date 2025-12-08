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
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .video_source import download_video_audio, cleanup_file
from .whisper_service import transcribe_audio_with_whisper_small_fp16

logger = logging.getLogger(__name__)

# Global Whisper semaphore (limit = 1) to serialize video transcriptions
# This is created here to avoid circular import issues with server.main
# server.main will import this if needed, but we create it here
_whisper_semaphore = None

def get_whisper_semaphore():
    """Get or create the global Whisper semaphore."""
    global _whisper_semaphore
    if _whisper_semaphore is None:
        _whisper_semaphore = asyncio.Semaphore(1)
    return _whisper_semaphore


async def get_transcript_from_url(url: str, conversation_id: Optional[str] = None) -> str:
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
        
        conversation_id_str = conversation_id or "unknown"
        logger.info(
            "get_transcript_from_url: starting Tier 2 pipeline url=%s host=%s conversation=%s",
            url,
            host,
            conversation_id_str,
        )
        
        # Download audio using yt-dlp with timing
        t_download_start = time.time()
        audio_path = await download_video_audio(url)
        t_download_end = time.time()
        
        if not audio_path or not audio_path.exists():
            raise RuntimeError("yt-dlp did not produce a valid audio file")
        
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info(
            f"[Summary] yt-dlp download finished in {t_download_end - t_download_start:.2f}s for conversation={conversation_id_str} url={url[:80]} size_mb={file_size_mb:.2f}"
        )
        
        # ----- Global Whisper Lock -----
        whisper_semaphore = get_whisper_semaphore()
        # Check if Whisper is already in use
        if whisper_semaphore.locked():
            logger.info(f"[Summary] Whisper busy — conversation={conversation_id_str} will wait for lock")
        else:
            logger.info(f"[Summary] Whisper available — acquiring lock for conversation={conversation_id_str}")
        
        # Acquire semaphore (only 1 Whisper transcription at a time globally)
        async with whisper_semaphore:
            logger.info(f"[Summary] Whisper lock acquired for conversation={conversation_id_str}")
            t_whisper_start = time.time()
            
            # Transcribe using local Whisper-small-FP16 (M1-optimized)
            # The whisper service handles FP16, Metal acceleration, and chunking internally
            transcript = await transcribe_audio_with_whisper_small_fp16(str(audio_path))
            
            t_whisper_end = time.time()
            logger.info(f"[Summary] Whisper transcription finished in {t_whisper_end - t_whisper_start:.2f}s for conversation={conversation_id_str}")
        
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

