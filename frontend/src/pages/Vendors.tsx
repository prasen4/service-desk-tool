import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Desk, type VendorSummary, type VendorUpdatesResponse } from "../api";
import { formatDate } from "../utils";

export default function Vendors() {
  const [vendors, setVendors] = useState<VendorSummary[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<VendorUpdatesResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [desks, setDesks] = useState<Desk[]>([]);
  const [showAddVendor, setShowAddVendor] = useState(false);
  const [newVendorName, setNewVendorName] = useState("");
  const [newVendorDesk, setNewVendorDesk] = useState("");
  const [addingVendor, setAddingVendor] = useState(false);
  const [addVendorError, setAddVendorError] = useState<string | null>(null);
  const [addVendorSuccess, setAddVendorSuccess] = useState<string | null>(null);

  function loadVendors() {
    return api
      .get<{ vendors: VendorSummary[]; total: number }>("/api/vendors?limit=500")
      .then((d) => setVendors(d.vendors.filter((v) => v.update_count > 0 || v.is_tracked)));
  }

  useEffect(() => {
    loadVendors().finally(() => setLoading(false));
    api
      .get<{ desks: Desk[] }>("/api/desks")
      .then((d) => {
        setDesks(d.desks);
        if (d.desks.length) setNewVendorDesk(d.desks[0].id);
      })
      .catch(() => {});
  }, []);

  const filtered = useMemo(
    () => vendors.filter((v) => v.name.toLowerCase().includes(search.toLowerCase())),
    [vendors, search]
  );

  useEffect(() => {
    if (!selected) return;
    setDetailLoading(true);
    setDetailError(null);
    api
      .get<VendorUpdatesResponse>(`/api/vendors/${encodeURIComponent(selected)}/updates?limit=100`)
      .then(setDetail)
      .catch((e) => setDetailError(e.message))
      .finally(() => setDetailLoading(false));
  }, [selected]);

  async function submitNewVendor(e: React.FormEvent) {
    e.preventDefault();
    if (!newVendorName.trim() || !newVendorDesk) return;
    setAddingVendor(true);
    setAddVendorError(null);
    setAddVendorSuccess(null);
    try {
      await api.post(`/api/desks/${encodeURIComponent(newVendorDesk)}/vendors`, { vendor: newVendorName.trim() });
      const deskName = desks.find((d) => d.id === newVendorDesk)?.name || newVendorDesk;
      setAddVendorSuccess(
        `"${newVendorName.trim()}" is now tracked on ${deskName} — it will automatically appear in Vendor News, research runs, and reports.`
      );
      setNewVendorName("");
      await loadVendors();
    } catch (e: any) {
      setAddVendorError(e.message || "Failed to add vendor");
    } finally {
      setAddingVendor(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-3)" }}>
        <div>
          <h1>Vendor News</h1>
          <p className="subtitle">
            Running feed of curated updates by vendor — click a vendor to see latest news tagged by tech desk
          </p>
        </div>
        <button className="btn btn-outline btn-sm" onClick={() => setShowAddVendor((v) => !v)}>
          {showAddVendor ? "Cancel" : "+ Add Vendor"}
        </button>
      </div>

      {showAddVendor && (
        <div className="panel" style={{ marginBottom: "var(--space-4)" }}>
          <h2>Add a Vendor</h2>
          <p className="sub">
            Adding a vendor tracks it on a tech desk — it will automatically propagate to research (vendor-targeted
            search queries), Vendor News, and future reports. No restart required.
          </p>
          <form onSubmit={submitNewVendor}>
            <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
              <div className="form-group" style={{ minWidth: 220, flex: 1 }}>
                <label>Vendor name</label>
                <input
                  type="text"
                  placeholder="e.g. Snowflake"
                  value={newVendorName}
                  onChange={(e) => setNewVendorName(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ minWidth: 220 }}>
                <label>Tech desk</label>
                <select value={newVendorDesk} onChange={(e) => setNewVendorDesk(e.target.value)}>
                  {desks.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
              <button type="submit" className="btn btn-primary" disabled={addingVendor || !newVendorName.trim()}>
                {addingVendor ? "Adding..." : "Add Vendor"}
              </button>
            </div>
          </form>
          {addVendorError && <p className="error-text">{addVendorError}</p>}
          {addVendorSuccess && <p className="success-text">{addVendorSuccess}</p>}
        </div>
      )}

      <div className="form-group" style={{ maxWidth: 320, marginBottom: "var(--space-4)" }}>
        <label>Filter vendors</label>
        <input
          type="text"
          placeholder="Search vendors..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="vendor-layout">
        <div className="vendor-list">
          {loading ? (
            <div className="empty">Loading vendors...</div>
          ) : !filtered.length ? (
            <div className="empty">No vendors match. Run research to collect updates.</div>
          ) : (
            filtered.map((v) => (
              <div
                key={v.name}
                className={"vendor-list-item" + (selected === v.name ? " active" : "")}
                onClick={() => setSelected(v.name)}
              >
                <div>
                  <div className="name">{v.name}</div>
                  <div className="meta">
                    {v.latest_at ? `Latest: ${formatDate(v.latest_at)}` : "No updates yet"}
                    {v.tracked_desks?.length ? ` · ${v.tracked_desks.map((d) => d.name).join(", ")}` : ""}
                  </div>
                </div>
                <span className="vendor-count">{v.update_count}</span>
              </div>
            ))
          )}
        </div>
        <div className="vendor-detail">
          {!selected ? (
            <div className="empty">Select a vendor to view their news feed</div>
          ) : detailLoading ? (
            <div className="empty">Loading...</div>
          ) : detailError ? (
            <div className="empty">Could not load updates: {detailError}</div>
          ) : detail ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-3)" }}>
                <h2>{detail.vendor}</h2>
                <Link className="btn btn-outline btn-sm" to={`/vendors/${encodeURIComponent(detail.vendor)}`}>
                  Open Profile →
                </Link>
              </div>
              <div className="sub">
                {detail.update_count} update{detail.update_count === 1 ? "" : "s"} · Tracked on:{" "}
                {detail.tracked_desks?.length ? (
                  detail.tracked_desks.map((d) => (
                    <span className="badge badge-desk" key={d.id} style={{ marginRight: 4 }}>
                      {d.name}
                    </span>
                  ))
                ) : (
                  <span className="badge badge-untracked">ad hoc</span>
                )}
              </div>
              {!detail.updates.length ? (
                <div className="empty">No updates for this vendor yet.</div>
              ) : (
                detail.updates.map((u, i) => (
                  <div className="news-item" key={i}>
                    <h4>{u.title}</h4>
                    <div className="news-meta">
                      <span className="badge badge-desk">{u.desk_name}</span>
                      <span>{formatDate(u.published_date || u.sort_at)}</span>
                      <span className={`badge badge-${u.relevance}`}>{u.relevance}</span>
                    </div>
                    <p style={{ fontSize: "var(--text-small)", marginBottom: "var(--space-2)" }}>{u.summary}</p>
                    <a className="link" href={u.source_url} target="_blank" rel="noreferrer">
                      {u.source_name || "Source"}
                    </a>
                  </div>
                ))
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
