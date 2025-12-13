import React from 'react';
import type { Source } from '../types/sources';
import { InlineCitation } from './InlineCitation';

interface InlineSourceCitationsProps {
  text: string;
  sources?: Source[];
  /** Pre-computed used sources array (shared across all fragments) */
  sharedUsedSources?: Source[];
  /** Pre-computed mapping from citation key (e.g., "1", "R1", "M2") to index in sharedUsedSources */
  sharedUsedNumberToIndex?: Map<string, number> | Map<number, number>; // Support both for backward compatibility
}

/**
 * Replace citation patterns in plain text with <InlineCitation /> chips.
 * Supports:
 * - [1], [2], [1, 3] (Web sources - no prefix)
 * - [R1], [R2], [R1, R3] (RAG sources)
 * - [M1], [M2], [M1, M3] (Memory sources)
 * - [W1], [W2] (explicit Web prefix, optional)
 *
 * Only sources that are actually cited in the text are included in the popover navigation.
 * If sharedUsedSources is provided, use that instead of computing from this fragment.
 */
export const InlineSourceCitations: React.FC<InlineSourceCitationsProps> = ({ 
  text, 
  sources, 
  sharedUsedSources, 
  sharedUsedNumberToIndex 
}) => {
  // If we have shared sources, use those; otherwise require sources prop
  const hasSources = (sharedUsedSources && sharedUsedSources.length > 0) || (sources && sources.length > 0);
  if (!hasSources) {
    return <>{text}</>;
  }
  
  // Use shared sources if available, otherwise fall back to sources prop
  const sourcesToUse = sharedUsedSources && sharedUsedSources.length > 0 ? sharedUsedSources : (sources || []);

  // Define citationPattern to match [1], [R1], [M1], [W1] patterns
  // Supports: [1], [2, 3] (Web), [R1], [R2, R3] (RAG), [M1], [M2, M3] (Memory), [W1] (explicit Web)
  const citationPattern = /\[([RMW]?\d+(?:\s*,\s*[RMW]?\d+)*)\]/g;

  // Helper to extract prefix and number from citation string
  const parseCitation = (citationStr: string): { prefix: 'R' | 'M' | 'W' | null; number: number } => {
    const trimmed = citationStr.trim();
    if (trimmed.startsWith('R')) {
      return { prefix: 'R', number: parseInt(trimmed.substring(1), 10) };
    } else if (trimmed.startsWith('M')) {
      return { prefix: 'M', number: parseInt(trimmed.substring(1), 10) };
    } else if (trimmed.startsWith('W')) {
      return { prefix: 'W', number: parseInt(trimmed.substring(1), 10) };
    } else {
      // No prefix = Web (default)
      return { prefix: null, number: parseInt(trimmed, 10) };
    }
  };

  // Helper to get citation prefix for a source
  const getSourcePrefix = (source: Source): 'R' | 'M' | 'W' | null => {
    if (source.citationPrefix !== undefined) {
      return source.citationPrefix;
    }
    // Fallback to sourceType
    if (source.sourceType === 'rag') return 'R';
    if (source.sourceType === 'memory') return 'M';
    if (source.sourceType === 'web') return null; // Web uses no prefix
    return null; // Default to Web (no prefix)
  };

  // Build citationToSource map - will be populated based on whether we use shared sources or not
  const citationToSource = new Map<string, { source: Source; index: number; total: number }>();

  // Use shared usedSources if provided (for consistent totals across fragments)
  let usedSources: Source[];
  let usedNumberToIndex: Map<string, number>; // Map citation key to index in usedSources

  if (sharedUsedSources && sharedUsedNumberToIndex) {
    // Use the pre-computed shared arrays
    usedSources = sharedUsedSources;
    // Convert sharedUsedNumberToIndex to string-based format
    usedNumberToIndex = new Map<string, number>();
    sharedUsedNumberToIndex.forEach((idx, key) => {
      // Handle both number (old format) and string (new format) keys
      if (typeof key === 'number') {
        // Old format: number-based, need to determine prefix from source
        const source = usedSources[idx];
        if (source) {
          const prefix = getSourcePrefix(source);
          const citationKey = prefix ? `${prefix}${key}` : String(key);
          usedNumberToIndex.set(citationKey, idx);
        }
      } else {
        // New format: string-based (e.g., "R1", "M2", "1")
        usedNumberToIndex.set(key, idx);
      }
    });
    
    // Rebuild citationToSource from sharedUsedSources for proper matching
    // Group shared sources by type to get totals for each group
    const sharedWeb: Source[] = [];
    const sharedRag: Source[] = [];
    const sharedMemory: Source[] = [];
    
    sharedUsedSources.forEach(source => {
      const prefix = getSourcePrefix(source);
      if (prefix === 'R') {
        sharedRag.push(source);
      } else if (prefix === 'M') {
        sharedMemory.push(source);
      } else {
        sharedWeb.push(source);
      }
    });
    
    // Rebuild citationToSource map using the citation keys from usedNumberToIndex
    // This ensures we match the exact citation keys that were found in the text
    usedNumberToIndex.forEach((usedIdx, citationKey) => {
      const source = usedSources[usedIdx];
      if (source) {
        // Determine which group this source belongs to for total count
        const prefix = getSourcePrefix(source);
        let total = 0;
        let groupIdx = 0;
        
        if (prefix === 'R') {
          total = sharedRag.length;
          groupIdx = sharedRag.findIndex(s => s.id === source.id);
        } else if (prefix === 'M') {
          total = sharedMemory.length;
          groupIdx = sharedMemory.findIndex(s => s.id === source.id);
        } else {
          total = sharedWeb.length;
          groupIdx = sharedWeb.findIndex(s => s.id === source.id);
        }
        
        if (groupIdx >= 0) {
          citationToSource.set(citationKey, {
            source,
            index: groupIdx,
            total
          });
        }
      }
    });
  } else {
    // Build citationToSource from sourcesToUse
    // Group sources by type and assign citation numbers
    const groupedSources: {
      web: Source[];
      rag: Source[];
      memory: Source[];
    } = {
      web: [],
      rag: [],
      memory: []
    };

    sourcesToUse.forEach(source => {
      const prefix = getSourcePrefix(source);
      if (prefix === 'R') {
        groupedSources.rag.push(source);
      } else if (prefix === 'M') {
        groupedSources.memory.push(source);
      } else {
        groupedSources.web.push(source);
      }
    });

    // Sort each group by rank
    groupedSources.web.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
    groupedSources.rag.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
    groupedSources.memory.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));

    // Map Web sources: [1], [2], [3]
    groupedSources.web.forEach((source, idx) => {
      const citationKey = String(idx + 1);
      citationToSource.set(citationKey, {
        source,
        index: idx,
        total: groupedSources.web.length
      });
    });

    // Map RAG sources: [R1], [R2], [R3]
    groupedSources.rag.forEach((source, idx) => {
      const citationKey = `R${idx + 1}`;
      citationToSource.set(citationKey, {
        source,
        index: idx,
        total: groupedSources.rag.length
      });
    });

    // Map Memory sources: [M1], [M2], [M3]
    groupedSources.memory.forEach((source, idx) => {
      const citationKey = `M${idx + 1}`;
      citationToSource.set(citationKey, {
        source,
        index: idx,
        total: groupedSources.memory.length
      });
    });
    // Build usedSources from citations found in text
    const foundCitations = new Set<string>();
    
    let scanMatch: RegExpExecArray | null;
    citationPattern.lastIndex = 0;
    while ((scanMatch = citationPattern.exec(text)) !== null) {
      const citationStrs = scanMatch[1].split(',').map(s => s.trim());
      citationStrs.forEach(citationStr => {
        const { prefix, number } = parseCitation(citationStr);
        const citationKey = prefix ? `${prefix}${number}` : String(number);
        if (citationToSource.has(citationKey)) {
          foundCitations.add(citationKey);
        }
      });
    }

    // Build usedSources array in order of first appearance
    usedSources = [];
    usedNumberToIndex = new Map<string, number>();
    
    // Process citations in order: Web first, then RAG, then Memory
    const allCitationKeys = Array.from(foundCitations).sort((a, b) => {
      // Sort: Web (numeric) < RAG (R) < Memory (M)
      const aPrefix = a.match(/^([RMW]?)/)?.[1] || '';
      const bPrefix = b.match(/^([RMW]?)/)?.[1] || '';
      const order = { '': 0, 'R': 1, 'M': 2 };
      const aOrder = order[aPrefix as keyof typeof order] ?? 3;
      const bOrder = order[bPrefix as keyof typeof order] ?? 3;
      if (aOrder !== bOrder) return aOrder - bOrder;
      // Within same type, sort by number
      const aNum = parseInt(a.replace(/^[RMW]/, ''), 10);
      const bNum = parseInt(b.replace(/^[RMW]/, ''), 10);
      return aNum - bNum;
    });

    allCitationKeys.forEach(citationKey => {
      const citationData = citationToSource.get(citationKey);
      if (citationData) {
        const usedIndex = usedSources.length;
        usedSources.push(citationData.source);
        usedNumberToIndex.set(citationKey, usedIndex);
      }
    });
  }

  // Graceful fallback: if no sources are used, return text as-is
  if (usedSources.length === 0) {
    return <>{text}</>;
  }

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  // Reset regex for main processing
  citationPattern.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = citationPattern.exec(text)) !== null) {
    const matchStart = match.index;
    const matchEnd = match.index + match[0].length;

    if (matchStart > lastIndex) {
      parts.push(text.slice(lastIndex, matchStart));
    }

    const citationStrs = match[1].split(',').map(s => s.trim());
    const citationData: Array<{ source: Source; index: number; total: number; displayText: string }> = [];

    citationStrs.forEach(citationStr => {
      const { prefix, number } = parseCitation(citationStr);
      const citationKey = prefix ? `${prefix}${number}` : String(number);
      const citationInfo = citationToSource.get(citationKey);
      
      if (citationInfo) {
        const usedIndex = usedNumberToIndex.get(citationKey);
        if (usedIndex !== undefined) {
          // Use the total from citationInfo (group-specific) for proper display
          citationData.push({
            source: citationInfo.source,
            index: usedIndex,
            total: citationInfo.total, // Use group-specific total (e.g., 2 for Memory if there are 2 Memory sources)
            displayText: citationKey // Display as "R1", "M2", "1", etc.
          });
        } else {
          // Fallback: if citation key not in usedNumberToIndex, try to find it directly
          // This can happen if the citation wasn't in the initial scan but is in this fragment
          const directSource = citationInfo.source;
          if (directSource) {
            // Find the index in usedSources
            const foundIdx = usedSources.findIndex(s => s.id === directSource.id);
            if (foundIdx >= 0) {
              citationData.push({
                source: directSource,
                index: foundIdx,
                total: citationInfo.total,
                displayText: citationKey
              });
            }
          }
        }
      }
    });

    // Sort by usedIndex to maintain order
    citationData.sort((a, b) => a.index - b.index);

    if (citationData.length > 0) {
      // Create separate citation chips for each citation
      citationData.forEach((data, idx) => {
        parts.push(
          <InlineCitation
            key={`cite-${matchStart}-${idx}`}
            index={data.index}
            source={data.source}
            total={data.total}
            displayText={data.displayText}
          />
        );
        
        // Add a comma separator between citations (except for the last one)
        if (idx < citationData.length - 1) {
          parts.push(', ');
        }
      });
    } else {
      // No matching source, keep raw marker
      parts.push(match[0]);
    }

    lastIndex = matchEnd;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
};

