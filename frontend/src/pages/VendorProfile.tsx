import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type VendorProfile as VendorProfileType, type VendorStatusOption, type PositionPaper } from "../api";
import { formatDate, formatDateTime } from "../utils";
import { useJobActivity } from "../hooks/useJobActivity";

type Tab = "notes" | "status" | "news" | "position-paper";

export default function VendorProfile() {
  const { vendorName = "" } = useParams();
  const { runJob } = useJobActivity();
  const [profile, setProfile] = useState<VendorProfileType | null>(null);
  const [statuses, setStatuses] = useState<VendorStatusOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("notes");

  const [noteBody, setNoteBody] = useState("");
  const [noteAuthor, setNoteAuthor] = useState("");
  const [noteFile, setNoteFile] = useState<File | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);

  const [pendingStatus, setPendingStatus] = useState<VendorStatusOption | null>(null);
  const [statusNote, setStatusNote] = useState("");
  const [savingStatus, setSavingStatus] = useState(false);

  const [positionPapers, setPositionPapers] = useState<PositionPaper[]>([]);
  const [ppLoading, setPpLoading] = useState(false);
  const [ppError, setPpError] = useState<string | null>(null);
  const [showPromptModal, setShowPromptModal] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, s] = await Promise.all([
        api.get<VendorProfileType>(`/api/vendors/${encodeURIComponent(vendorName)}/profile?news_limit=100`),
        statuses.length ? Promise.resolve({ statuses }) : api.get<{ statuses: VendorStatusOption[] }>("/api/vendors/statuses"),
      ]);
      setProfile(p);
      setStatuses(s.statuses);
    } catch (e: any) {
      setError(e.message || "Vendor not found");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendorName]);

  useEffect(() => {
    load();
  }, [load]);

  const loadPositionPapers = useCallback(async () => {
    setPpLoading(true);
    setPpError(null);
    try {
      const res = await api.get<{ position_papers: PositionPaper[] }>(
        `/api/vendors/${encodeURIComponent(vendorName)}/position-papers`
      );
      setPositionPapers(res.position_papers);
    } catch (e: any) {
      setPpError(e.message || "Failed to load position papers");
    } finally {
      setPpLoading(false);
    }
  }, [vendorName]);

  useEffect(() => {
    if (tab === "position-paper") loadPositionPapers();
  }, [tab, loadPositionPapers]);

  async function generatePositionPaper() {
    setGenerating(true);
    setPpError(null);
    try {
      await runJob(
        `/api/vendors/${encodeURIComponent(vendorName)}/position-paper`,
        { custom_prompt: customPrompt },
        { start: "Generating position paper...", running: "Generating position paper", wait: "Starting..." }
      );
      setShowPromptModal(false);
      setCustomPrompt("");
      loadPositionPapers();
    } catch (e: any) {
      setPpError(e.message || "Position paper generation failed");
    } finally {
      setGenerating(false);
    }
  }

  async function confirmStatusChange() {
    if (!pendingStatus) return;
    setSavingStatus(true);
    try {
      await api.post(`/api/vendors/${encodeURIComponent(vendorName)}/status`, {
        status: pendingStatus.value,
        note: statusNote,
        changed_by: "",
      });
      setPendingStatus(null);
      setStatusNote("");
      load();
    } catch (e: any) {
      alert("Error: " + e.message);
    } finally {
      setSavingStatus(false);
    }
  }

  async function submitNote(e: React.FormEvent) {
    e.preventDefault();
    if (!noteBody.trim() && !noteFile) {
      setNoteError("A note must include text or a file attachment.");
      return;
    }
    setSavingNote(true);
    setNoteError(null);
    try {
      const form = new FormData();
      form.set("body", noteBody);
      form.set("author", noteAuthor);
      if (noteFile) form.set("file", noteFile);
      await api.postForm(`/api/vendors/${encodeURIComponent(vendorName)}/notes`, form);
      setNoteBody("");
      setNoteFile(null);
      load();
    } catch (e: any) {
      setNoteError(e.message || "Failed to save note");
    } finally {
      setSavingNote(false);
    }
  }

  async function deleteNote(noteId: number) {
    if (!confirm("Delete this note and any attachment?")) return;
    try {
      await api.delete(`/api/vendors/${encodeURIComponent(vendorName)}/notes/${noteId}`);
      load();
    } catch (e: any) {
      alert("Error: " + e.message);
    }
  }

  async function deleteAttachment(attachmentId: number) {
    if (!confirm("Delete this attachment?")) return;
    try {
      await api.delete(`/api/vendors/${encodeURIComponent(vendorName)}/attachments/${attachmentId}`);
      load();
    } catch (e: any) {
      alert("Error: " + e.message);
    }
  }

  if (loading) return <div className="empty">Loading vendor profile...</div>;
  if (error || !profile) {
    return (
      <div>
        <Link className="link" to="/vendors">
          ← Back to Vendor News
        </Link>
        <div className="empty">{error || "Vendor not found."}</div>
      </div>
    );
  }

  return (
    <div>
      <Link className="link" to="/vendors">
        ← Back to Vendor News
      </Link>
      <div className="profile-header">
        <div>
          <h1 style={{ marginBottom: "var(--space-2)" }}>{profile.name}</h1>
          <p className="subtitle" style={{ marginBottom: 0 }}>
            {profile.owner ? `Owner: ${profile.owner} · ` : ""}
            {profile.is_tracked && profile.tracked_desks.length
              ? `Tracked on: ${profile.tracked_desks.map((d) => d.name).join(", ")}`
              : "Ad hoc vendor (not on a tracked desk list)"}
          </p>
        </div>
        <span className="badge badge-status">{profile.status_label || "No reported status yet"}</span>
      </div>

      <div className="panel">
        <h2>Status</h2>
        <div className="status-stepper">
          {statuses
            .filter((s) => !s.is_branch)
            .sort((a, b) => (a.stage_order || 0) - (b.stage_order || 0))
            .map((s) => {
              const currentOrder = statuses.find((x) => x.value === profile.status)?.stage_order;
              const isCurrent = profile.status === s.value;
              const isPast = currentOrder != null && s.stage_order != null && s.stage_order < currentOrder;
              return (
                <button
                  key={s.value}
                  className={
                    "status-step" + (isCurrent ? " current" : "") + (isPast ? " past" : "")
                  }
                  onClick={() => {
                    setStatusNote("");
                    setPendingStatus(s);
                  }}
                >
                  <span className="status-step-order">{s.stage_order}</span>
                  {s.label}
                </button>
              );
            })}
        </div>
        <div className="status-branch-row">
          <span className="status-branch-label">Other outcomes:</span>
          {statuses
            .filter((s) => s.is_branch)
            .map((s) => (
              <button
                key={s.value}
                className={"status-pill" + (profile.status === s.value ? " current" : "")}
                onClick={() => {
                  setStatusNote("");
                  setPendingStatus(s);
                }}
              >
                {s.label}
              </button>
            ))}
        </div>
      </div>

      {pendingStatus && (
        <div className="modal-overlay" onClick={() => !savingStatus && setPendingStatus(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>Move to "{pendingStatus.label}"</h3>
            <div className="form-group">
              <label>Note (optional)</label>
              <textarea
                value={statusNote}
                onChange={(e) => setStatusNote(e.target.value)}
                placeholder="Why is this changing?"
                autoFocus
              />
            </div>
            <div className="modal-actions">
              <button className="btn btn-outline" disabled={savingStatus} onClick={() => setPendingStatus(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={savingStatus} onClick={confirmStatusChange}>
                {savingStatus ? "Saving..." : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="tabs">
        <div className={"tab" + (tab === "notes" ? " active" : "")} onClick={() => setTab("notes")}>
          Notes ({profile.notes.length})
        </div>
        <div className={"tab" + (tab === "status" ? " active" : "")} onClick={() => setTab("status")}>
          Status History ({profile.status_history.length})
        </div>
        <div className={"tab" + (tab === "news" ? " active" : "")} onClick={() => setTab("news")}>
          News ({profile.news_count})
        </div>
        <div
          className={"tab" + (tab === "position-paper" ? " active" : "")}
          onClick={() => setTab("position-paper")}
        >
          Position Paper
        </div>
      </div>

      {tab === "notes" && (
        <div className="panel">
          <h2>Add a Note</h2>
          <form onSubmit={submitNote}>
            {noteError && <p className="error-text" style={{ marginBottom: "var(--space-4)" }}>{noteError}</p>}
            <div className="form-group">
              <label>Note</label>
              <textarea value={noteBody} onChange={(e) => setNoteBody(e.target.value)} placeholder="What happened?" />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Author</label>
                <input type="text" value={noteAuthor} onChange={(e) => setNoteAuthor(e.target.value)} placeholder="Your name" />
              </div>
              <div className="form-group">
                <label>Attachment (optional)</label>
                <div className="file-input-row">
                  <input
                    type="file"
                    onChange={(e) => setNoteFile(e.target.files?.[0] || null)}
                  />
                </div>
              </div>
            </div>
            <button className="btn btn-primary" type="submit" disabled={savingNote}>
              {savingNote ? "Saving..." : "Add Note"}
            </button>
          </form>
        </div>
      )}

      {tab === "notes" && (
        <div>
          {!profile.notes.length ? (
            <div className="empty">No notes yet. Add the first one above.</div>
          ) : (
            profile.notes.map((n) => (
              <div className="note-card" key={n.id}>
                <div className="note-meta">
                  <span>
                    {n.author || "Anonymous"} · {formatDateTime(n.created_at)}
                  </span>
                  <button className="link" onClick={() => deleteNote(n.id)}>
                    Delete
                  </button>
                </div>
                {n.body && <div className="note-body">{n.body}</div>}
                {!!n.attachments.length && (
                  <div className="note-attachments">
                    {n.attachments.map((a) => (
                      <span key={a.id} className="attachment-chip">
                        <a
                          href={`/api/vendors/${encodeURIComponent(vendorName)}/attachments/${a.id}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: "inherit", textDecoration: "none" }}
                        >
                          📎 {a.filename}
                        </a>
                        <button
                          className="link"
                          style={{ marginLeft: 6 }}
                          onClick={() => deleteAttachment(a.id)}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {tab === "status" && (
        <div className="panel">
          {!profile.status_history.length ? (
            <div className="empty">No status changes recorded yet.</div>
          ) : (
            <div className="timeline">
              {profile.status_history.map((e) => (
                <div className="timeline-item" key={e.id}>
                  <div>
                    <strong>{e.status_label}</strong>
                    {e.changed_by ? ` · ${e.changed_by}` : ""}
                    {e.duration_label ? <span className="badge badge-desk" style={{ marginLeft: 8 }}>{e.duration_label}</span> : null}
                  </div>
                  <div className="ts">{formatDateTime(e.created_at)}</div>
                  {e.note && <div style={{ marginTop: "var(--space-2)" }}>{e.note}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "news" && (
        <div>
          {!profile.news.length ? (
            <div className="empty">No news updates found for this vendor yet.</div>
          ) : (
            profile.news.map((u, i) => (
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
        </div>
      )}

      {tab === "position-paper" && (
        <div>
          <div className="panel">
            <h2>Generate Position Paper</h2>
            <p className="subtitle">
              Combines CRM notes, attachments, and prior research on {profile.name} with a fresh web search, then
              drafts a full position paper (.docx) via a two-stage AI pipeline.
            </p>
            <button className="btn btn-primary" disabled={generating} onClick={() => setShowPromptModal(true)}>
              {generating ? "Generating..." : "Generate Position Paper"}
            </button>
          </div>

          {ppError && <p className="error-text">{ppError}</p>}

          <div className="panel">
            <h2>History</h2>
            {ppLoading ? (
              <div className="empty">Loading...</div>
            ) : !positionPapers.length ? (
              <div className="empty">No position papers generated yet.</div>
            ) : (
              <div className="timeline">
                {positionPapers.map((p) => (
                  <div className="timeline-item" key={p.id}>
                    <div>
                      <strong>{p.status === "completed" ? "Completed" : p.status === "failed" ? "Failed" : "Running"}</strong>
                      {p.custom_prompt ? ` · custom guidance provided` : ""}
                    </div>
                    <div className="ts">{formatDateTime(p.generated_at || p.created_at)}</div>
                    {p.error_message && <div className="error-text" style={{ marginTop: "var(--space-2)" }}>{p.error_message}</div>}
                    {p.status === "completed" && p.docx_path && (
                      <div style={{ marginTop: "var(--space-2)" }}>
                        <a className="link" href={`/api/vendors/position-papers/${p.id}/download`}>
                          Download .docx
                        </a>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showPromptModal && (
        <div className="modal-overlay" onClick={() => !generating && setShowPromptModal(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>Generate Position Paper for {profile.name}</h3>
            <div className="form-group">
              <label>Custom instructions (optional)</label>
              <textarea
                value={customPrompt}
                onChange={(e) => setCustomPrompt(e.target.value)}
                placeholder="e.g. Focus on payment integrity use cases and compare against Vendor X."
                autoFocus
              />
            </div>
            <div className="modal-actions">
              <button className="btn btn-outline" disabled={generating} onClick={() => setShowPromptModal(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={generating} onClick={generatePositionPaper}>
                {generating ? "Generating..." : "Generate"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

