// Shared RAG file type with stable index
export interface RagFile {
  id: string;
  chat_id: string;
  filename: string;
  mime_type: string;
  size: number;
  created_at: string;
  text_path: string | null;
  path?: string | null;  // Path to original file (for preview)
  text_extracted: boolean;
  error?: string | null;
  // Stable, 1-based index for this conversation's tray
  index: number;
}

