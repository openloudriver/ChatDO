export type SourceKind = 'url' | 'file' | 'text' | 'note';

export interface Source {
  id: string;
  kind: SourceKind;
  title: string;
  description?: string;
  url?: string;          // for url / web articles
  fileName?: string;     // for uploaded files
  createdAt: string;
  meta?: Record<string, any>;
}

