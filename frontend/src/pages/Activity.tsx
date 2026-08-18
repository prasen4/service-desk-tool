import { useJobActivity } from "../hooks/useJobActivity";
import { formatDateTime } from "../utils";
import type { Job } from "../api";

const KIND_LABEL: Record<string, string> = {
  pipeline: "Full pipeline",
  research: "Research",
  report: "Report generation",
};

function jobTitle(j: Job): string {
  return KIND_LABEL[j.job_type] || j.job_type;
}

function badgeClass(status: string): string {
  if (status === "completed") return "badge badge-completed";
  if (status === "failed") return "badge badge-failed";
  if (status === "running") return "badge badge-running";
  return "badge badge-pending";
}

export default function Activity() {
  const { jobs } = useJobActivity();

  return (
    <div>
      <h1>Activity</h1>
      <p className="subtitle">
        Live status of research, report, and pipeline jobs. This view updates automatically.
      </p>
      <div className="panel">
        {!jobs.length ? (
          <div className="empty">No jobs yet. Run research or a pipeline to see activity here.</div>
        ) : (
          jobs.map((j) => {
            const active = j.status === "running" || j.status === "pending";
            const detail =
              j.status === "failed" ? (
                <span className="error-text">{(j.error || "Failed").split("\n")[0]}</span>
              ) : (
                j.message || ""
              );
            return (
              <div className="job-row" key={j.id}>
                {active ? <span className="pulse-dot" /> : <span style={{ width: 9 }} />}
                <div className="job-main">
                  <div className="job-title">
                    {jobTitle(j)} <span className={badgeClass(j.status)}>{j.status}</span>
                  </div>
                  <div className="job-sub">
                    {formatDateTime(j.created_at)}
                    {detail ? <> · {detail}</> : null}
                  </div>
                  {active && (
                    <div className="job-progress-track">
                      <div className="job-progress-fill" style={{ width: `${j.progress || 5}%` }} />
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
