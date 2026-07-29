# Tech Desk Intelligence Platform

**Automated Gen AI research, aggregation, and stakeholder reporting for Cotiviti.**

Replace manual Technology Desk workflows with a single API key and one-click automation. Tech Desk monitors all five Gen AI categories from the RedCell Technical Prospecting framework, performs deep web research, curates updates with LLM analysis, and generates presentation-ready monthly reports.

## What It Automates

| Manual Process | Automated By |
|---|---|
| Daily/weekly/monthly news tracking | Scheduled + on-demand web research |
| Logging dates and source links | Structured database with deduplication |
| Curating relevant updates per desk | LLM relevance filtering and summarization |
| Monthly stakeholder reports | AI-generated executive summaries, trends, recommendations |
| Priority desk focus (Models, ET, APPS) | 2x research depth on priority desks |
| Journal Club / Daily Demo prep | HTML, Markdown, and PDF exports |

## Tech Desks Covered

| Code | Desk | Priority |
|------|------|----------|
| **I** | Gen AI Infrastructure — cloud, compute, storage, network | |
| **M** | Gen AI Models — foundation models, hubs, hyperscalers | ⭐ |
| **ET** | Gen AI Engineering Tools — RAG, agents, deployment, TRiSM | ⭐ |
| **APPS** | Gen AI Applications — horizontal & vertical (BFSI, legal) | ⭐ |
| **HCLS** | HealthTech / Life Sciences — EHR, pharma, regulations | |

## Quick Start

### 1. Install

```bash
cd cotiviti-tool
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Configure (only an LLM API key required)

```bash
tech-desk init
# Prompts for your OpenAI API key (or compatible provider)
```

Or copy `.env.example` to `.env` and set `OPENAI_API_KEY`.

### 3. Run the Full Pipeline

```bash
tech-desk pipeline --period monthly
```

This single command:
1. Searches the web across all tech desk categories
2. Uses your LLM to filter, summarize, and score each update
3. Stores curated entries with dates and source links
4. Generates a comprehensive stakeholder report (HTML, Markdown, PDF)

### 4. Launch the Dashboard

```bash
tech-desk serve
```

Open **http://localhost:8080** for the web UI.

## Docker Deployment

```bash
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

docker compose up -d
```

The container binds to `127.0.0.1:8080`; run a reverse proxy (see below) for
external access.

## Production Deployment (EC2)

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a full walkthrough of hosting on a
single EC2 instance — a `systemd` service (`deploy/deploy.sh`,
`deploy/techdesk.service`), an nginx reverse proxy with TLS and optional basic
auth (`deploy/nginx.conf`), backups, and a security checklist.

> **Run one process.** Background jobs, the in-memory job registry behind the
> Activity view, and the scheduler all live in a single process. Scale
> vertically (a larger instance) rather than adding workers/replicas.

## CLI Commands

| Command | Description |
|---------|-------------|
| `tech-desk init` | Configure API key |
| `tech-desk pipeline --period monthly` | Full automation (research + report) |
| `tech-desk pipeline --desk APPS --period monthly` | Pipeline for Gen AI Applications only |
| `tech-desk report --desk applications` | Report for one desk (id, code, or name) |
| `tech-desk research --desk models --desk hcls` | Research for selected desks |
| `tech-desk research --period daily` | Run web research only |
| `tech-desk report --period monthly` | Generate report from existing data |
| `tech-desk serve` | Start web dashboard |
| `tech-desk status` | Show system status |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/configure` | POST | Set LLM API key |
| `/api/pipeline/run` | POST | One-click full automation |
| `/api/research/run` | POST | Run research collection |
| `/api/reports/generate` | POST | Generate report |
| `/api/updates` | GET | List curated updates |
| `/api/reports` | GET | List reports |
| `/api/reports/{id}/html` | GET | View report |
| `/api/reports/{id}/download/pdf` | GET | Download PDF |

Interactive docs at **http://localhost:8080/docs**.

## Report Output

Reports include:
- **Executive Summary** for leadership
- **Per-desk sections** with highlights and curated updates
- **Source links and dates** for every item
- **Trend analysis** and **vendor landscape** (monthly)
- **Actionable recommendations** for Cotiviti
- Export formats: **HTML**, **Markdown**, **PDF**

Reports are saved to `data/reports/{period}/`.

## Compatible LLM Providers

Works with any OpenAI-compatible API:
- OpenAI (`gpt-4o`, `gpt-4o-mini`)
- Azure OpenAI (set `OPENAI_BASE_URL`)
- Local models via LiteLLM, Ollama with OpenAI shim, etc.

## Configuration

Edit `config/tech_desks.yaml` to customize:
- Search queries per desk
- Focus areas and sub-areas
- Report depth settings
- Priority desk multipliers

Runtime configuration is environment-driven via `.env` (see `.env.example` for
every option and `DEPLOYMENT.md` for a production reference table).

## Development

```bash
make dev          # install with dev + test dependencies
make test         # run the test suite against an isolated data dir
make lint         # ruff checks
make format       # auto-fix lint issues
make serve        # run the dev server with autoreload
```

Tests never touch your real database or credentials — `tests/conftest.py` points
each run at a throwaway data directory and a dummy API key.

## Project Structure

```
src/tech_desk/
  api/            FastAPI app, routes, background job manager
  research/       Web search, LLM analysis, collection pipeline
  reports/        Report + vendor-intelligence generation
  export/         HTML / Markdown / PDF rendering
  config.py       Environment settings and desk resolution
  database.py     SQLAlchemy models and session management
  llm.py          Multi-provider LLM client (OpenAI-compatible + Anthropic)
  pricing.py      Provider/model catalog and cost estimation
  scheduler.py    Automated daily/weekly/monthly runs
config/           Tech desk definitions and branding
deploy/           systemd unit, nginx config, deploy script
tests/            Test suite (pytest)
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Web Search │────▶│  LLM Analyzer │────▶│  SQLite DB  │
│ (DuckDuckGo)│     │  (Your API Key)│     │  (Updates)  │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                    ┌──────────────┐     ┌─────────▼──────┐
                    │  Dashboard   │◀────│ Report Generator│
                    │  (FastAPI)   │     │  (LLM + Jinja)  │
                    └──────────────┘     └────────────────┘
```

## Scheduling

For unattended operation, the built-in scheduler runs:
- **Daily** pipeline at 06:00 UTC
- **Weekly** pipeline Mondays at 07:00 UTC
- **Monthly** pipeline on the 1st at 08:00 UTC

## Optional: SharePoint Integration

Install with SharePoint support:
```bash
pip install -e ".[sharepoint]"
```

Set `SHAREPOINT_*` variables in `.env` to auto-upload reports.

## License

Proprietary — Cotiviti internal use.
