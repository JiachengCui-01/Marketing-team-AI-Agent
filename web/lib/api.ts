export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type CreateSessionResponse = { session_id: string };
export type UploadResponse = {
  file_id: string;
  original_name: string;
  size: number;
};

export async function createSession(): Promise<CreateSessionResponse> {
  const res = await fetch(`${API_BASE}/api/sessions`, { method: "POST" });
  if (!res.ok) throw new Error(`createSession ${res.status}`);
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`deleteSession ${res.status}`);
}

export async function uploadCsv(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`uploadCsv ${res.status}`);
  return res.json();
}

export function streamUrl(
  sessionId: string,
  prompt: string,
  csvId?: string,
): string {
  const url = new URL(`${API_BASE}/api/sessions/${sessionId}/stream`);
  url.searchParams.set("prompt", prompt);
  if (csvId) url.searchParams.set("csv_id", csvId);
  return url.toString();
}
