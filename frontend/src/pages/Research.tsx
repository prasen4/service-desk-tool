import { useEffect, useState } from "react";
import { api, type Desk, type ResearchRun } from "../api";
import { formatDateTime } from "../utils";
import { useJobActivity } from "../hooks/useJobActivity";

export default function Research() {
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [desks, setDesks] = useState<Desk[]>([]);
  const [desk, setDesk] = useState("");
  const [customInstructions, setCustomInstructions] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { runJob } = useJobActivity();

  async function load() {
    setLoading(true);
    try {
      const [r, d] = await Promise.all([
        api.get<{ runs: ResearchRun[] }>("/api/research/runs?limit=20"),
        api.get<{ desks: Desk[] }>("/api/desks"),
      ]);
      setRuns(r.runs);
      setDesks(d.desks);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function runResearch() {
    setError(null);
    try {
      const payload: Record<string, unknown> = { period: "daily" };
      if (desk) payload.desk_ids = [desk];
      if (customInstructions.trim()) payload.custom_instructions = customInstructions.trim();
      const result = await runJob("/api/research/run", payload, {
        start: "Researching",
        running: "Research in progress",
        wait: "Scanning web for tech desk updates...",
      });
      const added = result.vendors_added as string[] | undefined;
      const addedNote = added?.length ? ` New vendors auto-tracked: ${added.join(", ")}.` : "";
      alert(`Research complete: ${result.updates_found} new updates.${addedNote}`);
      load();
    } catch (e: any) {
      setError(e.message || "Research run failed");
    }
  }

  return (
    <div>
      <h1>Research Runs</h1>
      <p className="subtitle">
        Web research and AI curation history — research isn't limited to already-tracked vendors; newly discovered
        vendors relevant to a desk's focus areas are automatically added to that desk's tracked list.
      </p>
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
        <button className="btn btn-primary" onClick={runResearch}>
          Run Research Now
        </button>
      </div>
      <div className="form-group" style={{ marginBottom: "var(--space-6)", maxWidth: 560 }}>
        <label>Custom instructions (optional)</label>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          placeholder="e.g. Prioritize payment integrity vendors this run."
        />
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Started</th>
              <th>Period</th>
              <th>Status</th>
              <th>Desks</th>
              <th>Updates</th>
              <th>New Vendors Tracked</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="empty">
                  Loading...
                </td>
              </tr>
            ) : !runs.length ? (
              <tr>
                <td colSpan={7} className="empty">
                  No research runs yet
                </td>
              </tr>
            ) : (
              runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{formatDateTime(r.started_at)}</td>
                  <td>{r.period}</td>
                  <td>
                    <span className={`badge badge-${r.status === "completed" ? "completed" : "failed"}`}>
                      {r.status}
                    </span>
                  </td>
                  <td>{r.desks_processed}</td>
                  <td>{r.updates_found}</td>
                  <td>{r.vendors_added?.length ? r.vendors_added.join(", ") : "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
