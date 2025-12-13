export type SourceKind = 'url' | 'file' | 'text' | 'note' | 'web' | 'rag' | 'memory';

export type Source = {
  id: string;
  kind?: SourceKind; // Legacy support
  title: string;
  description?: string;
  url?: string;
  fileName?: string;
  siteName?: string;
  publishedAt?: string | Date;
  rank?: number; // Lower = more relevant
  sourceType?: 'web' | 'rag' | 'memory'; // For styling and citation prefix
  citationPrefix?: 'R' | 'M' | 'W' | null; // Citation prefix: R=RAG, M=Memory, W=Web, null=Web (default)
  createdAt?: string; // Legacy support
  meta?: Record<string, any>;
};
