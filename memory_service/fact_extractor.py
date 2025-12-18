"""
Fact extraction pipeline for chat messages.

Uses deterministic, rule-based extraction with spaCy, dateparser, quantulum3,
and regex patterns. Only creates facts when rules are confident.
"""
import re
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import dateparser
import quantulum3

logger = logging.getLogger(__name__)

# Try to import spaCy, but make it optional
try:
    import spacy
    from spacy.matcher import Matcher
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logger.warning("spaCy not available. Fact extraction will be limited.")


# Pattern for explicit fact statements
EXPLICIT_FACT_PATTERNS = [
    r"(?:my|i|I)\s+(?:favorite|preferred|prefer)\s+(\w+)\s+is\s+(.+?)(?:\.|$)",
    r"(?:remember|note|save)\s+that\s+(.+?)(?:\.|$)",
    r"(?:my|I|i)\s+(\w+)\s+is\s+(.+?)(?:\.|$)",
    r"(?:I|i)\s+(?:like|love|hate|dislike)\s+(.+?)(?:\.|$)",
    r"(?:I|i)\s+(?:am|'m)\s+(.+?)(?:\.|$)",
    r"(?:I|i)\s+(?:have|got|own)\s+(?:a|an|the)?\s*(.+?)(?:\.|$)",
]

# Email pattern
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# URL pattern
URL_PATTERN = r'https?://[^\s<>"{}|\\^`\[\]]+'

# Currency pattern
CURRENCY_PATTERN = r'\$[\d,]+(?:\.\d{2})?'

# Phone number pattern (US format)
PHONE_PATTERN = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'


class FactExtractor:
    """Extracts structured facts from chat messages."""
    
    def __init__(self):
        self.nlp = None
        self.matcher = None
        if SPACY_AVAILABLE:
            try:
                # Try to load English model
                self.nlp = spacy.load("en_core_web_sm")
                self.matcher = Matcher(self.nlp.vocab)
                self._setup_patterns()
            except OSError:
                logger.warning("spaCy English model not found. Run: python -m spacy download en_core_web_sm")
                SPACY_AVAILABLE = False
    
    def _setup_patterns(self):
        """Setup spaCy matcher patterns."""
        if not self.matcher:
            return
        
        # Pattern: "my favorite X is Y"
        self.matcher.add("FAVORITE", [
            [{"LOWER": {"IN": ["my", "i"]}}, {"LOWER": "favorite"}, {"POS": "NOUN"}, {"LOWER": "is"}, {"POS": {"IN": ["NOUN", "ADJ", "PROPN"]}}]
        ])
        
        # Pattern: "I am X"
        self.matcher.add("AM", [
            [{"LOWER": "i"}, {"LOWER": {"IN": ["am", "'m"]}}, {"POS": {"IN": ["NOUN", "ADJ", "PROPN"]}}]
        ])
    
    def extract_facts(self, content: str, role: str = "user") -> List[Dict[str, any]]:
        """
        Extract facts from message content.
        
        Args:
            content: Message content
            role: Message role ("user" or "assistant")
            
        Returns:
            List of fact dicts with keys: fact_key, value_text, value_type, confidence
        """
        facts = []
        
        # Only extract from user messages (assistants might repeat facts)
        if role != "user":
            return facts
        
        content_lower = content.lower().strip()
        
        # 1. Check for explicit fact statements (high confidence)
        for pattern in EXPLICIT_FACT_PATTERNS:
            matches = re.finditer(pattern, content_lower, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    key_part = match.group(1).strip()
                    value = match.group(2).strip()
                else:
                    value = match.group(1).strip()
                    # Try to infer key from context
                    key_part = self._infer_key_from_context(content_lower, match.start())
                
                if value and len(value) < 200:  # Reasonable length limit
                    fact_key = self._normalize_fact_key(key_part)
                    value_type, normalized_value = self._normalize_value(value)
                    if fact_key and normalized_value:
                        facts.append({
                            "fact_key": fact_key,
                            "value_text": normalized_value,
                            "value_type": value_type,
                            "confidence": 0.9  # High confidence for explicit statements
                        })
        
        # 2. Extract dates
        dates = self._extract_dates(content)
        for date_str, date_obj in dates:
            fact_key = "user.mentioned_date"
            facts.append({
                "fact_key": fact_key,
                "value_text": date_str,
                "value_type": "date",
                "confidence": 0.7
            })
        
        # 3. Extract quantities/numbers
        quantities = self._extract_quantities(content)
        for qty_text, qty_value in quantities:
            fact_key = "user.mentioned_quantity"
            facts.append({
                "fact_key": fact_key,
                "value_text": qty_text,
                "value_type": "number",
                "confidence": 0.6
            })
        
        # 4. Extract emails
        emails = re.findall(EMAIL_PATTERN, content)
        for email in emails[:1]:  # Limit to first email
            fact_key = "user.email"
            facts.append({
                "fact_key": fact_key,
                "value_text": email,
                "value_type": "string",
                "confidence": 0.95  # Very high confidence for emails
            })
        
        # 5. Extract URLs
        urls = re.findall(URL_PATTERN, content)
        for url in urls[:1]:  # Limit to first URL
            fact_key = "user.mentioned_url"
            facts.append({
                "fact_key": fact_key,
                "value_text": url,
                "value_type": "string",
                "confidence": 0.9
            })
        
        # 6. Use spaCy for entity extraction (if available)
        if self.nlp:
            doc = self.nlp(content)
            # Extract named entities
            for ent in doc.ents:
                if ent.label_ in ["PERSON", "ORG", "GPE"]:  # Person, Organization, Geopolitical
                    fact_key = f"user.mentioned_{ent.label_.lower()}"
                    facts.append({
                        "fact_key": fact_key,
                        "value_text": ent.text,
                        "value_type": "string",
                        "confidence": 0.7
                    })
        
        # Deduplicate facts by fact_key (keep highest confidence)
        seen_keys = {}
        for fact in facts:
            key = fact["fact_key"]
            if key not in seen_keys or fact["confidence"] > seen_keys[key]["confidence"]:
                seen_keys[key] = fact
        
        return list(seen_keys.values())
    
    def _infer_key_from_context(self, content: str, match_start: int) -> str:
        """Infer fact key from surrounding context."""
        # Look for question words before the match
        context_before = content[max(0, match_start-50):match_start]
        if "favorite" in context_before:
            # Try to extract what they're talking about
            words = context_before.split()
            if len(words) >= 2:
                return words[-1]
        return "user.preference"
    
    def _normalize_fact_key(self, key_part: str) -> str:
        """Normalize fact key to standard format."""
        if not key_part:
            return None
        
        # Remove common words
        key_part = re.sub(r'\b(?:my|i|the|a|an)\b', '', key_part, flags=re.IGNORECASE).strip()
        
        # Normalize to lowercase, replace spaces with underscores
        normalized = re.sub(r'[^\w\s]', '', key_part.lower())
        normalized = re.sub(r'\s+', '_', normalized)
        
        # Prefix with user.
        if normalized:
            return f"user.{normalized}"
        return None
    
    def _normalize_value(self, value: str) -> Tuple[str, str]:
        """
        Normalize value and determine type.
        
        Returns:
            Tuple of (value_type, normalized_value)
        """
        value = value.strip()
        if not value:
            return None, None
        
        # Check for boolean
        if value.lower() in ["true", "false", "yes", "no"]:
            bool_val = "true" if value.lower() in ["true", "yes"] else "false"
            return "bool", bool_val
        
        # Check for number
        try:
            # Try to parse as number
            num_val = float(value.replace(',', ''))
            return "number", str(num_val)
        except ValueError:
            pass
        
        # Check for date
        parsed_date = dateparser.parse(value)
        if parsed_date:
            return "date", parsed_date.isoformat()
        
        # Default to string
        return "string", value
    
    def _extract_dates(self, content: str) -> List[Tuple[str, datetime]]:
        """Extract dates from content."""
        dates = []
        # Use dateparser to find dates
        # This is a simple approach - could be improved
        parsed = dateparser.parse(content)
        if parsed:
            dates.append((content, parsed))
        return dates
    
    def _extract_quantities(self, content: str) -> List[Tuple[str, float]]:
        """Extract quantities from content."""
        quantities = []
        try:
            quants = quantulum3.parse(content)
            for qty in quants:
                quantities.append((qty.surface, qty.value))
        except Exception:
            pass
        return quantities


# Global instance
_fact_extractor = None

def get_fact_extractor() -> FactExtractor:
    """Get or create the global fact extractor instance."""
    global _fact_extractor
    if _fact_extractor is None:
        _fact_extractor = FactExtractor()
    return _fact_extractor

