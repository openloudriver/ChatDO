"""
Video transcription service with 2-tier pipeline:
- Tier 1 (Privacy OFF): yt-dlp → OpenAI Whisper-1 → GPT-5
- Tier 2 (Privacy ON): yt-dlp → local Whisper-small → Llama-3.2
"""
import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .video_source import download_video_audio, cleanup_file
from .whisper_service import transcribe_file as transcribe_with_local_whisper

logger = logging.getLogger(__name__)

_openai_client: Optional["OpenAI"] = None


def get_openai_client() -> "OpenAI":
    """Get or create OpenAI client for hosted Whisper."""
    global _openai_client
    
    if not OPENAI_AVAILABLE:
        raise RuntimeError("openai package not installed - required for Tier 1 (hosted Whisper)")
    
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CHATDO_OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set – required for hosted Whisper")
        _openai_client = OpenAI(api_key=api_key)
        logger.info("OpenAI client initialized for Whisper transcription")
    
    return _openai_client


async def transcribe_with_openai_whisper(audio_path: Path) -> str:
    """
    Use OpenAI hosted Whisper (model='whisper-1') to transcribe an audio file.
    Returns plain text transcription.
    """
    client = get_openai_client()
    logger.info("Transcribing with OpenAI Whisper-1: %s", audio_path)
    
    loop = asyncio.get_event_loop()
    
    def _run() -> str:
        with audio_path.open("rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
            )
        # result is already a plain string when response_format="text"
        return str(result)
    
    transcript = await loop.run_in_executor(None, _run)
    logger.info("OpenAI Whisper-1 transcription complete: %d chars", len(transcript))
    return transcript


async def get_transcript_from_url(url: str, use_local_whisper: bool) -> str:
    """
    Download audio for a video URL and return its transcript.
    
    Args:
        url: Video URL (YouTube, Rumble, Bitchute, etc.)
        use_local_whisper: 
            - False → Tier 1 (yt-dlp + OpenAI Whisper-1)
            - True  → Tier 2 (yt-dlp + local Whisper-small)
    
    Returns:
        Full transcript text as a string
    """
    audio_path: Optional[Path] = None
    try:
        # Download audio using yt-dlp
        audio_path = await download_video_audio(url)
        
        # Transcribe using the appropriate Whisper
        if use_local_whisper:
            # Tier 2: local Whisper-small
            transcript = await transcribe_with_local_whisper(str(audio_path))
        else:
            # Tier 1: OpenAI Whisper-1
            transcript = await transcribe_with_openai_whisper(audio_path)
        
        if not transcript or not transcript.strip():
            raise RuntimeError("Transcription returned empty text")
        
        logger.info(
            "get_transcript_from_url: success url=%s use_local=%s transcript_chars=%d",
            url,
            use_local_whisper,
            len(transcript),
        )
        return transcript
        
    except Exception as e:
        logger.exception(
            "get_transcript_from_url: failed url=%s use_local=%s",
            url,
            use_local_whisper,
        )
        raise RuntimeError(f"Failed to obtain transcript for video: {e}") from e
    finally:
        # Clean up temporary audio file
        if audio_path:
            cleanup_file(audio_path)

