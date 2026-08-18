// Lightweight typed fetch wrapper for the Tech Desk API. Deliberately avoids
// heavyweight data-fetching libraries (react-query, etc.) to keep the
// dependency surface small; components use the useApi/usePolling hooks below.

export class ApiError extends Error {}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(path, {
    ...options,
    headers: isFormData
      ? options.headers
      : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = await res.json();
      detail = Array.isArray(err.detail)
        ? err.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
        : err.detail || detail;
    } catch {
      /* ignore parse failure, fall back to statusText */
    }
    throw new ApiError(detail || "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// —— Types (loose but useful — mirrors the FastAPI response shapes) ——

export interface Health {
  status: string;
  version: string;
  env: string;
  api_key_configured: boolean;
  provider: string;
  model: string;
  database: string;
  scheduler_enabled: boolean;
}

export interface Desk {
  id: string;
  code: string;
  name: string;
  description: string;
  areas: string[];
  key_vendors?: string[];
}

export interface DesksResponse {
  desks: Desk[];
  organization?: string;
  branding?: Record<string, unknown>;
}

export interface Job {
  id: string;
  job_type: string;
  status: "pending" | "running" | "completed" | "failed" | string;
  message?: string;
  progress?: number;
  created_at: string;
  completed_at?: string | null;
  result?: any;
  error?: string | null;
}

export interface ResearchRun {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: string;
  period: string;
  desks_processed: number;
  updates_found: number;
  vendors_added?: string[];
  error_message: string | null;
  custom_instructions?: string | null;
}

export interface ReportSummary {
  id: number;
  period: string;
  title: string;
  generated_at: string;
  period_start: string;
  period_end: string;
  has_html: boolean;
  has_pdf: boolean;
  custom_instructions?: string | null;
}

export interface UpdateItem {
  title: string;
  desk_id: string;
  desk_code?: string;
  desk_name?: string;
  vendor?: string;
  summary: string;
  source_url: string;
  source_name?: string;
  relevance: string;
  published_date?: string | null;
  discovered_at: string;
  who_is_affected_first?: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  input: number;
  output: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  sdk: string;
  base_url: string;
  key_hint?: string;
  docs?: string;
  requires_deployment?: boolean;
  models: ModelInfo[];
}

export interface Catalog {
  providers: ProviderInfo[];
  current: { provider: string; model: string; base_url: string; api_version?: string; configured: boolean };
  desk_count: number;
  tokens_per_desk_per_run: Record<string, { input: number; output: number }>;
  runs_per_month: Record<string, number>;
  measured: Record<string, { input_per_desk: number; output_per_desk: number; samples: number } | null>;
}

export interface VendorSummary {
  name: string;
  update_count: number;
  latest_at: string | null;
  is_tracked: boolean;
  tracked_desks: { id: string; name: string }[];
}

export interface VendorUpdatesResponse {
  vendor: string;
  is_tracked: boolean;
  tracked_desks: { id: string; name: string }[];
  update_count: number;
  updates: (UpdateItem & { desk_name: string; sort_at: string })[];
}

export interface VendorStatusOption {
  value: string;
  label: string;
  stage_order: number | null;
  is_branch: boolean;
}

export interface VendorNote {
  id: number;
  body: string;
  author: string;
  created_at: string;
  attachments: VendorAttachment[];
}

export interface VendorAttachment {
  id: number;
  note_id: number | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface VendorStatusEvent {
  id: number;
  status: string;
  status_label: string;
  note: string;
  changed_by: string;
  created_at: string;
  duration_label?: string | null;
}

export interface VendorProfile {
  id: number | null;
  name: string;
  status: string | null;
  status_label: string | null;
  owner: string;
  created_at: string | null;
  updated_at: string | null;
  is_tracked: boolean;
  tracked_desks: { id: string; name: string }[];
  news: (UpdateItem & { desk_name: string; sort_at: string })[];
  news_count: number;
  notes: VendorNote[];
  status_history: VendorStatusEvent[];
  attachments: VendorAttachment[];
}

export interface VendorProfileListItem {
  id: number;
  name: string;
  status: string;
  status_label: string;
  owner: string;
  updated_at: string;
}

export interface PositionPaper {
  id: number;
  vendor: string;
  status: "running" | "completed" | "failed" | string;
  custom_prompt: string;
  docx_path: string | null;
  error_message: string | null;
  created_at: string;
  generated_at: string | null;
}
