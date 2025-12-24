/**
 * Discovery API client for unified search across Facts, Index, and Files.
 * 
 * This module provides TypeScript types and functions matching the backend
 * Discovery Contract (server/contracts/discovery.py).
 */

export type DiscoveryDomain = "facts" | "index" | "files";
export type DiscoverySourceKind = "chat_message" | "file" | "fact";

export interface DiscoveryQuery {
  query: string;
  scope?: DiscoveryDomain[];
  limit?: number;
  offset?: number;
  chat_id?: string;
  project_id?: string;
  filters?: Record<string, any>;
}

export interface DiscoverySource {
  kind: DiscoverySourceKind;
  source_message_uuid?: string;
  source_chat_id?: string;
  source_file_id?: string;
  source_file_path?: string;
  source_fact_id?: string;
  snippet?: string;
  created_at?: string;
  meta?: Record<string, any>;
}

export interface DiscoveryHit {
  id: string;
  domain: DiscoveryDomain;
  type: string;
  title?: string;
  text: string;
  score?: number;
  rank?: number;
  sources: DiscoverySource[];
  meta?: Record<string, any>;
}

export interface DiscoveryResponse {
  query: string;
  hits: DiscoveryHit[];
  counts: Record<string, number>;
  timings_ms: Record<string, number>;
  degraded: Record<string, string>;
}

/**
 * Search across Facts, Index, and Files using the unified Discovery endpoint.
 * 
 * @param payload - Discovery query parameters
 * @returns Promise resolving to DiscoveryResponse
 */
export async function searchDiscovery(payload: DiscoveryQuery): Promise<DiscoveryResponse> {
  const response = await fetch("http://localhost:8000/discovery/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query: payload.query,
      scope: payload.scope || ["facts", "index", "files"],
      limit: payload.limit || 20,
      offset: payload.offset || 0,
      chat_id: payload.chat_id,
      project_id: payload.project_id,
      filters: payload.filters,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    let errorMessage = "Failed to search";
    try {
      const errorData = JSON.parse(errorText);
      errorMessage = errorData.detail || errorData.message || errorMessage;
    } catch {
      errorMessage = errorText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return response.json();
}

