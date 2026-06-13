export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type CreateSessionResponse = {
  session_id: string;
  name: string;
  group_id: string | null;
};
export type UploadResponse = {
  file_id: string;
  original_name: string;
  size: number;
  mime: string;
  ext: string;
};

export type SessionRecord = {
  id: string;
  name: string;
  group_id: string | null;
  created_at: number;
  updated_at: number;
};

export type GroupRecord = {
  id: string;
  name: string;
  created_at: number;
};

export type StoredMessage = {
  role: "user" | "assistant";
  content: string;
};

// ---------- sessions ----------

export async function listSessions(): Promise<SessionRecord[]> {
  const res = await fetch(`${API_BASE}/api/sessions`);
  if (!res.ok) throw new Error(`listSessions ${res.status}`);
  return res.json();
}

export async function createSession(
  opts: { name?: string; group_id?: string | null } = {},
): Promise<CreateSessionResponse> {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  if (!res.ok) throw new Error(`createSession ${res.status}`);
  return res.json();
}

export async function updateSession(
  id: string,
  patch: { name?: string; group_id?: string | null },
): Promise<SessionRecord> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`updateSession ${res.status}`);
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`deleteSession ${res.status}`);
}

export async function getSessionMessages(
  id: string,
): Promise<{ session_id: string; messages: StoredMessage[] }> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}/messages`);
  if (!res.ok) throw new Error(`getSessionMessages ${res.status}`);
  return res.json();
}

// ---------- groups ----------

export async function listGroups(): Promise<GroupRecord[]> {
  const res = await fetch(`${API_BASE}/api/groups`);
  if (!res.ok) throw new Error(`listGroups ${res.status}`);
  return res.json();
}

export async function createGroup(name: string): Promise<GroupRecord> {
  const res = await fetch(`${API_BASE}/api/groups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`createGroup ${res.status}`);
  return res.json();
}

export async function renameGroup(id: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/groups/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`renameGroup ${res.status}`);
}

export async function deleteGroup(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/groups/${id}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`deleteGroup ${res.status}`);
}

// ---------- uploads ----------

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`upload ${res.status}: ${detail || res.statusText}`);
  }
  return res.json();
}

export function uploadPreviewUrl(fileId: string): string {
  return `${API_BASE}/api/uploads/${fileId}/preview`;
}

export function uploadDownloadUrl(fileId: string): string {
  return `${API_BASE}/api/uploads/${fileId}/download`;
}

// ---------- artifacts ----------

export function artifactPreviewUrl(artifactId: string): string {
  return `${API_BASE}/api/artifacts/${artifactId}/preview`;
}

export function artifactDownloadUrl(artifactId: string): string {
  return `${API_BASE}/api/artifacts/${artifactId}/download`;
}

export type ArtifactMeta = {
  id: string;
  session_id: string | null;
  kind: string;
  filename: string;
  mime: string;
  created_at: number;
};

export async function getArtifactMeta(id: string): Promise<ArtifactMeta> {
  const res = await fetch(`${API_BASE}/api/artifacts/${id}`);
  if (!res.ok) throw new Error(`getArtifactMeta ${res.status}`);
  return res.json();
}

// ---------- stream ----------

export function streamUrl(
  sessionId: string,
  prompt: string,
  fileIds: string[] = [],
): string {
  const url = new URL(`${API_BASE}/api/sessions/${sessionId}/stream`);
  url.searchParams.set("prompt", prompt);
  if (fileIds.length > 0) {
    url.searchParams.set("file_ids", fileIds.join(","));
  }
  return url.toString();
}
