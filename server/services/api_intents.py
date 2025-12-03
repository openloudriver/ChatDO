"""API intent detection for routing queries to ApiRouter.

Simple rule-based classifier to detect when a user is asking for:
- Current weather for a location
- Current crypto price
- Current stock/ETF price
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel
import re


class ApiIntentResult(BaseModel):
    """Result of API intent detection."""
    intent: Literal["api_weather_current", "api_crypto_price", "api_stock_price"]
    # For weather
    location: Optional[str] = None
    # For assets
    symbol: Optional[str] = None
    asset_type: Optional[Literal["crypto", "equity"]] = None


# Known crypto tickers (common ones)
CRYPTO_TICKERS = {
    "xmr", "monero",
    "btc", "bitcoin",
    "eth", "ethereum",
    "ltc", "litecoin",
    "doge", "dogecoin",
    "ada", "cardano",
    "sol", "solana",
    "dot", "polkadot",
    "avax", "avalanche",
    "matic", "polygon",
}

# Known equity tickers (common ETFs/stocks)
EQUITY_TICKERS = {
    "msty", "schd", "spyi", "jepi", "o", "spy", "qqq", "vti", "voo",
    "dgro", "dvy", "vym", "schy", "fdiv", "divo", "spyd", "spyd",
    "sphd", "hdv", "pey", "sdy", "vig", "nobl", "sdiv", "rdvy",
}


def detect_api_intent(text: str) -> Optional[ApiIntentResult]:
    """
    Detect if the user is asking for API data (weather, crypto, stock).
    
    Returns ApiIntentResult if detected, None otherwise.
    """
    # Normalize
    q = text.strip().lower()
    
    # Weather patterns
    # Examples: "what's the weather in rome, ny?", "weather in enterprise, or"
    weather_patterns = [
        r"weather\s+in\s+(.+?)(?:\?|$|\.|,)",  # "weather in <location>"
        r"what'?s?\s+the\s+weather\s+(?:in|at|for)\s+(.+?)(?:\?|$|\.|,)",  # "what's the weather in <location>"
        r"current\s+weather\s+(?:in|at|for)\s+(.+?)(?:\?|$|\.|,)",  # "current weather in <location>"
        r"temperature\s+(?:in|at|for)\s+(.+?)(?:\?|$|\.|,)",  # "temperature in <location>"
    ]
    
    for pattern in weather_patterns:
        match = re.search(pattern, q)
        if match:
            location = match.group(1).strip()
            # Clean up common trailing words
            location = re.sub(r'\s+(right\s+now|today|now)$', '', location, flags=re.IGNORECASE)
            if location and len(location) > 2:
                return ApiIntentResult(
                    intent="api_weather_current",
                    location=location
                )
    
    # Fallback: if it starts with "weather in " assume the rest is the location
    if q.startswith("weather in "):
        location = q[11:].strip()
        # Remove trailing question marks, periods, etc.
        location = re.sub(r'[?.,!]+$', '', location)
        if location and len(location) > 2:
            return ApiIntentResult(
                intent="api_weather_current",
                location=location
            )
    
    # Crypto price patterns
    # Examples: "what's the price of xmr?", "current price of btc", "xmr price"
    crypto_patterns = [
        r"(?:what'?s?\s+)?(?:the\s+)?(?:current\s+)?price\s+(?:of\s+)?([a-z]+)(?:\?|$|\.|,)",  # "price of xmr"
        r"([a-z]+)\s+price",  # "xmr price"
        r"([a-z]+)\s+current\s+price",  # "xmr current price"
    ]
    
    for pattern in crypto_patterns:
        match = re.search(pattern, q)
        if match:
            symbol = match.group(1).strip().lower()
            if symbol in CRYPTO_TICKERS:
                # Normalize to standard ticker format
                if symbol == "monero":
                    symbol = "xmr"
                elif symbol == "bitcoin":
                    symbol = "btc"
                elif symbol == "ethereum":
                    symbol = "eth"
                elif symbol == "litecoin":
                    symbol = "ltc"
                elif symbol == "dogecoin":
                    symbol = "doge"
                elif symbol == "cardano":
                    symbol = "ada"
                elif symbol == "solana":
                    symbol = "sol"
                elif symbol == "polkadot":
                    symbol = "dot"
                elif symbol == "avalanche":
                    symbol = "avax"
                elif symbol == "polygon":
                    symbol = "matic"
                
                return ApiIntentResult(
                    intent="api_crypto_price",
                    symbol=symbol.upper(),
                    asset_type="crypto"
                )
    
    # Stock/ETF price patterns
    # Examples: "what's the price of msty?", "current price of schd", "spy quote"
    equity_patterns = [
        r"(?:what'?s?\s+)?(?:the\s+)?(?:current\s+)?(?:price|quote)\s+(?:of\s+)?([A-Z]{2,5})(?:\?|$|\.|,)",  # "price of MSTY"
        r"([A-Z]{2,5})\s+(?:price|quote)",  # "MSTY price"
        r"([A-Z]{2,5})\s+current\s+price",  # "MSTY current price"
    ]
    
    for pattern in equity_patterns:
        match = re.search(pattern, q)
        if match:
            symbol = match.group(1).strip().upper()
            # Check if it's a known equity ticker (2-5 uppercase letters)
            if len(symbol) >= 2 and len(symbol) <= 5 and symbol.lower() in EQUITY_TICKERS:
                return ApiIntentResult(
                    intent="api_stock_price",
                    symbol=symbol,
                    asset_type="equity"
                )
    
    # Also check for lowercase equity symbols in the text
    words = q.split()
    for word in words:
        # Remove punctuation
        clean_word = re.sub(r'[?.,!]+', '', word).upper()
        if len(clean_word) >= 2 and len(clean_word) <= 5 and clean_word.lower() in EQUITY_TICKERS:
            # Check if context suggests it's a price query
            if any(keyword in q for keyword in ["price", "quote", "current", "what", "how much"]):
                return ApiIntentResult(
                    intent="api_stock_price",
                    symbol=clean_word,
                    asset_type="equity"
                )
    
    # If nothing matches, return None
    return None

