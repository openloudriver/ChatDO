"""
Local Whisper transcription service using faster-whisper.
No OpenAI dependencies - purely local transcription.
"""
import asyncio
import logging
import os
from typing import Optional
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_MODEL = None


def get_whisper_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        model_name = os.getenv("WHISPER_MODEL_NAME", "small")
        requested_compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        logger.info("Loading Whisper model name=%s compute_type=%s", model_name, requested_compute_type)
        
        # Try compute types in order: requested, int8_float16, int8, float32
        compute_types = [
            requested_compute_type,
            "int8_float16",
            "int8",
            "float32",
        ]
        # Remove duplicates while preserving order
        seen = set()
        compute_types = [ct for ct in compute_types if ct not in seen and not seen.add(ct)]
        
        loaded = False
        selected_compute_type = None
        
        for compute_type in compute_types:
            try:
                logger.info("Attempting to load Whisper model with compute_type=%s...", compute_type)
                _MODEL = WhisperModel(model_name, compute_type=compute_type)
                selected_compute_type = compute_type
                logger.info("Whisper model loaded successfully with compute_type=%s", compute_type)
                loaded = True
                break
            except Exception as e:
                logger.warning("Failed to load with compute_type=%s: %s", compute_type, e)
                continue
        
        if not loaded:
            logger.exception("All compute type attempts failed for model %s", model_name)
            raise RuntimeError(f"Failed to load Whisper model {model_name} with any compute type")
        
        logger.info("Selected compute_type=%s for Whisper model %s", selected_compute_type, model_name)
    
    return _MODEL


async def transcribe_file(path: str, *, language: Optional[str] = None) -> str:
    """
    Run local Whisper on the given audio/video file and return the full transcript text.
    
    Args:
        path: Path to audio/video file
        language: Optional language code (e.g., "en"). If None, auto-detect.
        
    Returns:
        Full transcript text as a single string
    """
    loop = asyncio.get_event_loop()

    def _run() -> str:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Audio file not found: {path}")
        
        model = get_whisper_model()
        logger.info("transcribe_file: starting transcription file=%s", path)
        
        segments, _info = model.transcribe(path, language=language)
        text_parts = [seg.text for seg in segments]
        full_text = " ".join(text_parts).strip()
        
        logger.info("transcribe_file: finished transcription file=%s chars=%d", path, len(full_text))
        return full_text

    return await loop.run_in_executor(None, _run)

