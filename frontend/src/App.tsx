import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Archive,
  CheckCircle2,
  Database,
  FolderSearch,
  HardDrive,
  Loader2,
  ShieldCheck,
  Trash2
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  createJob,
  getReport,
  initialToken,
  listJobs,
  openJobEvents,
  runArchive,
  runClean,
  saveToken
} from "./api";
import type { ActionResult, Candidate, DuplicateGroup, Job, Report } from "./types";

const CHART_COLORS = ["#047857", "#2563eb", "#d97706", "#be123c", "#6d28d9", "#0f766e"];

export function App() {
  const [token, setToken] = useState(initialToken());
  const [tokenInput, setTokenInput] = useState(token);
  const [scanPath, setScanPath] = useState("");
  const [ageMonths, setAgeMonths] = useState(6);
  const [includeDuplicates, setIncludeDuplicates] = useState(true);
  const [includeNearDuplicates, setIncludeNearDuplicates] = useState(true);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [selectedCache, setSelectedCache] = useState<Set<string>>(new Set());
  const [selectedOld, setSelectedOld] = useState<Set<string>>(new Set());
  const [archiveTarget, setArchiveTarget] = useState("");
  const [dryRunClean, setDryRunClean] = useState(true);
  const [dryRunArchive, setDryRunArchive] = useState(true);
  const [cleanPhrase, setCleanPhrase] = useState("");
  const [archivePhrase, setArchivePhrase] = useState("");
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    saveToken(token);
    refreshJobs(token).catch((err) => setError(err.message));
  }, [token]);

  useEffect(() => {
    if (!token || !activeJob) return;
    if (activeJob.status === "completed") {
      loadReport(token, activeJob.id).catch((err) => setError(err.message));
      return;
    }
    if (activeJob.status === "failed") return;

    const events = openJobEvents(token, activeJob.id, (job) => {
      setActiveJob(job);
      setJobs((current) => mergeJob(current, job));
      if (job.status === "completed") {
        loadReport(token, job.id).catch((err) => setError(err.message));
      }
    });
    events.onerror = () => events.close();
    return () => events.close();
  }, [token, activeJob?.id, activeJob?.status]);

  async function refreshJobs(apiToken = token) {
    const response = await listJobs(apiToken);
    setJobs(response.jobs);
    if (!activeJob && response.jobs.length > 0) {
      setActiveJob(response.jobs[0]);
      if (response.jobs[0].status === "completed") {
        await loadReport(apiToken, response.jobs[0].id);
      }
    }
  }

  async function loadReport(apiToken: string, jobId: string) {
    const nextReport = await getReport(apiToken, jobId);
    setReport(nextReport);
    setSelectedCache(new Set());
    setSelectedOld(new Set());
  }

  async function submitJob(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setActionResult(null);
    const job = await createJob(token, {
      path: scanPath.trim() || undefined,
      age_months: ageMonths,
      include_duplicates: includeDuplicates,
      include_near_duplicates: includeDuplicates && includeNearDuplicates
    });
    setActiveJob(job);
    setReport(null);
    setJobs((current) => mergeJob(current, job));
  }

  async function selectJob(job: Job) {
    setActiveJob(job);
    setActionResult(null);
    setError("");
    if (job.status === "completed") {
      await loadReport(token, job.id);
    } else {
      setReport(null);
    }
  }

  async function submitClean() {
    if (!activeJob) return;
    setError("");
    setActionResult(null);
    const result = await runClean(token, activeJob.id, {
      candidate_ids: [...selectedCache],
      dry_run: dryRunClean,
      confirmation_phrase: dryRunClean ? undefined : cleanPhrase
    });
    setActionResult(result);
  }

  async function submitArchive() {
    if (!activeJob) return;
    setError("");
    setActionResult(null);
    const result = await runArchive(token, activeJob.id, {
      candidate_ids: [...selectedOld],
      dry_run: dryRunArchive,
      confirmation_phrase: dryRunArchive ? undefined : archivePhrase,
      target_path: archiveTarget.trim() || undefined
    });
    setActionResult(result);
  }

  if (!token) {
    return (
      <main className="auth-screen">
        <section className="auth-panel">
          <ShieldCheck aria-hidden="true" />
          <h1>Disk Space Manager</h1>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setToken(tokenInput.trim());
            }}
          >
            <label htmlFor="token">API token</label>
            <input
              id="token"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              autoFocus
            />
            <button type="submit">Connect</button>
          </form>
        </section>
      </main>
    );
  }

  const currentJob = report?.job || activeJob;
  const savingsData = report
    ? [
        { name: "Cache", bytes: report.savings.cache_size },
        { name: "Old files", bytes: report.savings.old_files_size },
        { name: "Duplicates", bytes: report.savings.exact_duplicate_reclaimable_size }
      ]
    : [];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <HardDrive aria-hidden="true" />
          <div>
            <h1>Disk Space Manager</h1>
            <span>{jobs.length} jobs</span>
          </div>
        </div>

        <form className="scan-form" onSubmit={(event) => submitJob(event).catch((err) => setError(err.message))}>
          <label htmlFor="path">Path</label>
          <input
            id="path"
            placeholder="Default: home directory"
            value={scanPath}
            onChange={(event) => setScanPath(event.target.value)}
          />

          <label htmlFor="age">Age threshold</label>
          <div className="inline-control">
            <input
              id="age"
              type="number"
              min="1"
              max="120"
              value={ageMonths}
              onChange={(event) => setAgeMonths(Number(event.target.value))}
            />
            <span>months</span>
          </div>

          <label className="toggle-row">
            <input
              type="checkbox"
              checked={includeDuplicates}
              onChange={(event) => setIncludeDuplicates(event.target.checked)}
            />
            Exact duplicates
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={includeNearDuplicates}
              disabled={!includeDuplicates}
              onChange={(event) => setIncludeNearDuplicates(event.target.checked)}
            />
            Near duplicates
          </label>

          <button type="submit" className="primary-button">
            <FolderSearch aria-hidden="true" />
            Scan
          </button>
        </form>

        <div className="job-list">
          {jobs.map((job) => (
            <button
              key={job.id}
              className={job.id === activeJob?.id ? "job-button active" : "job-button"}
              onClick={() => selectJob(job).catch((err) => setError(err.message))}
            >
              <span>{shortPath(job.path)}</span>
              <small>{job.status}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="content">
        {error && <div className="alert">{error}</div>}

        {currentJob && (
          <section className="status-band">
            <div>
              <span className={`status-pill ${currentJob.status}`}>{currentJob.status}</span>
              <h2>{currentJob.path}</h2>
              <p>{currentJob.progress_message}</p>
            </div>
            <div className="progress-wrap" aria-label="Job progress">
              <div style={{ width: `${currentJob.progress_percent}%` }} />
            </div>
          </section>
        )}

        {!currentJob && (
          <section className="empty-state">
            <Database aria-hidden="true" />
            <h2>No report selected</h2>
          </section>
        )}

        {currentJob?.status === "running" || currentJob?.status === "queued" ? (
          <section className="loading-state">
            <Loader2 aria-hidden="true" className="spin" />
            <span>{currentJob.progress_phase}</span>
          </section>
        ) : null}

        {report && (
          <>
            <section className="metric-grid">
              <Metric label="Scanned" value={String(report.scan.total_scanned)} />
              <Metric label="Total size" value={report.summary.total_size_formatted} />
              <Metric label="Potential" value={report.savings.total_savings_formatted} />
              <Metric label="Errors" value={String(report.scan.error_count)} />
            </section>

            <section className="chart-grid">
              <div className="panel">
                <h2>File types</h2>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={report.summary.top_extensions}
                      dataKey="size"
                      nameKey="extension"
                      innerRadius={54}
                      outerRadius={92}
                      paddingAngle={2}
                    >
                      {report.summary.top_extensions.map((entry, index) => (
                        <Cell key={entry.extension} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value: number) => formatBytes(value)} />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="panel">
                <h2>Potential savings</h2>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={savingsData}>
                    <CartesianGrid vertical={false} stroke="#d7dde4" />
                    <XAxis dataKey="name" />
                    <YAxis tickFormatter={formatBytes} width={78} />
                    <Tooltip formatter={(value: number) => formatBytes(value)} />
                    <Bar dataKey="bytes" fill="#047857" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="tables-grid">
              <SizeTable title="Largest directories" rows={report.largest_directories} />
              <SizeTable title="Largest files" rows={report.largest_files} />
            </section>

            <DuplicateReview report={report} />

            <section className="candidate-grid">
              <div className="panel">
                <CandidateHeader
                  icon={<Trash2 aria-hidden="true" />}
                  title="Cache candidates"
                  count={report.candidate_counts.cache}
                  selected={selectedCache.size}
                />
                <CandidateTable
                  candidates={report.cache_candidates}
                  selected={selectedCache}
                  setSelected={setSelectedCache}
                  metadataKey="reason"
                />
                <ActionPanel
                  action="clean"
                  dryRun={dryRunClean}
                  setDryRun={setDryRunClean}
                  phrase={cleanPhrase}
                  setPhrase={setCleanPhrase}
                  expected={report.job.confirmation_phrases.clean}
                  selectedCount={selectedCache.size}
                  onRun={() => submitClean().catch((err) => setError(err.message))}
                />
              </div>

              <div className="panel">
                <CandidateHeader
                  icon={<Archive aria-hidden="true" />}
                  title="Old file candidates"
                  count={report.candidate_counts.old}
                  selected={selectedOld.size}
                />
                <label htmlFor="archive-target">Archive target</label>
                <input
                  id="archive-target"
                  value={archiveTarget}
                  onChange={(event) => setArchiveTarget(event.target.value)}
                  placeholder="/path/to/archive"
                />
                <CandidateTable
                  candidates={report.old_candidates}
                  selected={selectedOld}
                  setSelected={setSelectedOld}
                  metadataKey="days_old"
                />
                <ActionPanel
                  action="archive"
                  dryRun={dryRunArchive}
                  setDryRun={setDryRunArchive}
                  phrase={archivePhrase}
                  setPhrase={setArchivePhrase}
                  expected={report.job.confirmation_phrases.archive}
                  selectedCount={selectedOld.size}
                  onRun={() => submitArchive().catch((err) => setError(err.message))}
                />
              </div>
            </section>
          </>
        )}

        {actionResult && (
          <section className="result-toast">
            <CheckCircle2 aria-hidden="true" />
            <span>
              {actionResult.action_type} {actionResult.dry_run ? "dry run" : "completed"}:
              {" "}{JSON.stringify(actionResult.result)}
            </span>
          </section>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SizeTable({ title, rows }: { title: string; rows: { path: string; size_formatted: string }[] }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path}>
              <td className="path-cell">{row.path}</td>
              <td>{row.size_formatted}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DuplicateReview({ report }: { report: Report }) {
  const exactGroups = report.duplicates.exact.groups || [];
  const nearGroups = report.duplicates.near.groups || [];
  if (exactGroups.length === 0 && nearGroups.length === 0) {
    return (
      <section className="panel">
        <h2>Duplicate review</h2>
        <p className="muted">No duplicate groups found in this report.</p>
      </section>
    );
  }

  return (
    <section className="duplicate-grid">
      <DuplicateGroupList
        title="Exact duplicates"
        groups={exactGroups}
        metric={report.duplicates.exact.reclaimable_size_formatted || "0.00 B"}
      />
      <DuplicateGroupList
        title="Near duplicates"
        groups={nearGroups}
        metric={report.duplicates.near.reviewable_size_formatted || "0.00 B"}
      />
    </section>
  );
}

function DuplicateGroupList({
  title,
  groups,
  metric
}: {
  title: string;
  groups: DuplicateGroup[];
  metric: string;
}) {
  return (
    <div className="panel">
      <div className="candidate-header">
        <div>
          <Database aria-hidden="true" />
          <h2>{title}</h2>
        </div>
        <span>{metric}</span>
      </div>
      <div className="duplicate-list">
        {groups.slice(0, 8).map((group, index) => (
          <article key={`${title}-${index}`} className="duplicate-group">
            <div>
              <strong>{group.file_count} files</strong>
              <span>
                {group.reclaimable_size_formatted ||
                  group.reviewable_size_formatted ||
                  group.total_size_formatted ||
                  ""}
              </span>
            </div>
            {group.reason && <p>{group.reason}</p>}
            <ul>
              {group.files.slice(0, 5).map((file) => (
                <li key={file.path}>
                  <span>{file.path}</span>
                  <small>{file.size_formatted}</small>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

function CandidateHeader({
  icon,
  title,
  count,
  selected
}: {
  icon: ReactNode;
  title: string;
  count: number;
  selected: number;
}) {
  return (
    <div className="candidate-header">
      <div>
        {icon}
        <h2>{title}</h2>
      </div>
      <span>
        {selected}/{count}
      </span>
    </div>
  );
}

function CandidateTable({
  candidates,
  selected,
  setSelected,
  metadataKey
}: {
  candidates: Candidate[];
  selected: Set<string>;
  setSelected: (next: Set<string>) => void;
  metadataKey: string;
}) {
  const visible = candidates.slice(0, 250);
  const allVisibleSelected = visible.length > 0 && visible.every((candidate) => selected.has(candidate.id));

  function toggle(candidateId: string) {
    const next = new Set(selected);
    if (next.has(candidateId)) next.delete(candidateId);
    else next.add(candidateId);
    setSelected(next);
  }

  function toggleVisible() {
    const next = new Set(selected);
    if (allVisibleSelected) {
      visible.forEach((candidate) => next.delete(candidate.id));
    } else {
      visible.forEach((candidate) => next.add(candidate.id));
    }
    setSelected(next);
  }

  return (
    <div className="candidate-table">
      <div className="table-toolbar">
        <button type="button" onClick={toggleVisible}>
          {allVisibleSelected ? "Clear" : "Select visible"}
        </button>
        <span>{visible.length} visible</span>
      </div>
      <table>
        <tbody>
          {visible.map((candidate) => (
            <tr key={candidate.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selected.has(candidate.id)}
                  onChange={() => toggle(candidate.id)}
                  aria-label={`Select ${candidate.path}`}
                />
              </td>
              <td className="path-cell">{candidate.path}</td>
              <td>{formatBytes(candidate.size)}</td>
              <td>{String(candidate.metadata[metadataKey] ?? "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActionPanel({
  action,
  dryRun,
  setDryRun,
  phrase,
  setPhrase,
  expected,
  selectedCount,
  onRun
}: {
  action: string;
  dryRun: boolean;
  setDryRun: (value: boolean) => void;
  phrase: string;
  setPhrase: (value: string) => void;
  expected: string;
  selectedCount: number;
  onRun: () => void;
}) {
  return (
    <div className="action-panel">
      <label className="toggle-row">
        <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
        Dry run
      </label>
      {!dryRun && (
        <>
          <label htmlFor={`${action}-phrase`}>Confirmation</label>
          <input
            id={`${action}-phrase`}
            value={phrase}
            onChange={(event) => setPhrase(event.target.value)}
            placeholder={expected}
          />
        </>
      )}
      <button type="button" disabled={selectedCount === 0} onClick={onRun}>
        Run {action}
      </button>
    </div>
  );
}

function mergeJob(jobs: Job[], job: Job): Job[] {
  const existing = jobs.filter((item) => item.id !== job.id);
  return [job, ...existing];
}

function shortPath(path: string): string {
  const parts = path.split("/");
  return parts.slice(-2).join("/") || path;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value)) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(1)} ${units[unit]}`;
}
