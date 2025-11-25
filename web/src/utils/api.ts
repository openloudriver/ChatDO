/**
 * API client utilities for ChatDO frontend
 */

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

