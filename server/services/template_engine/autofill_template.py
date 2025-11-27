"""
Autofill template fields using GPT-5 and captured impacts.
"""
import os
import json
import requests
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# AI-Router URL
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")


def autofill_template(
    template_text: str,
    fields: List[Dict[str, Any]],
    field_assignments: Dict[str, str],  # field_id -> impact_id
    impacts: List[Dict[str, Any]],  # List of impact entries
) -> str:
    """
    Autofill template fields using GPT-5 and assigned impacts.
    
    Args:
        template_text: Original template text
        fields: List of field definitions
        field_assignments: Mapping of field_id to impact_id
        impacts: List of all available impacts
        
    Returns:
        Filled template text with appended filled data
    """
    # Build impacts lookup
    impacts_dict = {impact["id"]: impact for impact in impacts}
    
    # Build field assignments with impact data
    assigned_impacts = {}
    for field_id, impact_id in field_assignments.items():
        if impact_id in impacts_dict:
            assigned_impacts[field_id] = impacts_dict[impact_id]
    
    system_prompt = """You are TemplateFillGPT.

Fill the provided template fields using the provided impacts.

You will receive:
1. Template fields that need to be filled
2. Captured impacts with relevant data

For each field, generate appropriate text based on the assigned impact(s).

Return ONLY a JSON object with field_id as keys and filled text as values:

{
  "field_id": "filled text here",
  "another_field": "more filled text"
}

Do not include markdown formatting. Return pure JSON only."""

    # Format fields for prompt
    fields_json = json.dumps(fields, indent=2)
    
    # Format impacts for prompt
    impacts_json = json.dumps(list(assigned_impacts.values()), indent=2)
    
    # Build field assignment mapping for clarity
    assignment_map = {
        field_id: {
            "impact_id": impact_id,
            "impact_title": impacts_dict.get(impact_id, {}).get("title", "Unknown")
        }
        for field_id, impact_id in field_assignments.items()
    }
    
    user_prompt = f"""Fill the template fields using the provided impacts.

TEMPLATE FIELDS:
{fields_json}

CAPTURED IMPACTS:
{impacts_json}

FIELD ASSIGNMENTS:
{json.dumps(assignment_map, indent=2)}

For each field_id in the assignments, generate appropriate text based on the corresponding impact data.

Return the JSON object with filled text for each field."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    payload = {
        "role": "chatdo",
        "intent": "doc_draft",
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
            filled_fields = json.loads(response_text)
            if not isinstance(filled_fields, dict):
                raise ValueError("AI did not return a JSON object")
            
            # Build output: original template + filled data section
            output_lines = [template_text]
            output_lines.append("\n" + "=" * 50)
            output_lines.append("FILLED DATA")
            output_lines.append("=" * 50 + "\n")
            
            # Add filled fields in order
            for field in fields:
                field_id = field["field_id"]
                if field_id in filled_fields:
                    label = field.get("label", field_id)
                    value = filled_fields[field_id]
                    output_lines.append(f"{label}: {value}\n")
            
            output_text = "\n".join(output_lines)
            logger.info(f"Generated autofilled template with {len(filled_fields)} fields")
            return output_text
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from AI response: {e}")
            logger.error(f"Response was: {response_text}")
            raise ValueError(f"Invalid JSON response from AI: {e}")
            
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to AI-Router: {e}")
        raise RuntimeError(f"AI-Router unavailable: {e}")
    except requests.exceptions.Timeout as e:
        logger.error(f"AI-Router request timed out: {e}")
        raise RuntimeError(f"AI-Router timeout: {e}")
    except Exception as e:
        logger.error(f"Template autofill failed: {e}", exc_info=True)
        raise

