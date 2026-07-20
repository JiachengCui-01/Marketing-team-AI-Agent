// In production the frontend should prefer the same-origin `/api` rewrite unless
// NEXT_PUBLIC_API_BASE is explicitly configured. Falling back to 127.0.0.1 in a
// browser points at the user's own machine and causes template/refine requests to
// fail with "Failed to fetch".
const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
const DEFAULT_REMOTE_API_BASE = "https://marketing-agent-api-ufgx.onrender.com";

function isLoopbackHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function shouldUseSameOriginApi(configured: string): boolean {
  if (!configured || typeof window === "undefined") return false;
  if (isLoopbackHost(window.location.hostname)) return false;
  try {
    const configuredUrl = new URL(configured);
    return configuredUrl.origin !== window.location.origin;
  } catch {
    return false;
  }
}

export const API_BASE = shouldUseSameOriginApi(CONFIGURED_API_BASE) ? "" : CONFIGURED_API_BASE;

const TOKEN_KEY = "marketing-agent-auth-token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

function withToken(url: string): string {
  const token = getAuthToken();
  if (!token) return url;
  const next = new URL(url, urlBase());
  next.searchParams.set("token", token);
  return next.toString();
}

function urlBase(): string {
  if (typeof window !== "undefined") return window.location.origin;
  return "http://127.0.0.1:8000";
}

function apiCandidates(path: string): string[] {
  const bases =
    typeof window === "undefined"
      ? [API_BASE || "http://127.0.0.1:8000"]
      : [API_BASE, "", DEFAULT_REMOTE_API_BASE];
  const urls = bases.map((base) => (base ? `${base}${path}` : path));
  return Array.from(new Set(urls));
}

async function parseJsonError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return String(body.detail || body.message || res.statusText);
  } catch {
    return res.statusText;
  }
}

export type UserProfile = {
  id: string;
  account: string;
  username: string;
  real_name: string;
  id_card_masked: string;
  avatar: string | null;
  phone: string | null;
  email: string | null;
  company: string | null;
  title: string | null;
  bio: string | null;
};

export type ProfilePayload = {
  account?: string;
  password?: string;
  username: string;
  real_name?: string;
  id_card?: string;
  avatar?: string | null;
  phone?: string | null;
  email?: string | null;
  company?: string | null;
  title?: string | null;
  bio?: string | null;
};

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
  artifacts?: MessageArtifact[];
};

export type MessageArtifact = {
  artifact_id: string;
  filename: string;
  mime: string;
};

export type MarketingMemoryProfile = {
  role_title: string[];
  industry: string[];
  company_brand: string[];
  products: string[];
  target_customers: string[];
  channels: string[];
  tone_preferences: string[];
  report_format_preferences: string[];
  kpi_data_preferences: string[];
  other_preferences: string[];
};

export type MarketingMemoryResponse = {
  profile: MarketingMemoryProfile;
  updated_at: number | null;
};

// ---------- auth ----------

export async function registerUser(payload: ProfilePayload): Promise<{ token: string; user: UserProfile }> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function loginUser(account: string, password: string): Promise<{ token: string; user: UserProfile }> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account, password }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function logoutUser(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    headers: authHeaders(),
  });
  setAuthToken(null);
}

export async function getMe(): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.user;
}

export async function updateMe(payload: ProfilePayload): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.user;
}

export async function deleteMe(confirmation: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    method: "DELETE",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ confirmation }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  setAuthToken(null);
}

export async function lookupAvatar(account: string): Promise<{ exists: boolean; avatar: string | null; username: string | null }> {
  const url = new URL(`${API_BASE}/api/auth/avatar`, urlBase());
  url.searchParams.set("account", account);
  const res = await fetch(url);
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function getMarketingMemory(): Promise<MarketingMemoryResponse> {
  const res = await fetch(`${API_BASE}/api/memory/marketing`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function saveMarketingMemory(profile: Partial<MarketingMemoryProfile>): Promise<MarketingMemoryResponse> {
  const res = await fetch(`${API_BASE}/api/memory/marketing`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ profile }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function clearMarketingMemory(): Promise<MarketingMemoryResponse> {
  const res = await fetch(`${API_BASE}/api/memory/marketing`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

// ---------- sessions ----------

export async function listSessions(): Promise<SessionRecord[]> {
  const res = await fetch(`${API_BASE}/api/sessions`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`listSessions ${res.status}`);
  return res.json();
}

export async function createSession(
  opts: { name?: string; group_id?: string | null } = {},
): Promise<CreateSessionResponse> {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`updateSession ${res.status}`);
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`deleteSession ${res.status}`);
}

export async function getSessionMessages(
  id: string,
): Promise<{ session_id: string; messages: StoredMessage[] }> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}/messages`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`getSessionMessages ${res.status}`);
  return res.json();
}

export async function completeSession(
  id: string,
  prompt: string,
  fileIds: string[] = [],
  skillIds: string[] = [],
): Promise<{ ok: boolean; text: string; events?: unknown[] }> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}/complete`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ prompt, file_ids: fileIds, skill_ids: skillIds }),
  });
  if (!res.ok) throw new Error(`completeSession ${res.status}`);
  return res.json();
}

// ---------- groups ----------

export async function listGroups(): Promise<GroupRecord[]> {
  const res = await fetch(`${API_BASE}/api/groups`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`listGroups ${res.status}`);
  return res.json();
}

export async function createGroup(name: string): Promise<GroupRecord> {
  const res = await fetch(`${API_BASE}/api/groups`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`createGroup ${res.status}`);
  return res.json();
}

export async function renameGroup(id: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/groups/${id}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`renameGroup ${res.status}`);
}

export async function deleteGroup(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/groups/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`deleteGroup ${res.status}`);
}

// ---------- uploads ----------

function uploadForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

async function uploadTo(url: string, file: File): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: authHeaders(),
    body: uploadForm(file),
  });
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  let lastError: unknown = null;
  for (const url of apiCandidates("/api/upload")) {
    try {
      const res = await uploadTo(url, file);
      if (res.ok) return res.json();
      const detail = await res.text().catch(() => "");
      lastError = new Error(`upload ${res.status}: ${detail || res.statusText}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("upload failed");
}

export function uploadPreviewUrl(fileId: string): string {
  return withToken(`${API_BASE}/api/uploads/${fileId}/preview`);
}

export function uploadDownloadUrl(fileId: string): string {
  return withToken(`${API_BASE}/api/uploads/${fileId}/download`);
}

// ---------- artifacts ----------

export function artifactPreviewUrl(artifactId: string): string {
  return withToken(`${API_BASE}/api/artifacts/${artifactId}/preview`);
}

export function artifactDownloadUrl(artifactId: string): string {
  return withToken(`${API_BASE}/api/artifacts/${artifactId}/download`);
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
  const res = await fetch(`${API_BASE}/api/artifacts/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getArtifactMeta ${res.status}`);
  return res.json();
}

// ---------- news ----------

export type NewsConfig = {
  id: string;
  industry: string;
  detail_level: "brief" | "detailed";
  summary_time: string;
  timezone: string;
  language: "zh" | "en";
  enabled: boolean;
  cancelled_at: number | null;
  revert_at?: number | null;
  last_run_at: number | null;
  created_at: number;
  updated_at: number;
};

export type NewsConfigPayload = {
  industry: string;
  detail_level: "brief" | "detailed";
  summary_time: string;
  timezone: string;
  language: "zh" | "en";
};

export type NewsSummary = {
  id: string;
  summary: string;
  sources?: NewsSource[];
  source_score?: number;
  strong_source_count?: number;
  weak_source_count?: number;
  generated_at: number;
  window_start: number | null;
  window_end: number | null;
  created_at: number;
};

export type NewsSource = {
  url: string;
  domain: string;
  tier: number;
  tier_label: string;
  score: number;
  reason: string;
  is_weak_signal: boolean;
  title?: string | null;
  display_text?: string | null;
};

export async function getNewsConfig(): Promise<NewsConfig | null> {
  const res = await fetch(`${API_BASE}/api/news/config`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.config;
}

export async function saveNewsConfig(payload: NewsConfigPayload): Promise<NewsConfig> {
  const res = await fetch(`${API_BASE}/api/news/config`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.config;
}

export async function deleteNewsConfig(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/news/config`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
}

export async function cancelNews(): Promise<NewsConfig> {
  const res = await fetch(`${API_BASE}/api/news/cancel`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.config;
}

export async function getNewsSummary(): Promise<NewsSummary | null> {
  const res = await fetch(`${API_BASE}/api/news/summary`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.summary;
}

export async function refreshNews(language: "zh" | "en"): Promise<NewsSummary> {
  const res = await fetch(`${API_BASE}/api/news/refresh`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ language }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  const body = await res.json();
  return body.summary;
}

// ---------- marketing image ----------

export type ImageStyleKey = "xiaohongshu" | "taobao" | "amazon" | "instagram" | "generic";

export type WorkflowSkill = {
  id: string;
  name: string;
  description: string;
  structure: string[];
};

export async function getWorkflowSkills(): Promise<WorkflowSkill[]> {
  const res = await fetch(`${API_BASE}/api/skills`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return (await res.json()).skills;
}

export type ImageSkill = {
  id: ImageStyleKey;
  name: string;
  description: string;
  platform: string;
  aspect_ratio: string;
};

export type ImageProcessResult = {
  classification: "object" | "screenshot";
  original: { file_id: string; preview_url: string };
  cutout: { artifact_id: string; preview_url: string } | null;
  warning: string | null;
};

export type ImageGeneration = {
  ok: boolean;
  unavailable?: boolean;
  message?: string;
  artifact_id?: string;
  history_id?: string;
  filename?: string;
  mime?: string;
  style_key?: string;
  prompt?: string;
  created_at?: number;
  preview_url?: string;
};

export type ImageHistoryItem = {
  id: string;
  prompt: string;
  style_key: string;
  artifact_id: string | null;
  created_at: number;
  params: Record<string, unknown>;
  preview_url: string | null;
};

export type ImageTemplate = {
  id: string;
  platform: string;
  style_key: string;
  style: string | null;
  label: string;
  prompt: string;
  aspect_ratio: string | null;
  sort_order: number;
};

export type ImageCutoutResult = {
  artifact_id: string | null;
  preview_url: string | null;
  warning: string | null;
};

export type ImageSource =
  | { type: "upload"; id: string }
  | { type: "cutout"; id: string }
  | { type: "none" };

export async function getImageSkills(): Promise<ImageSkill[]> {
  const res = await fetch(`${API_BASE}/api/image/skills`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return (await res.json()).skills;
}

export async function processImage(fileId: string): Promise<ImageProcessResult> {
  const res = await fetch(`${API_BASE}/api/image/process`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ file_id: fileId }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function cutoutImage(fileId: string): Promise<ImageCutoutResult> {
  const res = await fetch(`${API_BASE}/api/image/cutout`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ file_id: fileId }),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function generateImage(payload: {
  prompt: string;
  style_key?: string | null;
  platform?: string | null;
  source?: ImageSource;
  template_id?: string | null;
  aspect_ratio?: string | null;
}): Promise<ImageGeneration> {
  const res = await fetch(`${API_BASE}/api/image/generate`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function saveComposedImage(payload: {
  file_id: string;
  template_id?: string | null;
  style_key?: string | null;
  prompt?: string | null;
}): Promise<ImageGeneration> {
  const requestInit: RequestInit = {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  };
  let lastError: unknown = null;
  for (const url of apiCandidates("/api/image/compose-save")) {
    try {
      const res = await fetch(url, requestInit);
      if (res.ok) return res.json();
      lastError = new Error(await parseJsonError(res));
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("compose save failed");
}

export async function reeditImage(payload: {
  history_id: string;
  prompt: string;
  style_key?: string | null;
  aspect_ratio?: string | null;
}): Promise<ImageGeneration> {
  const res = await fetch(`${API_BASE}/api/image/re-edit`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json();
}

export async function listImageHistory(): Promise<ImageHistoryItem[]> {
  const res = await fetch(`${API_BASE}/api/image/history`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return (await res.json()).history;
}

export async function deleteImageGeneration(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/image/history/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
}

export async function listImageTemplates(filter?: {
  platform?: string;
  style?: string;
}): Promise<ImageTemplate[]> {
  const params = new URLSearchParams();
  if (filter?.platform && filter.platform !== "all") params.set("platform", filter.platform);
  if (filter?.style && filter.style !== "all") params.set("style", filter.style);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/image/templates${qs ? `?${qs}` : ""}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseJsonError(res));
  return (await res.json()).templates;
}

// ---------- stream ----------

export function streamUrl(
  sessionId: string,
  prompt: string,
  fileIds: string[] = [],
  skillIds: string[] = [],
): string {
  const url = new URL(`${API_BASE}/api/sessions/${sessionId}/stream`, urlBase());
  url.searchParams.set("prompt", prompt);
  if (fileIds.length > 0) {
    url.searchParams.set("file_ids", fileIds.join(","));
  }
  if (skillIds.length > 0) {
    url.searchParams.set("skill_ids", skillIds.join(","));
  }
  const token = getAuthToken();
  if (token) url.searchParams.set("token", token);
  return url.toString();
}
