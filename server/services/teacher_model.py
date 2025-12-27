"""
Teacher Model integration for high-accuracy canonicalization.

The Teacher Model (GPT-5) is invoked when canonicalizer confidence < 0.92.
Teacher decides canonical topics and generates alias mappings.
"""
import logging
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TeacherCanonicalizationResult:
    """Result from Teacher Model canonicalization."""
    canonical_topic: str
    aliases: List[str]
    reasoning: Optional[str] = None


async def invoke_teacher_for_canonicalization(
    raw_topic: str,
    normalized_topic: str
) -> Optional[TeacherCanonicalizationResult]:
    """
    Invoke Teacher Model (GPT-5) to canonicalize a topic.
    
    Teacher decides:
    - Canonical topic name (singular, lowercase, token-safe)
    - List of aliases that should map to this canonical topic
    
    Args:
        raw_topic: Original raw topic from Nano router
        normalized_topic: Normalized topic string (after basic cleanup)
        
    Returns:
        TeacherCanonicalizationResult with canonical topic and aliases, or None if failed
    """
    try:
        import requests
        import os
        
        # Build teacher prompt
        prompt = f"""You are a high-accuracy topic canonicalization teacher for a Facts system.

Your task is to determine the canonical topic name and generate alias mappings.

Rules:
1. Canonical topic must be:
   - Singular (e.g., "crypto" not "cryptos")
   - Lowercase
   - Token-safe (alphanumeric + underscores only)
   - Short and clear (prefer "crypto" over "cryptocurrency")

2. Generate aliases that users might use for this topic:
   - Include plural forms
   - Include synonyms
   - Include common variations
   - Include the canonical topic itself

3. Be consistent: if "cryptocurrency" → "crypto", then "digital currency" → "crypto" too

Raw topic: {raw_topic}
Normalized: {normalized_topic}

Output JSON:
{{
  "canonical_topic": "crypto",
  "aliases": ["crypto", "cryptocurrency", "cryptocurrencies", "digital currency", "digital currencies", "virtual currency"],
  "reasoning": "Brief explanation of why this canonical topic was chosen"
}}

Output JSON only:"""
        
        # Call GPT-5 via AI Router (use high-accuracy reasoning model)
        AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")
        
        payload = {
            "role": "chatdo",
            "intent": "general_chat",  # Use general_chat to route to GPT-5
            "priority": "high",
            "privacyLevel": "normal",
            "costTier": "standard",  # Standard tier should route to GPT-5
            "input": {
                "messages": [
                    {"role": "system", "content": "You are a topic canonicalization expert. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
        }
        
        response = requests.post(
            AI_ROUTER_URL,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get("ok"):
            logger.error(f"[TEACHER] AI Router error: {data.get('error')}")
            return None
        
        # Extract content from response
        output_messages = data.get("output", {}).get("messages", [])
        if not output_messages:
            logger.error("[TEACHER] AI Router returned no messages")
            return None
        
        # Get the last assistant message
        assistant_message = None
        for msg in reversed(output_messages):
            if msg.get("role") == "assistant":
                assistant_message = msg
                break
        
        if not assistant_message:
            logger.error("[TEACHER] AI Router returned no assistant message")
            return None
        
        content = assistant_message.get("content", "").strip()
        
        # Parse JSON (extract from markdown if needed)
        json_text = content
        if json_text.startswith("```"):
            lines = json_text.split("\n")
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    json_lines.append(line)
            json_text = "\n".join(json_lines).strip()
        
        # Parse JSON
        try:
            data = json.loads(json_text)
            
            canonical_topic = data.get("canonical_topic", "").strip()
            aliases = data.get("aliases", [])
            reasoning = data.get("reasoning", "")
            
            if not canonical_topic:
                logger.error("[TEACHER] No canonical_topic in response")
                return None
            
            if not aliases:
                # At least include the canonical topic itself
                aliases = [canonical_topic]
            
            logger.info(
                f"[TEACHER] Canonicalized '{raw_topic}' → '{canonical_topic}' "
                f"with {len(aliases)} aliases"
            )
            
            return TeacherCanonicalizationResult(
                canonical_topic=canonical_topic,
                aliases=aliases,
                reasoning=reasoning
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"[TEACHER] Failed to parse JSON response: {e}")
            logger.error(f"[TEACHER] Response content: {content[:500]}")
            return None
            
    except Exception as e:
        logger.error(f"[TEACHER] Error invoking teacher: {e}", exc_info=True)
        return None

