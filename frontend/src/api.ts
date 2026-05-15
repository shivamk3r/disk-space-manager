import type { ActionResult, Job, Report } from "./types";

const API_BASE = import.meta.env.VITE_DSM_API_BASE || "";
const ENV_TOKEN = import.meta.env.VITE_DSM_TOKEN || "";

export function initialToken(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("token") || ENV_TOKEN || localStorage.getItem("dsm-token") || "";
}

export function saveToken(token: string): void {
  localStorage.setItem("dsm-token", token);
}

export async function apiRequest<T>(
  path: string,
  token: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {})
    }
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep HTTP status text when the body is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function createJob(
  token: string,
  payload: {
    path?: string;
    age_months: number;
    include_duplicates: boolean;
    include_near_duplicates: boolean;
  }
): Promise<Job> {
  return apiRequest<Job>("/api/jobs", token, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listJobs(token: string): Promise<{ jobs: Job[] }> {
  return apiRequest<{ jobs: Job[] }>("/api/jobs", token);
}

export function getReport(token: string, jobId: string): Promise<Report> {
  return apiRequest<Report>(`/api/jobs/${jobId}/report`, token);
}

export function runClean(
  token: string,
  jobId: string,
  payload: {
    candidate_ids: string[];
    dry_run: boolean;
    confirmation_phrase?: string;
  }
): Promise<ActionResult> {
  return apiRequest<ActionResult>(`/api/jobs/${jobId}/actions/clean`, token, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runArchive(
  token: string,
  jobId: string,
  payload: {
    candidate_ids: string[];
    dry_run: boolean;
    confirmation_phrase?: string;
    target_path?: string;
    external_path?: string;
  }
): Promise<ActionResult> {
  return apiRequest<ActionResult>(`/api/jobs/${jobId}/actions/archive`, token, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function openJobEvents(
  token: string,
  jobId: string,
  onJob: (job: Job) => void
): EventSource {
  const source = new EventSource(
    `${API_BASE}/api/jobs/${jobId}/events?token=${encodeURIComponent(token)}`
  );
  source.addEventListener("progress", (event) => {
    onJob(JSON.parse((event as MessageEvent).data) as Job);
  });
  return source;
}
