export interface ImpactEntry {
  id: string;
  created_at: string;
  updated_at: string;
  title: string;
  date?: string | null;
  context?: string | null;
  actions: string;
  impact?: string | null;
  metrics?: string | null;
  tags: string[];
  notes?: string | null;
  activeBullet?: string | null;
}

export interface ImpactTemplate {
  id: string;
  created_at: string;
  name: string;
  description?: string | null;
  tags: string[];
  file_name: string;
  mime_type?: string | null;
}

