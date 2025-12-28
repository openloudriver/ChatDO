"""
Nano Router - Control plane that uses GPT-5 Nano to route messages.

This is the mandatory first step for EVERY message. Nano acts as the router/control plane
and determines the execution path with extracted candidates to avoid double Nano calls.
"""
import os
import json
import logging
import requests
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

from server.contracts.routing_plan import RoutingPlan

logger = logging.getLogger(__name__)

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(env_path)

# AI-Router HTTP client
AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://localhost:8081/v1/ai/run")

# JSON Schema for RoutingPlan (for OpenAI response_format)
ROUTING_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "content_plane": {
            "type": "string",
            "enum": ["facts", "index", "files", "chat"]
        },
        "operation": {
            "type": "string",
            "enum": ["write", "read", "search", "none"]
        },
        "reasoning_required": {
            "type": "boolean"
        },
        "facts_write_candidate": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "value": {
                    # OpenAI JSON schema doesn't support oneOf, so we use anyOf
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}}
                    ]
                },
                "rank_ordered": {"type": "boolean"}
            },
            "required": ["topic", "value", "rank_ordered"],  # All properties required for OpenAI JSON schema
            "additionalProperties": False
        },
        "facts_read_candidate": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "query": {"type": "string"}
            },
            "required": ["topic", "query"],
            "additionalProperties": False
        },
        "index_candidate": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "files_candidate": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path_hint": {"type": "string"}
            },
            "required": ["query", "path_hint"],  # All properties required for OpenAI JSON schema
            "additionalProperties": False
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0
        },
        "why": {
            "type": "string"
        }
    },
    "required": ["content_plane", "operation", "reasoning_required", "confidence"],
    "additionalProperties": False
}


class NanoRouterError(Exception):
    """Base exception for Nano Router errors."""
    pass


class NanoRouterSchemaError(NanoRouterError):
    """Nano Router returned invalid schema."""
    pass


async def route_with_nano(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    retry_on_schema_error: bool = True
) -> RoutingPlan:
    """
    Route a user message using GPT-5 Nano to determine execution path.
    
    This is the mandatory first step for EVERY message. Nano determines:
    - content_plane: facts | index | files | chat
    - operation: write | read | search | none
    - reasoning_required: boolean
    - Extracted candidates to avoid double Nano calls
    
    Args:
        user_message: The user's message
        conversation_history: Optional conversation history for context
        retry_on_schema_error: Whether to retry once on schema validation failure
        
    Returns:
        RoutingPlan with complete routing decision and extracted candidates
        
    Raises:
        NanoRouterError: If Nano router fails
        NanoRouterSchemaError: If schema validation fails (after retry)
    """
    # Build routing prompt with HARD INVARIANTS
    history_context = ""
    if conversation_history:
        history_lines = []
        for msg in conversation_history[-5:]:  # Last 5 messages for context
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]  # Truncate long messages
            history_lines.append(f"{role}: {content}")
        if history_lines:
            history_context = "\n\nRecent conversation:\n" + "\n".join(history_lines)
    
    # Build the routing prompt with CRITICAL PATTERN MATCHING at the top
    routing_prompt = f"""You are a deterministic message router. Your ONLY job is to classify the user's message and output JSON.

PATTERN MATCHING RULES (CHECK THESE FIRST, IN ORDER):

RULE 1: "My favorite" + topic + "is/are" + value(s) OR numbered lists with "favorite"
IF the message contains ANYWHERE (not just at the start):
  a) The pattern "favorite" (or "favorites") + topic word + "is" or "are" + value(s), OR
  b) A numbered list (1), 2), 3) or 1. 2. 3.) with "favorite" + topic in the same message:
  → content_plane="facts"
  → operation="write"
  → reasoning_required=false
  → facts_write_candidate MUST be populated:
    - topic: extract the topic word (e.g., "crypto", "colors", "candy", "cryptocurrency", "cryptos")
    - value: extract the value(s) as string or array
      * Single value: "My favorite candy is Reese's" → value="Reese's"
      * Multiple values: "My favorite colors are red, white, blue" → value=["red", "white", "blue"]
      * Numbered list: "1) XMR, 2) BTC, 3) XLM" → value=["XMR", "BTC", "XLM"] (preserve order from numbers)
      * Handle commas and "and": "red, white and blue" → ["red", "white", "blue"]
    - rank_ordered: true if multiple values OR numbered list, false if single value
  → confidence=1.0
  → why="My favorite pattern detected: [topic] = [value(s)]"
  → DO NOT route to index or chat - this is ALWAYS facts/write
  
CRITICAL: Look for "favorite" + topic + numbered list ANYWHERE in the message, even if the message starts with other text like "Sorry" or "Argh!".

EXAMPLES FOR RULE 1:
- "My favorite candy is Reese's" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"candy","value":"Reese's","rank_ordered":false}},"confidence":1.0,"why":"My favorite pattern detected: candy = Reese's"}}
- "My favorite colors are red, white and blue" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"colors","value":["red","white","blue"],"rank_ordered":true}},"confidence":1.0,"why":"My favorite pattern detected: colors = [red, white, blue]"}}
- "My favorite cryptos are BTC, XMR and XLM" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"crypto","value":["BTC","XMR","XLM"],"rank_ordered":true}},"confidence":1.0,"why":"My favorite pattern detected: crypto = [BTC, XMR, XLM]"}}
- "Here's the list of my favorite cryptos: 1) XMR, 2) BTC, and 3) XLM" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"crypto","value":["XMR","BTC","XLM"],"rank_ordered":true}},"confidence":1.0,"why":"My favorite pattern detected: crypto = [XMR, BTC, XLM]"}}
- "My favorite cryptos: 1. XMR, 2. BTC, 3. XLM" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"crypto","value":["XMR","BTC","XLM"],"rank_ordered":true}},"confidence":1.0,"why":"My favorite pattern detected: crypto = [XMR, BTC, XLM]"}}
- "Argh! Sorry, that was wrong again. Here's the list of my favorite cryptos: 1) XMR, 2) BTC, and 3) XLM" → {{"content_plane":"facts","operation":"write","reasoning_required":false,"facts_write_candidate":{{"topic":"crypto","value":["XMR","BTC","XLM"],"rank_ordered":true}},"confidence":1.0,"why":"My favorite pattern detected: crypto = [XMR, BTC, XLM]"}}

RULE 2: "List/Show/What is my favorite X" OR ordinal queries like "second favorite", "third favorite"
IF the message:
  a) Contains "list" (anywhere) + "my favorite" + topic, OR
  b) Starts with "List my favorite", "Show my favorite", "What is my favorite", "What are my favorite", OR
  c) Contains "list in order" + "my favorite" + topic, OR
  d) Contains ordinal words (second, third, fourth, fifth, etc.) + "favorite" + topic:
  → content_plane="facts"
  → operation="read"
  → reasoning_required=false
  → facts_read_candidate MUST be populated:
    - topic: extract the topic word
    - query: the original message
  → confidence=1.0
  → why="Facts read query for [topic]" (or "Facts ordinal query: [ordinal] favorite [topic]")
  
CRITICAL: "Please list my favorite X", "List my favorite X", "list in order my favorite X" all route to facts/read.
  
EXAMPLES FOR RULE 2:
- "What are my favorite cryptos?" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"crypto","query":"What are my favorite cryptos?","rank":null}},"confidence":1.0,"why":"Facts read query for crypto"}}
- "List my favorite cryptos" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"crypto","query":"List my favorite cryptos","rank":null}},"confidence":1.0,"why":"Facts read query for crypto"}}
- "Please list my favorite candy" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"candy","query":"Please list my favorite candy","rank":null}},"confidence":1.0,"why":"Facts read query for candy"}}
- "Please list in order my favorite candy" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"candy","query":"Please list in order my favorite candy","rank":null}},"confidence":1.0,"why":"Facts read query for candy"}}
- "What is my second favorite crypto?" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"crypto","query":"What is my second favorite crypto?","rank":2}},"confidence":1.0,"why":"Facts ordinal query: second favorite crypto"}}
- "What is my third favorite color?" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"color","query":"What is my third favorite color?","rank":3}},"confidence":1.0,"why":"Facts ordinal query: third favorite color"}}
- "What's my #2 favorite crypto?" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"crypto","query":"What's my #2 favorite crypto?","rank":2}},"confidence":1.0,"why":"Facts ordinal query: #2 favorite crypto"}}
- "What is my 2nd favorite crypto?" → {{"content_plane":"facts","operation":"read","reasoning_required":false,"facts_read_candidate":{{"topic":"crypto","query":"What is my 2nd favorite crypto?","rank":2}},"confidence":1.0,"why":"Facts ordinal query: 2nd favorite crypto"}}

RULE 3: "What did we discuss" or "Search for X in my history"
IF the message contains "What did we discuss" or "Search for X in my history":
  → content_plane="index"
  → operation="search"
  → reasoning_required=true
  → index_candidate MUST be populated with query

RULE 4: "List files" or "Read file X"
IF the message is about files:
  → content_plane="files"
  → operation="read"
  → reasoning_required=false
  → files_candidate MUST be populated

RULE 5: Everything else
IF none of the above patterns match:
  → content_plane="chat"
  → operation="none"
  → reasoning_required=true

OUTPUT SCHEMA:
{{
  "content_plane": "facts" | "index" | "files" | "chat",
  "operation": "write" | "read" | "search" | "none",
  "reasoning_required": boolean,
  "facts_write_candidate": {{"topic": "string", "value": "string" | ["string"], "rank_ordered": boolean}} | null,
  "facts_read_candidate": {{"topic": "string", "query": "string", "rank": number | null}} | null,
  "index_candidate": {{"query": "string"}} | null,
  "files_candidate": {{"query": "string", "path_hint": "string" | null}} | null,
  "confidence": 0.0-1.0,
  "why": "string"
}}

CRITICAL: 
- Check RULE 1 FIRST - if "My favorite" pattern exists, it MUST be facts/write
- Index is for searching conversational history, NOT for storing preferences
- Output ONLY valid JSON matching the schema above
- No markdown, no code fences, no explanation - just JSON

User message: {user_message}{history_context}

Output JSON:"""
    
    # Build messages for AI Router
    # Put the critical pattern matching rules in the system message for maximum emphasis
    system_message = """You are a deterministic message router. Your ONLY job is to classify messages and output JSON.

CRITICAL PATTERN (CHECK FIRST):
If message contains "My favorite" + topic + "is/are" + value(s):
  → content_plane="facts", operation="write", reasoning_required=false
  → MUST populate facts_write_candidate with topic and value(s)
  → This is ALWAYS facts/write, NEVER index or chat

Output ONLY valid JSON matching the RoutingPlan schema. No markdown, no explanation, no code fences."""
    
    messages = [
        {
            "role": "system",
            "content": system_message
        },
        {
            "role": "user",
            "content": routing_prompt
        }
    ]
    
    payload = {
        "role": "chatdo",
        "intent": "nano_routing",
        "priority": "high",
        "privacyLevel": "normal",
        "costTier": "standard",
        "input": {
            "messages": messages,
            # Request JSON object mode (OpenAI JSON schema mode doesn't support optional fields well)
            # We'll validate with Pydantic after parsing
            "response_format": {
                "type": "json_object"
            }
            # NOTE: GPT-5 Nano doesn't support temperature=0, only default (1)
            # We rely on the prompt for determinism, and validate with Pydantic
        }
    }
    
    try:
        logger.debug(f"[NANO-ROUTER] Routing message: {user_message[:100]}...")
        
        response = requests.post(
            AI_ROUTER_URL,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get("ok"):
            raise NanoRouterError(f"AI Router error: {data.get('error')}")
        
        # Extract content from response
        output_messages = data.get("output", {}).get("messages", [])
        if not output_messages:
            raise NanoRouterError("AI Router returned no messages")
        
        # Get the last assistant message
        assistant_message = None
        for msg in reversed(output_messages):
            if msg.get("role") == "assistant":
                assistant_message = msg
                break
        
        if not assistant_message:
            raise NanoRouterError("AI Router returned no assistant message")
        
        result_text = assistant_message.get("content", "").strip()
        
        if not result_text:
            raise NanoRouterError("Nano router returned empty response")
        
        # Log raw response for debugging
        logger.info(f"[NANO-ROUTER] Raw response (first 500 chars): {result_text[:500]}")
        
        # Parse JSON (extract from markdown if needed - should not happen with JSON schema mode)
        json_text = result_text.strip()
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
        
        # Parse and validate with Pydantic
        try:
            routing_data = json.loads(json_text)
            logger.info(f"[NANO-ROUTER] Parsed JSON: {json.dumps(routing_data, indent=2)}")
            
            # Detect and set rank for ordinal queries if not already set by router
            if routing_data.get("content_plane") == "facts" and routing_data.get("operation") == "read":
                facts_read = routing_data.get("facts_read_candidate")
                if facts_read and facts_read.get("rank") is None:
                    from server.services.ordinal_detection import detect_ordinal_rank
                    detected_rank = detect_ordinal_rank(user_message)
                    if detected_rank:
                        facts_read["rank"] = detected_rank
                        logger.info(f"[NANO-ROUTER] Detected ordinal rank: {detected_rank} (ordinal_parse_source=router_post_parse)")
            
            routing_plan = RoutingPlan(**routing_data)
            
            # Log rank if present
            rank_info = ""
            if routing_plan.facts_read_candidate and routing_plan.facts_read_candidate.rank:
                rank_info = f", rank={routing_plan.facts_read_candidate.rank}"
            
            logger.info(
                f"[NANO-ROUTER] ✅ Validated routing plan: content_plane={routing_plan.content_plane}, "
                f"operation={routing_plan.operation}, reasoning_required={routing_plan.reasoning_required}, "
                f"confidence={routing_plan.confidence}, why={routing_plan.why}{rank_info}"
            )
        except Exception as e:
            # Schema validation failed - retry once with corrective prompt
            if retry_on_schema_error:
                logger.warning(
                    f"[NANO-ROUTER] Schema validation failed, retrying with corrective prompt: {e}"
                )
                corrective_prompt = f"""The previous response did not match the RoutingPlan schema. Error: {e}

Original user message: {user_message}

Please output ONLY valid JSON matching this exact schema:
{json.dumps(ROUTING_PLAN_SCHEMA, indent=2)}

Your previous (invalid) response was:
{result_text[:500]}

Output the corrected JSON now:"""
                
                messages_retry = [
                    {
                        "role": "system",
                        "content": "You are a deterministic message router. Output ONLY valid JSON matching the RoutingPlan schema, no markdown, no explanation."
                    },
                    {
                        "role": "user",
                        "content": routing_prompt
                    },
                    {
                        "role": "assistant",
                        "content": result_text
                    },
                    {
                        "role": "user",
                        "content": corrective_prompt
                    }
                ]
                
                payload_retry = {
                    "role": "chatdo",
                    "intent": "nano_routing",
                    "priority": "high",
                    "privacyLevel": "normal",
                    "costTier": "standard",
                    "input": {
                        "messages": messages_retry,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "routing_plan",
                    "strict": False,  # Set to False to allow optional candidate fields
                    "schema": ROUTING_PLAN_SCHEMA
                }
            },
                        "temperature": 0.0
                    }
                }
                
                response_retry = requests.post(
                    AI_ROUTER_URL,
                    json=payload_retry,
                    timeout=30
                )
                response_retry.raise_for_status()
                
                data_retry = response_retry.json()
                if not data_retry.get("ok"):
                    raise NanoRouterSchemaError(f"Retry failed: {data_retry.get('error')}")
                
                output_messages_retry = data_retry.get("output", {}).get("messages", [])
                if output_messages_retry:
                    result_text_retry = output_messages_retry[-1].get("content", "").strip()
                    if result_text_retry:
                        json_text_retry = result_text_retry.strip()
                        if json_text_retry.startswith("```"):
                            # Extract from markdown
                            lines = json_text_retry.split("\n")
                            json_lines = []
                            in_code_block = False
                            for line in lines:
                                if line.strip().startswith("```"):
                                    in_code_block = not in_code_block
                                    continue
                                if in_code_block:
                                    json_lines.append(line)
                            json_text_retry = "\n".join(json_lines).strip()
                        
                        routing_data_retry = json.loads(json_text_retry)
                        routing_plan = RoutingPlan(**routing_data_retry)
                    else:
                        raise NanoRouterSchemaError("Retry returned empty response")
                else:
                    raise NanoRouterSchemaError("Retry returned no messages")
            else:
                raise NanoRouterSchemaError(f"Schema validation failed: {e}. Response: {result_text[:500]}")
        
        # Log full routing plan for telemetry
        logger.info(
            f"[NANO-ROUTER] ✅ Routing plan: content_plane={routing_plan.content_plane}, "
            f"operation={routing_plan.operation}, reasoning_required={routing_plan.reasoning_required}, "
            f"confidence={routing_plan.confidence}, why={routing_plan.why}"
        )
        if routing_plan.facts_write_candidate:
            logger.info(
                f"[NANO-ROUTER] Facts write candidate: topic={routing_plan.facts_write_candidate.topic}, "
                f"value={routing_plan.facts_write_candidate.value}, rank_ordered={routing_plan.facts_write_candidate.rank_ordered}"
            )
        if routing_plan.facts_read_candidate:
            logger.info(
                f"[NANO-ROUTER] Facts read candidate: topic={routing_plan.facts_read_candidate.topic}"
            )
        
        return routing_plan
        
    except requests.exceptions.Timeout:
        raise NanoRouterError(
            f"Nano router request timed out after 30s. "
            f"AI Router may be slow or unavailable at {AI_ROUTER_URL}"
        )
    except requests.exceptions.ConnectionError as e:
        raise NanoRouterError(
            f"Nano router (AI Router) is unavailable at {AI_ROUTER_URL}. "
            f"Connection error: {e}"
        )
    except requests.exceptions.HTTPError as e:
        raise NanoRouterError(
            f"Nano router HTTP error: {e.response.status_code} - {e.response.text}"
        )
    except (NanoRouterError, NanoRouterSchemaError):
        raise
    except Exception as e:
        raise NanoRouterError(f"Nano router unexpected error: {e}")
