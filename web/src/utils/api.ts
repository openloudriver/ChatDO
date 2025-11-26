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

