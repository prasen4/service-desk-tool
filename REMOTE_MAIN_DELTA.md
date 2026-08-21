# Remote `main` Delta Summary

Snapshot of what landed on `origin/main` after the local baseline commit
`74f3941` (PostgreSQL support with SQLite fallback), through `dfabf43`.

Local was **13 commits behind** remote with no uncommitted local changes at the
time this note was written.

---

## What’s on remote that local did not have

- **React frontend** — Vite/React app replacing the old single HTML dashboard
- **Vendor profiles & CRM routes** — notes, attachments, status pipeline, position papers
- **Alembic migrations** — baseline + vendor profiles/jobs + position papers (incl. Postgres revision-id fix)
- **Position paper renderer** — `.docx` generation with Cotiviti branding assets
- **Azure OpenAI support** — provider + GPT-5.4 pricing + custom deployment-name cost matching
- **Search upgrades** — `SEARCH_BACKEND`, SearXNG, DDG retry/backoff, concurrent search + analysis
- **Newer model API support** — `max_completion_tokens` for GPT-5 family (+ race fix)
- **Rate limiting**
- **Deploy/diagnostics** — `tech-desk doctor`, Docker deploy script, config mount/ownership fixes, Dockerfile ordering for React build
- **UI polish** — sidebar emoji removal; logo aspect-ratio fix
- **Expanded tests** — diagnostics, search, vendors, plus broader API/config/core/LLM coverage

---

## Frontend & vendor-profile changes that look user-request / feedback based

These are the ones that read like product feedback or stakeholder asks (not pure
infra). Strongest signals first.

### Clear polish / feedback follow-ups (later commits)

- **Remove sidebar emoji icons** — nav labels only (Dashboard, Research, Reports, etc.); Settings no longer uses ⚙️ / ⚡ / 🔑 style icons
- **Fix stretched Cotiviti logo** in position papers — preserve native aspect ratio instead of forcing width×height (classic “logo looks squashed” feedback)
- **Azure cost projection for custom deployment names** — free-text Azure deployment names now resolve pricing via substring match against known model IDs (feedback pattern: “my deployment isn’t named exactly `gpt-4o` so cost shows wrong/blank”)
- **Azure-specific LLM Setup UX** — “Deployment Name”, Azure Endpoint, API version fields instead of a normal model dropdown

### Vendor News / Profiles (looks like stakeholder product requests)

- **Vendor News as a first-class page** with search/filter and desk-tagged update feed
- **“+ Add Vendor”** — add a vendor to a tech desk from the UI; auto-propagates into research queries, Vendor News, and reports without restart
- **Dedicated Vendor Profile page** (from Vendor News → “Open Profile”)
- **CRM-style status pipeline stepper**:
  - Identified → Outreach Sent → Meeting Scheduled → Proposal Received → POC In Progress → Evaluation → Contract Negotiation → Selected → Implementation
  - Branch outcomes: **Rejected**, **On Hold**
- **Status change confirmation modal** with optional “why is this changing?” note
- **Status history timeline** with duration-in-stage labels
- **Analyst notes** — text + optional author + optional file attachment; notes required to have text or a file
- **Attachment download/delete** on vendor notes
- **News tab on profile** — vendor’s curated updates in one place
- **Position Paper tab** — generate a `.docx` from CRM notes + attachments + research + fresh web search
- **Custom prompt modal** before generation (“focus on payment integrity / compare to Vendor X”)
- **Position paper history** with status + download link
- **Owner / tracked-desks display** on the profile header (“Tracked on …” vs ad hoc)

### Broader frontend structure that likely came from earlier product feedback

- **Multi-page React app** instead of one giant HTML page (Dashboard, Research, Reports, Updates Feed, Vendor News, Tech Desks, Activity, LLM Setup)
- **Settings subgroup** in the sidebar (Activity + LLM Setup collapsed under Settings)
- **Persistent Activity / job badge** carried into the React app (same need as the earlier “show job progress in the UI” request)
- **Dark/light theme toggle** preserved in the new sidebar

---

## Caveat

Not every vendor-CRM feature can be proven as a verbal ask vs a planned build —
most landed in one large commit. The ones that most clearly look like **user
feedback after use** are: **emoji removal**, **logo stretch fix**, and **Azure
custom deployment cost matching**. The vendor profile CRM (status pipeline,
notes/attachments, add-vendor, position papers) most clearly looks like
**stakeholder product requirements**.
