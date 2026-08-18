import { useEffect, useState } from "react";
import { api, type Desk, type ReportSummary } from "../api";
import { formatDateTime } from "../utils";
import { useJobActivity } from "../hooks/useJobActivity";

export default function Reports() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [desks, setDesks] = useState<Desk[]>([]);
  const [desk, setDesk] = useState("");
  const [period, setPeriod] = useState("monthly");
  const [customInstructions, setCustomInstructions] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { runJob } = useJobActivity();

  async function load() {
    setLoading(true);
    try {
      const [r, d] = await Promise.all([
        api.get<{ reports: ReportSummary[] }>("/api/reports?limit=50"),
        api.get<{ desks: Desk[] }>("/api/desks"),
      ]);
      setReports(r.reports);
      setDesks(d.desks);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function generateReport() {
    setError(null);
    try {
      const payload: Record<string, unknown> = { period };
      if (desk) payload.desk_ids = [desk];
      if (customInstructions.trim()) payload.custom_instructions = customInstructions.trim();
      const result = await runJob("/api/reports/generate", payload, {
        start: "Generating Report",
        running: "Synthesizing intelligence",
        wait: "Building stakeholder brief...",
      });
      alert("Report generated: " + result.title);
      load();
    } catch (e: any) {
      setError(e.message || "Report generation failed");
    }
  }

  return (
    <div>
      <h1>Reports</h1>
      <p className="subtitle">Stakeholder-ready Cotiviti intelligence briefs</p>
      {error && <p className="error-text" style={{ marginBottom: "var(--space-4)" }}>{error}</p>}
      <div className="btn-group" style={{ marginBottom: "var(--space-3)", alignItems: "center" }}>
        <select className="inline-select" value={desk} onChange={(e) => setDesk(e.target.value)}>
          <option value="">All Desks</option>
          {desks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} — {d.name}
            </option>
          ))}
        </select>
        <select className="inline-select" value={period} onChange={(e) => setPeriod(e.target.value)}>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
        <button className="btn btn-primary" onClick={generateReport}>
          Generate Report
        </button>
      </div>
      <div className="form-group" style={{ marginBottom: "var(--space-6)", maxWidth: 560 }}>
        <label>Custom instructions (optional)</label>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          placeholder="e.g. Emphasize competitive positioning vs. incumbents this run."
        />
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Period</th>
              <th>Generated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className="empty">
                  Loading...
                </td>
              </tr>
            ) : !reports.length ? (
              <tr>
                <td colSpan={4} className="empty">
                  No reports yet
                </td>
              </tr>
            ) : (
              reports.map((r) => (
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
                    {r.has_pdf && (
                      <>
                        {" "}
                        · <a className="link" href={`/api/reports/${r.id}/download/pdf`}>PDF</a>
                      </>
                    )}{" "}
                    · <a className="link" href={`/api/reports/${r.id}/download/markdown`}>MD</a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
