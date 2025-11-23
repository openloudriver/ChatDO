"""
Video transcription service with 2-tier pipeline:
- Tier 1 (Privacy OFF): yt-dlp → OpenAI Whisper-1 → GPT-5
- Tier 2 (Privacy ON): yt-dlp → Whisper-small → Llama-3.2
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

# OpenAI Whisper-1 pricing: $0.006 per minute of audio
WHISPER_PRICE_PER_MINUTE = 0.006


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
    Also records usage cost to the AI Router.
    """
    client = get_openai_client()
    logger.info("Transcribing with OpenAI Whisper-1: %s", audio_path)
    
    # Get audio duration for cost calculation
    duration_seconds = None
    try:
        # Try using ffprobe first (most reliable)
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            duration_seconds = float(result.stdout.strip())
    except Exception:
        # If ffprobe fails, try mutagen (if available)
        try:
            from mutagen import File
            audio_file = File(str(audio_path))
            if audio_file is not None and hasattr(audio_file, 'info') and hasattr(audio_file.info, 'length'):
                duration_seconds = audio_file.info.length
        except Exception:
            pass
    
    if duration_seconds is None:
        logger.warning("Could not determine audio duration for Whisper cost calculation - usage will not be tracked")
    
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
    
    # Record usage cost to AI Router
    if duration_seconds is not None:
        duration_minutes = duration_seconds / 60.0
        cost_usd = duration_minutes * WHISPER_PRICE_PER_MINUTE
        
        # Record usage via AI Router endpoint
        ai_router_url = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")
        base_url = ai_router_url.rsplit("/v1/ai/run", 1)[0]
        record_url = f"{base_url}/v1/ai/spend/record"
        
        try:
            import requests
            requests.post(
                record_url,
                json={
                    "providerId": "openai-whisper-1",  # Separate provider ID for Whisper-1
                    "modelId": "whisper-1",
                    "costUsd": cost_usd,
                },
                timeout=5
            )
            logger.info("Recorded Whisper-1 usage: %.2f minutes, $%.6f", duration_minutes, cost_usd)
        except Exception as e:
            logger.warning("Failed to record Whisper-1 usage: %s", e)
    
    return transcript


async def get_transcript_from_url(url: str, use_local_whisper: bool) -> str:
    """
    Download audio for a video URL and return its transcript.
    
    Args:
        url: Video URL (YouTube, Rumble, Bitchute, etc.)
        use_local_whisper: 
            - False → Tier 1 (yt-dlp + OpenAI Whisper-1)
            - True  → Tier 2 (yt-dlp + Whisper-small)
    
    Returns:
        Full transcript text as a string
    """
    audio_path: Optional[Path] = None
    try:
        # Download audio using yt-dlp
        audio_path = await download_video_audio(url)
        
        # Transcribe using the appropriate Whisper
        if use_local_whisper:
            # Tier 2: Whisper-small (no cost tracking)
            transcript = await transcribe_with_local_whisper(str(audio_path))
        else:
            # Tier 1: OpenAI Whisper-1 (tracks usage cost)
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

