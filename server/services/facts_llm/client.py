"""
Facts LLM client for Qwen-based fact extraction.

This module provides a strict, non-retrying client for calling Qwen2.5 7B Instruct
via Ollama (or other local runner) to produce JSON operations for fact extraction.
"""
import os
import requests
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(env_path)

# Configuration from environment
FACTS_LLM_PROVIDER = os.getenv("FACTS_LLM_PROVIDER", "ollama")
FACTS_LLM_MODEL = os.getenv("FACTS_LLM_MODEL", "qwen2.5:7b-instruct")
FACTS_LLM_URL = os.getenv("FACTS_LLM_URL", "http://127.0.0.1:11434")
FACTS_LLM_TIMEOUT_S = int(os.getenv("FACTS_LLM_TIMEOUT_S", "12"))


class FactsLLMError(Exception):
    """Base exception for Facts LLM errors."""
    pass


class FactsLLMTimeoutError(FactsLLMError):
    """Facts LLM request timed out."""
    pass


class FactsLLMUnavailableError(FactsLLMError):
    """Facts LLM service is unavailable."""
    pass


def run_facts_llm(prompt: str) -> str:
    """
    Call Qwen LLM (via Ollama) with strict timeout and no retries.
    
    This function hard-fails if:
    - Ollama is unavailable
    - Request times out
    - Any HTTP error occurs
    
    Args:
        prompt: The prompt to send to the LLM
        
    Returns:
        Raw text response from the LLM
        
    Raises:
        FactsLLMUnavailableError: If Ollama is not reachable
        FactsLLMTimeoutError: If request times out
        FactsLLMError: For other errors
    """
    if FACTS_LLM_PROVIDER != "ollama":
        raise FactsLLMError(
            f"Unsupported Facts LLM provider: {FACTS_LLM_PROVIDER}. "
            "Only 'ollama' is currently supported."
        )
    
    url = f"{FACTS_LLM_URL}/api/generate"
    
    payload = {
        "model": FACTS_LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,  # Low temperature for deterministic JSON output
            "top_p": 0.9,
        }
    }
    
    try:
        logger.debug(f"[FACTS-LLM] Calling {url} with model {FACTS_LLM_MODEL}")
        response = requests.post(
            url,
            json=payload,
            timeout=FACTS_LLM_TIMEOUT_S
        )
        response.raise_for_status()
        
        data = response.json()
        result_text = data.get("response", "").strip()
        
        if not result_text:
            raise FactsLLMError("Facts LLM returned empty response")
        
        logger.debug(f"[FACTS-LLM] Received response ({len(result_text)} chars)")
        return result_text
        
    except requests.exceptions.Timeout:
        raise FactsLLMTimeoutError(
            f"Facts LLM request timed out after {FACTS_LLM_TIMEOUT_S}s. "
            f"Ollama may be slow or unavailable at {FACTS_LLM_URL}"
        )
    except requests.exceptions.ConnectionError as e:
        raise FactsLLMUnavailableError(
            f"Facts LLM (Ollama) is unavailable at {FACTS_LLM_URL}. "
            f"Connection error: {e}"
        )
    except requests.exceptions.HTTPError as e:
        raise FactsLLMError(
            f"Facts LLM HTTP error: {e.response.status_code} - {e.response.text}"
        )
    except Exception as e:
        raise FactsLLMError(f"Facts LLM unexpected error: {e}")

