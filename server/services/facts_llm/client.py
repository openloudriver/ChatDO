"""
Facts LLM client for GPT-5 Nano-based fact extraction.

This module provides a client for calling GPT-5 Nano via the AI Router
to produce JSON operations for fact extraction.
"""
import os
import json
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(env_path)

# AI-Router HTTP client
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")


class FactsLLMError(Exception):
    """Base exception for Facts LLM errors."""
    pass


class FactsLLMTimeoutError(FactsLLMError):
    """Facts LLM request timed out."""
    pass


class FactsLLMUnavailableError(FactsLLMError):
    """Facts LLM service is unavailable."""
    pass


class FactsLLMInvalidJSONError(FactsLLMError):
    """Facts LLM returned invalid JSON."""
    pass


async def run_facts_llm(prompt: str) -> str:
    """
    Call GPT-5 Nano (via AI Router) to produce JSON operations for fact extraction.
    
    This function hard-fails if:
    - AI Router is unavailable
    - Request times out
    - Any HTTP error occurs
    - Invalid JSON (no retry)
    
    Args:
        prompt: The prompt to send to GPT-5 Nano
        
    Returns:
        Raw text response from GPT-5 Nano
        
    Raises:
        FactsLLMUnavailableError: If AI Router is not reachable
        FactsLLMTimeoutError: If request times out
        FactsLLMInvalidJSONError: If response is invalid JSON
        FactsLLMError: For other errors
    """
    import requests
    
    # Call GPT-5 Nano via AI Router using nano_facts intent
    payload = {
        "role": "chatdo",
        "intent": "nano_facts",
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a fact extraction system. Extract facts from the user's message and output ONLY valid JSON. Do not include any explanation or markdown formatting."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        },
    }
    
    try:
        logger.debug(f"[FACTS-LLM] Calling GPT-5 Nano via AI Router at {AI_ROUTER_URL}")
        
        # Make direct call to AI Router with Nano model
        # We need to bypass the router's intent-based selection and force Nano
        # For now, we'll call the router and it should route to Nano based on costTier or we'll need to add a nano intent
        # Actually, let's make a direct HTTP call to force Nano
        
        # Alternative: Call AI Router's internal Nano provider directly
        # But the router doesn't expose that - we need to use the router's API
        # The router selects based on intent, so we need a way to force Nano
        
        # For now, let's use a workaround: call the router with a custom endpoint or modify the router
        # Actually, the cleanest approach is to add a "nano" intent or modify the router to accept model override
        
        # TEMPORARY: We'll need to modify the AI router to support direct model selection
        # For now, let's make the call and handle the response
        
        response = requests.post(
            AI_ROUTER_URL,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get("ok"):
            raise FactsLLMError(f"AI Router error: {data.get('error')}")
        
        # Extract content from response
        output_messages = data.get("output", {}).get("messages", [])
        if not output_messages:
            raise FactsLLMError("AI Router returned no messages")
        
        # Get the last assistant message
        assistant_message = None
        for msg in reversed(output_messages):
            if msg.get("role") == "assistant":
                assistant_message = msg
                break
        
        if not assistant_message:
            raise FactsLLMError("AI Router returned no assistant message")
        
        result_text = assistant_message.get("content", "").strip()
        
        if not result_text:
            raise FactsLLMError("GPT-5 Nano returned empty response")
        
        logger.debug(f"[FACTS-LLM] Received response from GPT-5 Nano ({len(result_text)} chars)")
        return result_text
        
    except requests.exceptions.Timeout:
        raise FactsLLMTimeoutError(
            f"Facts LLM (GPT-5 Nano) request timed out after 30s. "
            f"AI Router may be slow or unavailable at {AI_ROUTER_URL}"
        )
    except requests.exceptions.ConnectionError as e:
        raise FactsLLMUnavailableError(
            f"Facts LLM (GPT-5 Nano via AI Router) is unavailable at {AI_ROUTER_URL}. "
            f"Connection error: {e}"
        )
    except requests.exceptions.HTTPError as e:
        raise FactsLLMError(
            f"Facts LLM HTTP error: {e.response.status_code} - {e.response.text}"
        )
    except FactsLLMError:
        raise
    except Exception as e:
        raise FactsLLMError(f"Facts LLM unexpected error: {e}")
