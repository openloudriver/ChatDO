"""
Analyze templates to identify fillable fields using GPT-5.
"""
import os
import json
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# AI-Router URL
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")


def analyze_template(template_text: str) -> List[Dict[str, Any]]:
    """
    Analyze template text to identify fillable fields using GPT-5.
    
    Args:
        template_text: Extracted text from the template
        
    Returns:
        List of field dictionaries with field_id, label, and instructions
    """
    system_prompt = """You are TemplateAnalyzerGPT.

You receive a template file's extracted text.

Identify all fields that appear fillable or require data.

Extract them as a JSON array:

[
  { "field_id": "short_title", "label": "Short Title", "instructions": "One-line summary of the action" },
  { "field_id": "impact", "label": "Impact Narrative", "instructions": "Summarize why it mattered." }
]

Return ONLY JSON. No markdown, no explanation, just the JSON array.

If no fields exist, return [].

Field IDs should be:
- Short, lowercase, underscore-separated (e.g., "short_title", "impact_narrative")
- Descriptive of what the field contains
- Unique within the template

Labels should be:
- Human-readable names as they appear in the template
- Clear and descriptive

Instructions should be:
- Brief guidance on what to fill in this field
- Based on the template's context and requirements"""

    user_prompt = f"""Analyze this template and identify all fillable fields:

{template_text}

Return the JSON array of fields."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    payload = {
        "role": "chatdo",
        "intent": "general_chat",
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": messages,
        },
    }
    
    try:
        resp = requests.post(AI_ROUTER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("ok"):
            raise RuntimeError(f"AI-Router error: {data.get('error')}")
        
        response_text = data["output"]["messages"][0]["content"]
        
        # Extract JSON from response (handle markdown code blocks if present)
        response_text = response_text.strip()
        if response_text.startswith("```"):
            # Remove markdown code blocks
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
        
        # Parse JSON
        try:
            fields = json.loads(response_text)
            if not isinstance(fields, list):
                logger.warning(f"AI returned non-list: {fields}, wrapping in list")
                fields = [fields] if isinstance(fields, dict) else []
            
            # Validate field structure
            validated_fields = []
            for field in fields:
                if isinstance(field, dict) and "field_id" in field:
                    validated_fields.append({
                        "field_id": field["field_id"],
                        "label": field.get("label", field["field_id"]),
                        "instructions": field.get("instructions", ""),
                    })
            
            logger.info(f"Identified {len(validated_fields)} fields in template")
            return validated_fields
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from AI response: {e}")
            logger.error(f"Response was: {response_text}")
            return []
            
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to AI-Router: {e}")
        raise RuntimeError(f"AI-Router unavailable: {e}")
    except requests.exceptions.Timeout as e:
        logger.error(f"AI-Router request timed out: {e}")
        raise RuntimeError(f"AI-Router timeout: {e}")
    except Exception as e:
        logger.error(f"Template analysis failed: {e}", exc_info=True)
        raise

