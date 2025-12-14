"""
Ranked list extraction and ordinal query handling for ChatDO.

This module handles:
1. Extracting numbered/ranked lists from user messages (1), 2), 3), first/second/third, etc.)
2. Storing ranked lists in a structured format
3. Detecting ordinal queries (second, third, #2, etc.)
4. Answering ordinal queries from stored ranked lists
"""
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class RankedItem:
    """Represents a single item in a ranked list."""
    rank: int  # 1-based rank (1 = first, 2 = second, etc.)
    value: str  # The actual item value
    topic: str  # The topic/category (e.g., "favorite colors", "favorite crypto")


@dataclass
class RankedList:
    """Represents a complete ranked list for a topic."""
    topic: str  # The topic/category
    items: List[RankedItem]  # Ordered list of ranked items
    source_message: str  # The original message that contained this list
    message_id: Optional[str] = None  # ID of the message that contained this list


def extract_ranked_lists(message: str) -> List[RankedList]:
    """
    Extract ranked lists from a user message.
    
    Supports formats:
    - "1) Blue, 2) Green, 3) Black"
    - "1. Blue, 2. Green, 3. Black"
    - "#1 Blue, #2 Green, #3 Black"
    - "first: Blue, second: Green, third: Black"
    - "My favorite colors are 1) Blue, 2) Green, 3) Black"
    
    Args:
        message: The user message to parse
        
    Returns:
        List of RankedList objects found in the message
    """
    ranked_lists = []
    message_lower = message.lower()
    
    # Pattern 1: Numbered lists with parentheses or periods
    # Matches: "1) Blue, 2) Green" or "1. Blue, 2. Green"
    pattern1 = re.compile(r'(\d+)[.)]\s*([^,0-9]+?)(?=\s*\d+[.)]|,|$)', re.IGNORECASE)
    matches1 = pattern1.findall(message)
    
    if matches1:
        # Try to extract topic from context (look for "favorite X", "my X", etc.)
        topic_match = re.search(r'(?:my|favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', message_lower)
        topic = topic_match.group(1) if topic_match else "items"
        
        items = []
        for rank_str, value in matches1:
            rank = int(rank_str)
            value = value.strip().rstrip(',').strip()
            if value:
                items.append(RankedItem(rank=rank, value=value, topic=topic))
        
        if items:
            ranked_lists.append(RankedList(
                topic=topic,
                items=items,
                source_message=message
            ))
    
    # Pattern 2: Hash-prefixed numbers (#1, #2, #3)
    pattern2 = re.compile(r'#(\d+)\s+([^,#0-9]+?)(?=\s*#\d+|,|$)', re.IGNORECASE)
    matches2 = pattern2.findall(message)
    
    if matches2:
        topic_match = re.search(r'(?:my|favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', message_lower)
        topic = topic_match.group(1) if topic_match else "items"
        
        items = []
        for rank_str, value in matches2:
            rank = int(rank_str)
            value = value.strip().rstrip(',').strip()
            if value:
                items.append(RankedItem(rank=rank, value=value, topic=topic))
        
        if items:
            ranked_lists.append(RankedList(
                topic=topic,
                items=items,
                source_message=message
            ))
    
    # Pattern 3: Ordinal words (first, second, third, etc.)
    ordinal_map = {
        'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
        'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10
    }
    pattern3 = re.compile(r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s*[:)]\s*([^,]+?)(?=\s*(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)[:)]|,|$)', re.IGNORECASE)
    matches3 = pattern3.findall(message)
    
    if matches3:
        topic_match = re.search(r'(?:my|favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', message_lower)
        topic = topic_match.group(1) if topic_match else "items"
        
        items = []
        for ordinal_str, value in matches3:
            rank = ordinal_map.get(ordinal_str.lower(), None)
            if rank:
                value = value.strip().rstrip(',').strip()
                if value:
                    items.append(RankedItem(rank=rank, value=value, topic=topic))
        
        if items:
            ranked_lists.append(RankedList(
                topic=topic,
                items=items,
                source_message=message
            ))
    
    return ranked_lists


def detect_ordinal_query(query: str) -> Optional[Tuple[int, Optional[str]]]:
    """
    Detect if a query is asking for a specific ranked item.
    
    Args:
        query: The user's query
        
    Returns:
        Tuple of (rank, topic) if an ordinal query is detected, None otherwise
        rank: 1-based rank (1 = first, 2 = second, etc.)
        topic: Optional topic/category if detected (e.g., "colors", "crypto")
    """
    query_lower = query.lower()
    
    # Pattern 0: "What is my favorite X?" or "What's my favorite X?" -> defaults to rank 1 (first)
    # This handles queries like "What is my favorite tv show?" -> should return #1
    # But NOT "What are my favorite X?" which should return the full list (handled separately)
    favorite_query_match = re.search(r"what(?:'s| is)\s+(?:my|your)?\s+favorite\s+([a-z]+(?:\s+[a-z]+)?)", query_lower)
    if favorite_query_match and "are" not in query_lower and "second" not in query_lower and "third" not in query_lower and "#" not in query_lower:
        topic = favorite_query_match.group(1).strip()
        # Remove "favorite" if it appears in the topic
        topic = re.sub(r'\bfavorite\s+', '', topic).strip()
        return (1, topic)  # Default to first/rank 1
    
    # Pattern 1: "second", "third", etc.
    ordinal_map = {
        'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
        'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10
    }
    
    for ordinal, rank in ordinal_map.items():
        if ordinal in query_lower:
            # Try to extract topic - look for patterns like "favorite X" or "my X"
            # Match after ordinal words: "second favorite color" -> "color"
            # Or match "my favorite X" pattern
            topic_match = re.search(r'(?:my\s+)?(?:favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', query_lower)
            if topic_match:
                topic = topic_match.group(1)
                # Remove ordinal words from topic if present
                topic = re.sub(r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+', '', topic).strip()
                # If topic still contains "favorite", try to get the word after it
                if 'favorite' in topic:
                    favorite_match = re.search(r'favorite\s+([a-z]+(?:\s+[a-z]+)?)', topic)
                    if favorite_match:
                        topic = favorite_match.group(1).strip()
            else:
                # Try to find a noun after the ordinal
                topic_match = re.search(rf'{ordinal}\s+(?:favorite\s+)?([a-z]+(?:\s+[a-z]+)?)', query_lower)
                topic = topic_match.group(1) if topic_match else None
            return (rank, topic)
    
    # Pattern 2: "#1", "#2", etc.
    hash_match = re.search(r'#(\d+)', query)
    if hash_match:
        rank = int(hash_match.group(1))
        topic_match = re.search(r'(?:my|favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', query_lower)
        topic = topic_match.group(1) if topic_match else None
        return (rank, topic)
    
    # Pattern 3: "number 1", "number 2", etc.
    num_match = re.search(r'number\s+(\d+)\s+(?:favorite\s+)?([a-z]+(?:\s+[a-z]+)?)', query_lower)
    if num_match:
        rank = int(num_match.group(1))
        topic = num_match.group(2) if num_match.group(2) else None
        if not topic:
            # Fallback: try to find topic elsewhere
            topic_match = re.search(r'(?:my|favorite|top)\s+([a-z]+(?:\s+[a-z]+)?)', query_lower)
            topic = topic_match.group(1) if topic_match else None
        return (rank, topic)
    
    return None


def answer_ordinal_query(rank: int, topic: Optional[str], ranked_lists: List[RankedList]) -> Optional[str]:
    """
    Answer an ordinal query using stored ranked lists.
    
    Args:
        rank: The requested rank (1-based)
        topic: Optional topic to filter by
        ranked_lists: List of stored ranked lists
        
    Returns:
        The value at the requested rank, or None if not found
    """
    # Filter by topic if provided - use STRICT matching to avoid wrong lists
    if topic:
        matching_lists = []
        topic_lower = topic.lower().strip()
        
        for rl in ranked_lists:
            stored_topic_lower = rl.topic.lower().strip()
            
            # Extract core words from both topics (remove "favorite", "my", etc.)
            topic_words = set([w for w in topic_lower.split() if w not in ['favorite', 'my', 'top', 'the', 'a', 'an'] and len(w) > 2])
            stored_words = set([w for w in stored_topic_lower.split() if w not in ['favorite', 'my', 'top', 'the', 'a', 'an'] and len(w) > 2])
            
            # Must have at least one meaningful word in common
            common_words = topic_words.intersection(stored_words)
            
            # Also check if one topic is a substring of the other (for "tv show" vs "tv shows")
            is_substring_match = (topic_lower in stored_topic_lower or stored_topic_lower in topic_lower)
            
            # Require either common words OR substring match, but be strict
            if common_words or (is_substring_match and len(topic_lower) > 3):
                matching_lists.append(rl)
    else:
        matching_lists = ranked_lists
    
    # Find the item at the requested rank
    for ranked_list in matching_lists:
        for item in ranked_list.items:
            if item.rank == rank:
                return item.value
    
    return None


def get_full_ranked_list(topic: Optional[str], ranked_lists: List[RankedList]) -> Optional[List[RankedItem]]:
    """
    Get the full ranked list for a topic.
    
    Args:
        topic: Optional topic to filter by
        ranked_lists: List of stored ranked lists
        
    Returns:
        List of RankedItem objects in rank order, or None if not found
    """
    if topic:
        # Use STRICT topic matching to avoid returning wrong lists
        matching_lists = []
        topic_lower = topic.lower().strip()
        
        for rl in ranked_lists:
            stored_topic_lower = rl.topic.lower().strip()
            
            # Extract core words from both topics (remove "favorite", "my", etc.)
            topic_words = set([w for w in topic_lower.split() if w not in ['favorite', 'my', 'top', 'the', 'a', 'an'] and len(w) > 2])
            stored_words = set([w for w in stored_topic_lower.split() if w not in ['favorite', 'my', 'top', 'the', 'a', 'an'] and len(w) > 2])
            
            # Must have at least one meaningful word in common
            common_words = topic_words.intersection(stored_words)
            
            # Also check if one topic is a substring of the other (for "tv show" vs "tv shows")
            is_substring_match = (topic_lower in stored_topic_lower or stored_topic_lower in topic_lower)
            
            # Require either common words OR substring match, but be strict
            if common_words or (is_substring_match and len(topic_lower) > 3):
                matching_lists.append(rl)
        
        # If no matches found, return None (don't guess!)
        if not matching_lists:
            return None
    else:
        matching_lists = ranked_lists
    
    if not matching_lists:
        return None
    
    # Return the most recent list (first one found, could be improved to track recency)
    ranked_list = matching_lists[0]
    return sorted(ranked_list.items, key=lambda x: x.rank)
