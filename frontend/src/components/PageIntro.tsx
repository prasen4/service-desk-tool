import { useState } from "react";

const STORAGE_PREFIX = "techdesk:intro:";

function readDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/**
 * Small dismissible "what is this page for" info box. Shown by default the
 * first time a visitor lands on a page; dismissing it is remembered per
 * browser (localStorage) so it doesn't nag returning users. A small "?"
 * button stays behind so anyone can bring the explanation back on demand.
 */
export default function PageIntro({ id, children }: { id: string; children: React.ReactNode }) {
  const storageKey = STORAGE_PREFIX + id;
  const [dismissed, setDismissed] = useState(() => readDismissed(storageKey));

  if (dismissed) {
    return (
      <button
        type="button"
        className="page-intro-reopen"
        onClick={() => setDismissed(false)}
        title="Show what this page is for"
        aria-label="Show what this page is for"
      >
        ?
      </button>
    );
  }

  function dismiss() {
    try {
      localStorage.setItem(storageKey, "1");
    } catch {
      /* localStorage unavailable — dismiss for this session only */
    }
    setDismissed(true);
  }

  return (
    <div className="page-intro">
      <span className="page-intro-icon">i</span>
      <div className="page-intro-text">{children}</div>
      <button type="button" className="page-intro-close" onClick={dismiss} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}
