export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface Job {
  id: string;
  status: JobStatus;
  path: string;
  age_months: number;
  include_duplicates: boolean;
  include_near_duplicates: boolean;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  progress_phase: string;
  progress_percent: number;
  progress_message: string;
  confirmation_phrases: {
    clean: string;
    archive: string;
  };
}

export interface Candidate {
  id: string;
  kind: "cache" | "old";
  path: string;
  size: number;
  metadata: Record<string, unknown>;
}

export interface SizeItem {
  path: string;
  size: number;
  size_formatted: string;
}

export interface DuplicateGroup {
  kind: string;
  file_count: number;
  files: SizeItem[];
  total_size?: number;
  total_size_formatted?: string;
  reclaimable_size?: number;
  reclaimable_size_formatted?: string;
  reviewable_size?: number;
  reviewable_size_formatted?: string;
  reason?: string;
  confidence?: string;
}

export interface DuplicateSection {
  groups: DuplicateGroup[];
  group_count: number;
  duplicate_file_count?: number;
  reviewable_file_count?: number;
  reclaimable_size?: number;
  reclaimable_size_formatted?: string;
  reviewable_size?: number;
  reviewable_size_formatted?: string;
}

export interface ExtensionSummary {
  extension: string;
  count: number;
  size: number;
  size_formatted: string;
}

export interface Report {
  job: Job;
  job_id: string;
  path: string;
  age_months: number;
  scan: {
    total_scanned: number;
    error_count: number;
    errors: string[];
  };
  summary: {
    total_size: number;
    total_size_formatted: string;
    file_count: number;
    average_file_size: number;
    average_file_size_formatted: string;
    top_extensions: ExtensionSummary[];
  };
  largest_files: SizeItem[];
  largest_directories: SizeItem[];
  savings: {
    cache_size: number;
    cache_size_formatted: string;
    cache_file_count: number;
    old_files_size: number;
    old_files_size_formatted: string;
    old_files_count: number;
    exact_duplicate_reclaimable_size: number;
    exact_duplicate_reclaimable_size_formatted: string;
    exact_duplicate_file_count: number;
    total_savings: number;
    total_savings_formatted: string;
  };
  duplicates: {
    exact: DuplicateSection;
    near: DuplicateSection;
  };
  candidate_counts: {
    cache: number;
    old: number;
  };
  cache_candidates: Candidate[];
  old_candidates: Candidate[];
}

export interface ActionResult {
  id: string;
  job_id: string;
  action_type: string;
  dry_run: boolean;
  selected_count: number;
  skipped_count: number;
  result: Record<string, unknown>;
  created_at: string;
}
