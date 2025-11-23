"""
Video source detection and audio extraction for Privacy Mode.
Supports multiple video platforms via yt-dlp.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)

# Supported video hosts
SUPPORTED_VIDEO_HOSTS = [
    "youtube.com",
    "youtu.be",
    "rumble.com",
    "bitchute.com",
    "odysee.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "vimeo.com",
]


def is_video_url(url: str) -> bool:
    """
    Returns True if the URL looks like it's from a known video host.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        # Strip www. prefix if present
        host = host.replace("www.", "")
        
        # Check if any supported host is contained in the hostname
        for supported_host in SUPPORTED_VIDEO_HOSTS:
            if supported_host in host:
                return True
        return False
    except Exception as e:
        logger.warning("is_video_url: error parsing URL %s: %s", url, e)
        return False


def get_ffmpeg_path() -> str:
    """
    Returns the ffmpeg binary path.
    - Reads FFMPEG_PATH from env
    - Falls back to 'ffmpeg' (rely on PATH) if not set
    """
    return os.getenv("FFMPEG_PATH", "ffmpeg")


async def download_video_audio(url: str) -> Path:
    """
    Download audio from the given video URL using yt-dlp.
    Returns a pathlib.Path to the downloaded audio file.
    Raises RuntimeError on failure with a clear message.
    """
    loop = asyncio.get_event_loop()
    ffmpeg_path = get_ffmpeg_path()

    def _download() -> str:
        logger.info("download_video_audio: starting download url=%s ffmpeg=%s", url, ffmpeg_path)

        tmp_dir = Path("data") / "tmp_audio"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "ffmpeg_location": ffmpeg_path,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        except Exception as e:
            # Check if it's a yt-dlp DownloadError specifically
            error_type = type(e).__name__
            error_msg = str(e)
            logger.exception(
                "download_video_audio: yt-dlp error for url=%s error_type=%s error=%s",
                url,
                error_type,
                error_msg,
            )
            raise RuntimeError(f"yt-dlp failed to download audio for url={url}") from e

        file_path = Path(filename)
        if not file_path.exists():
            logger.error("download_video_audio: file was not created by yt-dlp (path=%s)", file_path)
            raise RuntimeError("yt-dlp did not produce an audio file")

        logger.info(
            "download_video_audio: download complete url=%s file=%s size=%s bytes",
            url,
            file_path,
            file_path.stat().st_size,
        )
        return str(file_path)

    try:
        file_path_str = await loop.run_in_executor(None, _download)
        return Path(file_path_str)
    except Exception:
        logger.exception("download_video_audio: error while downloading audio for %s", url)
        raise


def cleanup_file(path: Path) -> None:
    """
    Best-effort cleanup of temporary audio file.
    """
    try:
        if path.exists():
            path.unlink(missing_ok=True)
            logger.info("cleanup_file: removed temp audio file %s", path)
    except Exception:
        logger.warning("cleanup_file: failed to remove temp file %s", path, exc_info=True)

