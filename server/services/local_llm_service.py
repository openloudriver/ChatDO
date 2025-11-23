"""
Local LLM service for privacy mode summarization.
Uses llama-cpp-python to run Llama-3.2 3B locally.
No OpenAI dependencies - strictly local.
"""
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional
from llama_cpp import Llama

logger = logging.getLogger(__name__)

_local_llm: Optional[Llama] = None


def get_local_llm() -> Llama:
    """
    Lazily load a local Llama model for summarization.
    Model path and params are configurable via environment variables.
    """
    global _local_llm

    if _local_llm is not None:
        return _local_llm

    # Get model path from env, or use default relative to project root
    env_path = os.getenv("LOCAL_SUMMARY_MODEL_PATH")
    if env_path:
        model_path = env_path
    else:
        # Default: look in project root's models/ directory
        # This file is in server/services/, so go up 2 levels to project root
        project_root = Path(__file__).parent.parent.parent
        model_path = str(project_root / "models" / "llama-3.2-3b-instruct.Q4_0.gguf")

    n_ctx = int(os.getenv("LOCAL_SUMMARY_CTX", "8192"))
    n_threads = int(os.getenv("LOCAL_SUMMARY_THREADS", "0"))  # 0 = auto
    n_gpu_layers = int(os.getenv("LOCAL_SUMMARY_N_GPU_LAYERS", "0"))

    logger.info(
        "Loading local LLM for summaries: model_path=%s n_ctx=%s n_threads=%s n_gpu_layers=%s",
        model_path,
        n_ctx,
        n_threads,
        n_gpu_layers,
    )

    _local_llm = Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
    )

    return _local_llm


SUMMARY_PROMPT_TEMPLATE_WEB = """You are a concise analyst. You are given the text of a web article or page.

Write a clear, compact summary and bullet-point key takeaways using this exact structure:

SUMMARY

- 2–4 sentences summarizing the core message and main arguments of the article.

KEY POINTS

- 4–8 bullet points covering the most important ideas, facts, and claims.

WHY THIS MATTERS

- 2–4 sentences explaining why the content is significant, who it affects, or what actions/risks/opportunities it implies.

Rules:

- Do NOT include any preamble like "Note:" or "Here is the summary:" or meta-commentary about what you are doing.

- Do NOT include any bullet that is just "..." or similar filler. Every bullet must be meaningful.

- Focus on the content of the article itself, not navigation, comments, or unrelated links.

- Use neutral, descriptive language (no hype, no exaggeration).

Article text:

{text}

"""

SUMMARY_PROMPT_TEMPLATE_VIDEO = """You are a concise analyst. You are given a transcript of a video.

Write a clear, compact summary and bullet-point key takeaways using this exact structure:

SUMMARY

- 2–4 sentences summarizing the core message and main arguments of the video.

KEY POINTS

- 4–8 bullet points covering the most important ideas, facts, and claims.

WHY THIS MATTERS

- 2–4 sentences explaining why the content is significant, who it affects, or what actions/risks/opportunities it implies.

Rules:

- Do NOT include any preamble like "Note:" or "Here is the summary:" or meta-commentary about what you are doing.

- Do NOT include any bullet that is just "..." or similar filler. Every bullet must be meaningful.

- Ignore filler speech, intros, outros, sponsor ads, and off-topic digressions.

- Use neutral, descriptive language (no hype, no exaggeration).

Transcript:

{text}

"""


async def summarize_text_locally(
    text: str,
    *,
    max_tokens: int = 800,
    mode: str = "web",
) -> str:
    """
    Summarize the given text using the local Llama model (privacy mode).
    This must not call any OpenAI APIs.
    
    Args:
        text: The text to summarize (article text or video transcript)
        max_tokens: Maximum tokens for the summary
        mode: "web" for articles or "video" for video transcripts
    """
    if not text or not text.strip():
        raise ValueError("Cannot summarize empty text.")

    llm = get_local_llm()
    
    # Select prompt template based on mode
    if mode == "video":
        prompt = SUMMARY_PROMPT_TEMPLATE_VIDEO.format(text=text)
        logger.info("Local summary: using video transcript prompt")
    else:
        prompt = SUMMARY_PROMPT_TEMPLATE_WEB.format(text=text)
        logger.info("Local summary: using web article prompt")

    loop = asyncio.get_event_loop()

    def _run():
        # llama-cpp-python returns a dict with "choices"
        result = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.2,
            top_p=0.9,
            stop=None,
        )

        # Some versions use "choices"[0]["text"], others may use "choices"[0]["message"]["content"]
        choice = result["choices"][0]
        if "text" in choice:
            return choice["text"]
        elif "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"]
        else:
            return str(choice)

    logger.info("Local summary: starting llama-cpp generation... mode=%s", mode)
    summary = await loop.run_in_executor(None, _run)
    logger.info("Local summary: completed; length=%s chars mode=%s", len(summary), mode)
    return summary.strip()

