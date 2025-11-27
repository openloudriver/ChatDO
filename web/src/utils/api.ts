/**
 * API client utilities for ChatDO frontend
 */
import type { ImpactEntry, ImpactTemplate } from "../types/impact";

export type ProjectMemorySources = {
  project_id: string;
  memory_sources: string[];
};

export async function fetchProjectMemorySources(projectId: string): Promise<ProjectMemorySources> {
  const res = await fetch(`http://localhost:8000/api/projects/${projectId}/memory-sources`);
  if (!res.ok) throw new Error("Failed to load project memory sources");
  return res.json();
}

export async function updateProjectMemorySources(
  projectId: string,
  memorySources: string[]
): Promise<ProjectMemorySources> {
  const res = await fetch(`http://localhost:8000/api/projects/${projectId}/memory-sources`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ memory_sources: memorySources }),
  });
  if (!res.ok) throw new Error("Failed to update project memory sources");
  return res.json();
}

export async function fetchMemorySources(): Promise<any[]> {
  const res = await fetch("http://127.0.0.1:5858/sources");
  if (!res.ok) throw new Error("Failed to load memory sources");
  const data = await res.json();
  return data.sources || [];
}

export async function addMemorySource(params: {
  rootPath: string;
  displayName?: string;
  projectId?: string;
}) {
  const res = await fetch("http://localhost:8000/api/memory/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      root_path: params.rootPath,
      display_name: params.displayName,
      project_id: params.projectId ?? "scratch",
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || "Failed to add memory source");
  }
  return res.json();
}

export async function deleteMemorySource(sourceId: string): Promise<void> {
  const res = await fetch(
    `http://localhost:8000/api/memory/sources/${encodeURIComponent(sourceId)}`,
    {
      method: 'DELETE',
    },
  );
  if (!res.ok) {
    let message = 'Failed to delete memory source';
    try {
      const data = await res.json().catch(() => null);
      message = data?.detail || data?.message || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
}

// Impacts
export interface ImpactCreatePayload {
  title: string;
  date?: string | null;
  context?: string | null;
  actions: string;
  impact?: string | null;
  metrics?: string | null;
  tags?: string[];
  notes?: string | null;
}

export async function fetchImpacts(): Promise<ImpactEntry[]> {
  const res = await fetch("http://localhost:8000/api/impacts/");
  if (!res.ok) throw new Error("Failed to load impacts");
  return res.json();
}

export async function createImpact(payload: ImpactCreatePayload): Promise<ImpactEntry> {
  const res = await fetch("http://localhost:8000/api/impacts/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create impact");
  return res.json();
}

export async function updateImpact(
  id: string,
  patch: Partial<ImpactCreatePayload>
): Promise<ImpactEntry> {
  const res = await fetch(`http://localhost:8000/api/impacts/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to update impact");
  return res.json();
}

export async function deleteImpact(id: string): Promise<void> {
  const res = await fetch(`http://localhost:8000/api/impacts/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete impact");
}

// Templates
export async function fetchImpactTemplates(): Promise<ImpactTemplate[]> {
  const res = await fetch("http://localhost:8000/api/impact-templates/");
  if (!res.ok) throw new Error("Failed to load impact templates");
  return res.json();
}

export interface ImpactTemplateUploadPayload {
  file: File;
  name: string;
  description?: string;
  tags?: string; // comma-separated string
}

export async function uploadImpactTemplate(
  payload: ImpactTemplateUploadPayload
): Promise<ImpactTemplate> {
  const form = new FormData();
  form.append("file", payload.file);
  form.append("name", payload.name);
  if (payload.description) form.append("description", payload.description);
  if (payload.tags) form.append("tags", payload.tags);

  const res = await fetch("http://localhost:8000/api/impact-templates/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error("Failed to upload template");
  return res.json();
}

export async function deleteImpactTemplate(id: string): Promise<void> {
  const res = await fetch(`http://localhost:8000/api/impact-templates/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete template");
}

// Template Autofill Engine
export interface Template {
  template_id: string;
  filename: string;
  ext: string;
  fields: Array<{
    id?: string;  // PDF field ID
    field_id?: string;  // GPT-analyzed field ID
    name?: string;  // PDF field name
    label?: string;  // GPT-analyzed label
    instructions?: string;  // GPT-analyzed instructions
    page?: number;  // PDF page number
    type?: string;  // Field type (e.g., "text")
    maxChars?: number;  // Character limit
  }>;
  created_at: string;
  pages?: number;
}

export interface TemplateUploadResponse {
  template_id: string;
  filename: string;
  fields: Array<{
    field_id: string;
    label: string;
    instructions: string;
  }>;
}

export async function uploadTemplate(file: File): Promise<TemplateUploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch("http://localhost:8000/api/templates/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error("Failed to upload template");
  return res.json();
}

export async function listTemplates(): Promise<Template[]> {
  const res = await fetch("http://localhost:8000/api/templates");
  if (!res.ok) throw new Error("Failed to load templates");
  return res.json();
}

export interface AutofillRequest {
  field_assignments: Record<string, string>; // field_id -> impact_id
}

export interface AutofillResponse {
  template_id: string;
  output_path: string;
  output_text: string;
}

export async function autofillTemplate(
  templateId: string,
  fieldAssignments: Record<string, string>
): Promise<AutofillResponse> {
  const res = await fetch(`http://localhost:8000/api/templates/${templateId}/autofill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field_assignments: fieldAssignments }),
  });
  if (!res.ok) throw new Error("Failed to autofill template");
  return res.json();
}

export interface LatestAutofillResponse {
  template_id: string;
  output_path: string;
  output_text: string;
  created_at: string;
}

export async function getLatestAutofill(templateId: string): Promise<LatestAutofillResponse> {
  const res = await fetch(`http://localhost:8000/api/templates/${templateId}/autofill/latest`);
  if (!res.ok) throw new Error("Failed to get latest autofill");
  return res.json();
}

export async function getTemplate(templateId: string): Promise<Template> {
  const res = await fetch(`http://localhost:8000/api/templates/${templateId}`);
  if (!res.ok) throw new Error("Failed to get template");
  return res.json();
}

export async function deleteTemplate(templateId: string): Promise<void> {
  const res = await fetch(`http://localhost:8000/api/templates/${templateId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete template");
}

