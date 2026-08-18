import { useEffect, useState } from "react";
import { api, type Desk, type Health, type ReportSummary, type ResearchRun } from "../api";
import { formatDateTime } from "../utils";
import { useJobActivity } from "../hooks/useJobActivity";

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [lastRun, setLastRun] = useState<ResearchRun | null>(null);
  const [desks, setDesks] = useState<Desk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pipelineDesk, setPipelineDesk] = useState("");
  const [pipelinePeriod, setPipelinePeriod] = useState("daily");
  const [running, setRunning] = useState(false);
  const { runJob } = useJobActivity();

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [h, r, runs, d] = await Promise.all([
        api.get<Health>("/api/health"),
        api.get<{ reports: ReportSummary[] }>("/api/reports?limit=5"),
        api.get<{ runs: ResearchRun[] }>("/api/research/runs?limit=1"),
        api.get<{ desks: Desk[] }>("/api/desks"),
      ]);
      setHealth(h);
      setReports(r.reports);
      setLastRun(runs.runs[0] || null);
      setDesks(d.desks);
    } catch (e: any) {
      setError(e.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function runPipeline() {
    setRunning(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { period: pipelinePeriod };
      if (pipelineDesk) payload.desk_ids = [pipelineDesk];
      const result = await runJob("/api/pipeline/run", payload, {
        start: "Starting Pipeline",
        running: "Pipeline Running",
        wait: "Researching web, curating with AI, generating brief...",
      });
      const r = result.report;
      alert(`Pipeline complete!\n\nUpdates: ${result.research.updates_found}\nReport: ${r.title}`);
      load();
    } catch (e: any) {
      setError(e.message || "Pipeline run failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="subtitle">
        Cotiviti Gen AI technology intelligence — automated briefs for healthcare tech leadership
      </p>

      {error && <p className="error-text" style={{ marginBottom: "var(--space-6)" }}>{error}</p>}

      {health && (
        <div className="cards">
          <div className="card">
            <div className="card-label">System</div>
            <div className={`card-value ${health.status === "ok" ? "ok" : "warn"}`}>
              {health.status === "ok" ? "Ready" : "Check"}
            </div>
          </div>
          <div className="card">
            <div className="card-label">API Key</div>
            <div className={`card-value small ${health.api_key_configured ? "ok" : "warn"}`}>
              {health.api_key_configured ? "Set" : "Not Set"}
            </div>
          </div>
          <div className="card">
            <div className="card-label">Model</div>
            <div className="card-value small">{health.model}</div>
          </div>
          <div className="card">
            <div className="card-label">Last Run</div>
            <div className="card-value small">{lastRun ? `${lastRun.updates_found} updates` : "—"}</div>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>One-Click Automation</h2>
        <p className="helper">
          Run the full pipeline: deep web research across all tech desks, LLM-powered curation, and
          stakeholder-ready report generation.
        </p>
        <div className="form-row" style={{ maxWidth: 600 }}>
          <div className="form-group">
            <label>Tech Desk</label>
            <select value={pipelineDesk} onChange={(e) => setPipelineDesk(e.target.value)}>
              <option value="">All Desks</option>
              {desks.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code} — {d.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Report Period</label>
            <select value={pipelinePeriod} onChange={(e) => setPipelinePeriod(e.target.value)}>
              <option value="daily">Daily Brief</option>
              <option value="weekly">Weekly Intelligence</option>
              <option value="monthly">Monthly Report</option>
            </select>
          </div>
        </div>
        <div className="btn-group">
          <button className="btn btn-accent" disabled={running} onClick={runPipeline}>
            ▶ Run Full Pipeline
          </button>
          <button className="btn btn-outline" onClick={load}>
            ↻ Refresh
          </button>
        </div>
      </div>

      <div className="panel">
        <h2>Recent Reports</h2>
        {loading ? (
          <div className="empty">Loading...</div>
        ) : !reports.length ? (
          <div className="empty">No reports yet. Configure your API key and run the pipeline.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Period</th>
                <th>Generated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{r.title}</td>
                  <td>
                    <span className="badge badge-medium">{r.period}</span>
                  </td>
                  <td>{formatDateTime(r.generated_at)}</td>
                  <td>
                    <a className="link" href={`/api/reports/${r.id}/html`} target="_blank" rel="noreferrer">
                      View
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
