"""
Video transcription services for both Privacy Mode and non-privacy mode.
"""
import logging
from pathlib import Path
from typing import Optional
from .video_source import is_video_url, download_video_audio, cleanup_file
from .whisper_service import transcribe_file  # local Whisper using faster-whisper

logger = logging.getLogger(__name__)


def is_youtube_url(url: str) -> bool:
    """
    Legacy function for backward compatibility.
    Checks if URL is YouTube (used by non-privacy mode).
    """
    return "youtube.com/watch" in url or "youtu.be/" in url


async def get_transcript_from_url(url: str) -> str:
    """
    Returns transcript text for the given URL (non-privacy mode, YouTube only).
    
    Current behavior:
    - If URL is YouTube: always download audio via yt-dlp and run local Whisper.
    - For non-YouTube URLs: raise ValueError (these should be handled by HTML/article summarizer).
    """
    if not is_youtube_url(url):
        logger.info("get_transcript_from_url: non-YouTube URL, not handled here url=%s", url)
        raise ValueError("Only YouTube URLs are supported for video transcription at this time.")

    logger.info("get_transcript_from_url: starting for url=%s", url)

    audio_path: Optional[Path] = None
    try:
        # 1) Download audio
        audio_path = await download_video_audio(url)

        # 2) Run local Whisper
        transcript = await transcribe_file(str(audio_path))

        if not transcript or not transcript.strip():
            raise RuntimeError("Whisper returned an empty transcript.")

        logger.info(
            "get_transcript_from_url: success url=%s transcript_chars=%d",
            url,
            len(transcript),
        )
        return transcript

    except Exception as e:
        logger.exception("get_transcript_from_url: failed for url=%s", url)
        raise RuntimeError(f"Failed to obtain transcript for video: {e}") from e

    finally:
        # Best-effort cleanup
        if audio_path:
            cleanup_file(audio_path)


async def get_local_video_transcript(url: str) -> str:
    """
    Privacy-mode video transcription:
    - Detects supported video URLs (YouTube, Rumble, Bitchute, etc.).
    - Downloads audio via yt-dlp.
    - Runs Whisper-small locally to get transcript.
    - Cleans up temp audio file.
    
    This is fully local - no GPT-5 or OpenAI calls.
    """
    if not is_video_url(url):
        logger.info("get_local_video_transcript: non-video URL url=%s", url)
        raise ValueError("URL does not look like a supported video source.")

    logger.info("get_local_video_transcript: starting for url=%s", url)

    audio_path: Optional[Path] = None
    try:
        # 1) Download audio
        audio_path = await download_video_audio(url)

        # 2) Run local Whisper
        transcript = await transcribe_file(str(audio_path))

        if not transcript or not transcript.strip():
            raise RuntimeError("Whisper transcription returned empty text")

        logger.info(
            "get_local_video_transcript: success url=%s transcript_chars=%d",
            url,
            len(transcript),
        )
        return transcript

    except ValueError as ve:
        # URL validation error - log and re-raise as-is
        logger.warning("get_local_video_transcript: invalid video URL url=%s error=%s", url, str(ve))
        raise
    except RuntimeError as re:
        # Audio download or transcription error - log full details but keep user-friendly message
        logger.exception(
            "get_local_video_transcript: failed for url=%s error_type=%s error=%s",
            url,
            type(re).__name__,
            str(re),
        )
        # Keep the user-facing message unchanged for consistency
        raise RuntimeError("Failed to obtain transcript for video") from re
    except Exception as e:
        # Unexpected errors - log everything
        logger.exception(
            "get_local_video_transcript: unexpected error for url=%s error_type=%s",
            url,
            type(e).__name__,
        )
        raise RuntimeError(f"Failed to obtain transcript for video: {e}") from e

    finally:
        # Best-effort cleanup
        if audio_path:
            cleanup_file(audio_path)
