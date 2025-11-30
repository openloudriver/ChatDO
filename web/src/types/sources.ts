export type SourceKind = 'url' | 'file' | 'text' | 'note' | 'web' | 'rag';

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
  sourceType?: 'web' | 'rag'; // For styling
  createdAt?: string; // Legacy support
  meta?: Record<string, any>;
};
