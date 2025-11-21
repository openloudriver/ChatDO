export type SourceKind = 'url' | 'file' | 'text' | 'note';

export type Source = {
  id: string;
  kind: SourceKind;
  title: string;
  description?: string;
  url?: string;
  fileName?: string;
  createdAt: string;
  meta?: Record<string, any>;
};
