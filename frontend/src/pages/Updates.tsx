import { useEffect, useState } from "react";
import { api, type Desk, type UpdateItem } from "../api";
import { formatDate } from "../utils";

export default function Updates() {
  const [updates, setUpdates] = useState<UpdateItem[]>([]);
  const [desks, setDesks] = useState<Desk[]>([]);
  const [desk, setDesk] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<{ desks: Desk[] }>("/api/desks").then((d) => setDesks(d.desks));
  }, []);

  useEffect(() => {
    setLoading(true);
    const qs = new URLSearchParams({ limit: "100" });
    if (desk) qs.set("desk_id", desk);
    api
      .get<{ updates: UpdateItem[] }>(`/api/updates?${qs.toString()}`)
      .then((d) => setUpdates(d.updates))
      .finally(() => setLoading(false));
  }, [desk]);

  return (
    <div>
      <h1>Updates Feed</h1>
      <p className="subtitle">Curated technology updates with source links and dates</p>
      <div className="form-group" style={{ maxWidth: 300, marginBottom: "var(--space-4)" }}>
        <label>Filter by Desk</label>
        <select value={desk} onChange={(e) => setDesk(e.target.value)}>
          <option value="">All Desks</option>
          {desks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} — {d.name}
            </option>
          ))}
        </select>
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Desk</th>
              <th>Date</th>
              <th>Relevance</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="empty">
                  Loading...
                </td>
              </tr>
            ) : !updates.length ? (
              <tr>
                <td colSpan={5} className="empty">
                  No updates yet. Run research first.
                </td>
              </tr>
            ) : (
              updates.map((u, i) => (
                <tr key={i}>
                  <td>
                    <strong>{u.title}</strong>
                    <br />
                    <small style={{ color: "var(--color-muted)" }}>
                      {u.vendor ? `${u.vendor} · ` : ""}
                      {u.summary.substring(0, 100)}...
                    </small>
                  </td>
                  <td>
                    <span className="badge badge-desk">{u.desk_code || u.desk_id}</span>
                  </td>
                  <td>{u.published_date ? formatDate(u.published_date) : formatDate(u.discovered_at)}</td>
                  <td>
                    <span className={`badge badge-${u.relevance}`}>{u.relevance}</span>
                  </td>
                  <td>
                    <a className="link" href={u.source_url} target="_blank" rel="noreferrer">
                      {u.source_name || "Source"}
                    </a>
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
