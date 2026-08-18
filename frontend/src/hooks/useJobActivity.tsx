import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Job } from "../api";

interface StatusBarState {
  title: string;
  msg: string;
  progress: number;
}

interface JobLabels {
  start: string;
  running: string;
  wait: string;
}

interface JobActivityContextValue {
  jobs: Job[];
  activeCount: number;
  statusBar: StatusBarState | null;
  refresh: () => Promise<void>;
  runJob: (endpoint: string, payload: Record<string, unknown>, labels: JobLabels) => Promise<any>;
}

const JobActivityContext = createContext<JobActivityContextValue | null>(null);

function jobTitle(j: Job): string {
  const kinds: Record<string, string> = {
    pipeline: "Full pipeline",
    research: "Research",
    report: "Report generation",
    position_paper: "Position paper",
  };
  return kinds[j.job_type] || j.job_type;
}

export function JobActivityProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [statusBar, setStatusBar] = useState<StatusBarState | null>(null);
  const activeLocalJob = useRef(false);

  const refresh = useCallback(async () => {
    let list: Job[] = [];
    try {
      list = (await api.get<{ jobs: Job[] }>("/api/jobs?limit=15")).jobs || [];
    } catch {
      return;
    }
    setJobs(list);
    const active = list.filter((j) => j.status === "running" || j.status === "pending");
    if (!activeLocalJob.current) {
      if (active.length) {
        const j = active[0];
        setStatusBar({ title: `${jobTitle(j)} running`, msg: j.message || "Working...", progress: j.progress || 10 });
      } else {
        setStatusBar(null);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const runJob = useCallback(
    async (endpoint: string, payload: Record<string, unknown>, labels: JobLabels) => {
      activeLocalJob.current = true;
      setStatusBar({ title: labels.start, msg: labels.wait, progress: 2 });
      try {
        const { job_id } = await api.post<{ job_id: string }>(endpoint, { ...payload, async_mode: true });
        refresh();
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const job = await api.get<Job>(`/api/jobs/${job_id}`);
          setStatusBar({ title: labels.running, msg: job.message || labels.wait, progress: job.progress || 10 });
          if (job.status === "completed") {
            setStatusBar(null);
            return job.result;
          }
          if (job.status === "failed") {
            setStatusBar(null);
            throw new Error(job.error || "Job failed");
          }
          await new Promise((r) => setTimeout(r, 2000));
        }
      } finally {
        activeLocalJob.current = false;
        refresh();
      }
    },
    [refresh]
  );

  return (
    <JobActivityContext.Provider value={{ jobs, activeCount: jobs.filter((j) => j.status === "running" || j.status === "pending").length, statusBar, refresh, runJob }}>
      {children}
    </JobActivityContext.Provider>
  );
}

export function useJobActivity(): JobActivityContextValue {
  const ctx = useContext(JobActivityContext);
  if (!ctx) throw new Error("useJobActivity must be used within JobActivityProvider");
  return ctx;
}
