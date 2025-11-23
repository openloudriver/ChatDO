"""
Local Whisper transcription service using faster-whisper.
Optimized for M1 Mac (FP16 + Metal acceleration) but portable to other hardware.

Tier 2 video transcription: yt-dlp → Whisper-small-FP16 → GPT-5
- Uses faster-whisper (CTranslate2 backend) for efficient inference
- Prefers FP16 compute type for reduced memory and better throughput on M1
- Automatically uses Metal/GPU acceleration on Apple Silicon when available
- Falls back to CPU/FP32 on non-Apple hardware or if GPU unavailable
"""
import asyncio
import logging
import os
import platform
from typing import Optional
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_MODEL = None


def _is_apple_silicon() -> bool:
    """Detect if running on Apple Silicon (M1/M2/M3/etc)."""
    return platform.processor() == "arm" or platform.machine() == "arm64"


def _get_optimal_device() -> str:
    """
    Determine optimal device for Whisper inference.
    - Apple Silicon: "auto" (faster-whisper will use Metal/GPU)
    - Other platforms: "cpu"
    """
    if _is_apple_silicon():
        return "auto"  # faster-whisper will auto-detect and use Metal on M1+
    return "cpu"


def _get_optimal_compute_type() -> list[str]:
    """
    Get optimal compute type order for current hardware.
    - M1 Mac: Prefer float16 for better performance and memory efficiency
    - Other platforms: Fall back to int8 or float32
    """
    if _is_apple_silicon():
        # M1+ benefits from FP16 with Metal acceleration
        return ["float16", "int8_float16", "int8", "float32"]
    else:
        # Non-Apple: prefer int8 for efficiency, fall back to float32
        return ["int8", "int8_float16", "float32"]


def get_whisper_model() -> WhisperModel:
    """
    Get or create the singleton Whisper model instance.
    Optimized for M1 Mac (FP16 + Metal) but portable.
    """
    global _MODEL
    if _MODEL is None:
        model_name = os.getenv("WHISPER_MODEL_NAME", "small")
        requested_compute_type = os.getenv("WHISPER_COMPUTE_TYPE")
        device = os.getenv("WHISPER_DEVICE") or _get_optimal_device()
        threads = int(os.getenv("WHISPER_THREADS", "0"))  # 0 = auto
        
        # Use requested compute type if provided, otherwise optimize for hardware
        if requested_compute_type:
            compute_types = [requested_compute_type]
        else:
            compute_types = _get_optimal_compute_type()
        
        # Remove duplicates while preserving order
        seen = set()
        compute_types = [ct for ct in compute_types if ct not in seen and not seen.add(ct)]
        
        logger.info(
            "Loading Whisper model: name=%s device=%s threads=%s compute_types=%s",
            model_name,
            device,
            threads if threads > 0 else "auto",
            compute_types,
        )
        
        loaded = False
        selected_compute_type = None
        
        for compute_type in compute_types:
            try:
                logger.info("Attempting to load Whisper model with compute_type=%s device=%s...", compute_type, device)
                
                # Build model args
                model_kwargs = {
                    "model_size_or_path": model_name,
                    "compute_type": compute_type,
                    "device": device,
                }
                if threads > 0:
                    model_kwargs["cpu_threads"] = threads
                
                _MODEL = WhisperModel(**model_kwargs)
                selected_compute_type = compute_type
                logger.info(
                    "Whisper model loaded successfully: compute_type=%s device=%s (optimized for M1: %s)",
                    compute_type,
                    device,
                    _is_apple_silicon(),
                )
                loaded = True
                break
            except Exception as e:
                logger.warning("Failed to load with compute_type=%s device=%s: %s", compute_type, device, e)
                # If device="auto" failed, try "cpu" as fallback
                if device == "auto":
                    try:
                        logger.info("Retrying with device=cpu...")
                        model_kwargs = {
                            "model_size_or_path": model_name,
                            "compute_type": compute_type,
                            "device": "cpu",
                        }
                        if threads > 0:
                            model_kwargs["cpu_threads"] = threads
                        _MODEL = WhisperModel(**model_kwargs)
                        selected_compute_type = compute_type
                        logger.info("Whisper model loaded with compute_type=%s device=cpu (fallback)", compute_type)
                        loaded = True
                        break
                    except Exception as e2:
                        logger.warning("Failed to load with compute_type=%s device=cpu: %s", compute_type, e2)
                        continue
                continue
        
        if not loaded:
            logger.exception("All compute type attempts failed for model %s", model_name)
            raise RuntimeError(f"Failed to load Whisper model {model_name} with any compute type")
        
        logger.info(
            "Selected Whisper config: model=%s compute_type=%s device=%s (M1 optimized: %s)",
            model_name,
            selected_compute_type,
            device,
            _is_apple_silicon(),
        )
    
    return _MODEL


async def transcribe_audio_with_whisper_small_fp16(
    audio_path: str,
    *,
    language: Optional[str] = None,
) -> str:
    """
    Transcribe audio using Whisper-small with FP16 optimization (M1-optimized).
    
    This is the Tier 2 transcription path: optimized for M1 Mac (FP16 + Metal)
    but portable to other hardware with automatic fallbacks.
    
    Args:
        audio_path: Path to audio/video file
        language: Optional language code (e.g., "en"). If None, auto-detect.
        
    Returns:
        Full transcript text as a single string
        
    Raises:
        FileNotFoundError: If audio file doesn't exist
        RuntimeError: If transcription fails
    """
    loop = asyncio.get_event_loop()

    def _run() -> str:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        model = get_whisper_model()
        logger.info(
            "transcribe_audio_with_whisper_small_fp16: starting transcription file=%s language=%s",
            audio_path,
            language or "auto",
        )
        
        # Transcribe with faster-whisper
        # The model is already configured for optimal compute type and device
        segments, info = model.transcribe(audio_path, language=language)
        
        # Collect all segment texts
        text_parts = []
        for seg in segments:
            if seg.text and seg.text.strip():
                text_parts.append(seg.text.strip())
        
        full_text = " ".join(text_parts).strip()
        
        # Log transcription metadata if available
        duration = getattr(info, "duration", None)
        if duration:
            logger.info(
                "transcribe_audio_with_whisper_small_fp16: finished file=%s duration=%.1fs chars=%d",
                audio_path,
                duration,
                len(full_text),
            )
        else:
            logger.info(
                "transcribe_audio_with_whisper_small_fp16: finished file=%s chars=%d",
                audio_path,
                len(full_text),
            )
        
        if not full_text:
            raise RuntimeError("Transcription returned empty text")
        
        return full_text

    return await loop.run_in_executor(None, _run)


# Alias for backward compatibility
async def transcribe_file(path: str, *, language: Optional[str] = None) -> str:
    """
    Alias for transcribe_audio_with_whisper_small_fp16 (backward compatibility).
    """
    return await transcribe_audio_with_whisper_small_fp16(path, language=language)

