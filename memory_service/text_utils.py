"""
Text utilities for tokenization and lexical search.

Provides tokenization for BM25-style lexical matching.
"""
import re
from typing import List, Dict
from collections import Counter

# Simple stopwords set for tokenization
STOPWORDS = {
    "the", "a", "an", "is", "are", "and", "of", "to", "in", "for", "on", "at",
    "this", "that", "it", "as", "with", "by", "from", "was", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "what", "when", "where", "which",
    "who", "whom", "whose", "why", "how"
}


def tokenize(text: str) -> List[str]:
    """
    Tokenize text into lowercase words, filtering out stopwords.
    
    Args:
        text: Input text string
        
    Returns:
        List of token strings (lowercase, no stopwords)
    """
    text = text.lower()
    # Simple word tokenizer - extract alphanumeric sequences
    tokens = re.findall(r"[a-z0-9]+", text)
    # Filter out stopwords and very short tokens
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def compute_bm25_score(query_tokens: List[str], doc_tokens: List[str], 
                       doc_freqs: Dict[str, int], avg_doc_length: float,
                       k1: float = 1.5, b: float = 0.75) -> float:
    """
    Compute BM25 score for a document given a query.
    
    Args:
        query_tokens: Tokenized query
        doc_tokens: Tokenized document
        doc_freqs: Dictionary mapping token to document frequency (how many docs contain it)
        avg_doc_length: Average document length in tokens
        k1: BM25 parameter (default 1.5)
        b: BM25 parameter (default 0.75)
        
    Returns:
        BM25 score
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    
    doc_length = len(doc_tokens)
    doc_token_counts = Counter(doc_tokens)
    total_docs = max(doc_freqs.values()) if doc_freqs else 1
    
    score = 0.0
    for term in query_tokens:
        if term not in doc_tokens:
            continue
        
        # Term frequency in this document
        tf = doc_token_counts[term]
        
        # Document frequency (how many documents contain this term)
        df = doc_freqs.get(term, 1)
        
        # Inverse document frequency
        idf = max(0.0, (total_docs - df + 0.5) / (df + 0.5))
        idf = max(0.0, idf)  # Ensure non-negative
        
        # BM25 term score
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_length / avg_doc_length))
        term_score = idf * (numerator / denominator) if denominator > 0 else 0.0
        
        score += term_score
    
    return score

