import { useJobActivity } from "../hooks/useJobActivity";

export default function StatusBar() {
  const { statusBar } = useJobActivity();
  if (!statusBar) return null;

  return (
    <div className="status-bar">
      <div className="title">
        <span className="spinner" /> <span>{statusBar.title}</span>
      </div>
      <div className="msg">{statusBar.msg}</div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${statusBar.progress}%` }} />
      </div>
    </div>
  );
}
