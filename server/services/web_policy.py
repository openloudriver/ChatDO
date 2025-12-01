"""
Deterministic web search policy helper.

Centralizes the decision logic for when to trigger Web + GPT-5 based on
the globe toggle state and user message content.

Uses a data-driven keyword matrix loaded from JSON config.
"""
import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "web_keywords.json",
)

# --- Default config used if JSON is missing or invalid ---
DEFAULT_CONFIG: Dict[str, Any] = {
    "categories": {
        "finance_price": {
            "priority": 1,
            "recency_required": True,
            "keywords": [
                "current price",
                "price of",
                "price right now",
                "trading at",
                "quote for",
                "market price",
                "spot price",
            ],
            "assets": [
                "xmr",
                "monero",
                "btc",
                "bitcoin",
                "eth",
                "ethereum",
                "msty",
                "mstr",
                "schd",
                " o ",
                "mdst",
                "jepi",
                "spyi",
                "spy",
                "qqq",
                "voo",
                "vti",
                "stock",
                "etf",
                "crypto",
                "token",
                "coin",
            ],
        },
        "finance_news": {
            "priority": 1,
            "recency_required": True,
            "keywords": [
                "latest",
                "breaking",
                "recent",
                "this week",
                "this month",
                "today",
                "right now",
                "currently",
            ],
            "context": [
                "market",
                "dividend",
                "yield",
                "earnings",
                "cpi",
                "inflation",
                "jobs report",
                "unemployment",
                "fed",
                "fomc",
                "rate hike",
                "interest rates",
            ],
        },
        "crypto_chain": {
            "priority": 2,
            "recency_required": True,
            "keywords": [
                "hashrate",
                "difficulty",
                "block reward",
                "block height",
                "mempool",
                "fees",
                "gas fees",
            ],
        },
        "security_incidents": {
            "priority": 2,
            "recency_required": True,
            "keywords": [
                "breach",
                "exploit",
                "cve",
                "attack",
                "hack",
                "ransomware",
                "outage",
                "downtime",
                "data leak",
            ],
        },
        "global_news": {
            "priority": 2,
            "recency_required": True,
            "keywords": [
                "breaking news",
                "latest news",
                "news today",
                "headline",
                "recent news",
            ],
        },
    },
    "recency_words": [
        "today",
        "right now",
        "currently",
        "current",
        "this week",
        "this month",
        "recently",
        "latest",
        "up to date",
        "live",
        "real time",
    ],
}


@lru_cache(maxsize=1)
def _load_config() -> Dict[str, Any]:
    """Load config from JSON file, fallback to default if missing or invalid."""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Basic sanity check
                if isinstance(data, dict) and "categories" in data:
                    return data
    except Exception:
        # Fall back silently; we can add logging later if needed
        pass
    return DEFAULT_CONFIG


def _contains_any(text: str, phrases: List[str]) -> bool:
    """Check if text contains any of the given phrases."""
    return any(p in text for p in phrases)


def _extract_urls(text: str) -> List[str]:
    """Very simple URL detector; enough to decide 'use web'."""
    pieces = text.split()
    urls: List[str] = []
    for token in pieces:
        t = token.lower()
        if t.startswith("http://") or t.startswith("https://"):
            urls.append(token)
        elif "." in t and ("www." in t or t.endswith(".com") or t.endswith(".org") or t.endswith(".net")):
            urls.append(token)
    return urls


def should_use_web(
    message_text: Optional[str] = None,
    web_mode: Optional[str] = None,
    *,
    web_toggle: Optional[str] = None,
) -> bool:
    """
    Centralized web policy:
      - web_mode/web_toggle "on"  => always True
      - web_mode/web_toggle "auto" => use deterministic keyword matrix
      - anything else => False

    Supports both positional and keyword arguments for backward compatibility.
    """
    if not message_text:
        return False

    text = message_text.lower()
    
    # Support both web_mode (positional) and web_toggle (keyword) for compatibility
    mode = (web_mode or web_toggle or "auto").lower()

    # 1) Explicit override: ON => always use web
    if mode == "on":
        return True

    # 2) Only handle AUTO; anything else => no web
    if mode != "auto":
        return False

    config = _load_config()
    categories: Dict[str, Any] = config.get("categories", {})
    recency_words: List[str] = config.get("recency_words", [])

    # 3) If user pasted or typed a URL, always use web
    if _extract_urls(text):
        return True

    # 4) Evaluate each category and collect matches
    matches: List[Dict[str, Any]] = []
    for name, cat in categories.items():
        priority = int(cat.get("priority", 99))
        recency_required = bool(cat.get("recency_required", False))
        keywords = [k.lower() for k in cat.get("keywords", [])]
        assets = [a.lower() for a in cat.get("assets", [])]
        context = [c.lower() for c in cat.get("context", [])]

        if not keywords and not assets and not context:
            continue

        # Core trigger: any primary keyword present
        has_keyword = _contains_any(text, keywords)

        # Optional asset/context triggers
        has_asset = _contains_any(text, assets)
        has_context = _contains_any(text, context)

        # Recency requirement
        has_recency = _contains_any(text, [w.lower() for w in recency_words])

        # Decision rules per category:
        # - If recency_required: need (keyword OR asset OR context) AND recency
        # - Else: keyword OR asset OR context is enough
        if recency_required:
            if (has_keyword or has_asset or has_context) and has_recency:
                matches.append({"name": name, "priority": priority})
        else:
            if has_keyword or has_asset or has_context:
                matches.append({"name": name, "priority": priority})

    if not matches:
        return False

    # 5) If any category matched, choose the highest-priority one
    matches.sort(key=lambda m: m["priority"])
    # For now, any match => we use web. Later we could introspect category for different behaviors.
    return True

