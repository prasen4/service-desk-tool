import { useEffect, useState } from "react";
import { api, type Desk } from "../api";
import { useJobActivity } from "../hooks/useJobActivity";

export default function Desks() {
  const [desks, setDesks] = useState<Desk[]>([]);
  const [loading, setLoading] = useState(true);
  const { runJob } = useJobActivity();

  useEffect(() => {
    api
      .get<{ desks: Desk[] }>("/api/desks")
      .then((d) => setDesks(d.desks))
      .finally(() => setLoading(false));
  }, []);

  async function runMonthly(desk: Desk) {
    if (!confirm(`Run full monthly pipeline for ${desk.name}?`)) return;
    try {
      const result = await runJob(
        "/api/pipeline/run",
        { period: "monthly", desk_ids: [desk.id] },
        { start: "Running Pipeline", running: `Processing ${desk.name}`, wait: "Researching and generating report..." }
      );
      alert(`Done! ${result.report.title}\nUpdates: ${result.report.total_updates}`);
    } catch (e: any) {
      alert("Error: " + e.message);
    }
  }

  return (
    <div>
      <h1>Tech Desks</h1>
      <p className="subtitle">Gen AI monitoring categories aligned with RedCell Technical Prospecting</p>
      {loading ? (
        <div className="empty">Loading...</div>
      ) : (
        <div className="desk-grid">
          {desks.map((d) => (
            <div className="desk-card" key={d.id}>
              <div className="desk-code">{d.code}</div>
              <h3>{d.name}</h3>
              <p style={{ fontSize: "var(--text-small)", marginTop: "var(--space-2)" }}>{d.description}</p>
              <div className="desk-areas">
                {d.areas.slice(0, 4).join(" · ")}
                {d.areas.length > 4 ? " ..." : ""}
              </div>
              {d.key_vendors && (
                <div className="desk-areas" style={{ marginTop: "var(--space-2)" }}>
                  <strong>Tracked vendors:</strong> {d.key_vendors.slice(0, 6).join(", ")}, and more
                </div>
              )}
              <div className="btn-group">
                <button className="btn btn-outline" onClick={() => runMonthly(d)}>
                  Run Monthly Report
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
