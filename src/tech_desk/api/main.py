from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from tech_desk import __version__
from tech_desk.api.jobs import job_manager
from tech_desk.api.services import run_pipeline_job, run_report_job, run_research_job
from tech_desk.config import ReportPeriod, get_settings, load_desk_config, resolve_desks
from tech_desk.database import (
    AppConfigORM,
    ReportORM,
    ResearchRunORM,
    UpdateORM,
    all_token_samples,
    get_db_session,
    get_engine,
    get_token_sample,
    init_db,
)
from tech_desk.llm import LLMClient
from tech_desk.logging_config import setup_logging
from tech_desk.pricing import PROVIDERS, estimate_cost, get_catalog, provider_for_model
from tech_desk.scheduler import TechDeskScheduler
from tech_desk.vendors import (
    build_vendor_registry,
    desk_lookup,
    get_vendor_updates,
    list_vendor_summaries,
    resolve_canonical_vendor,
    serialize_update,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
_scheduler: TechDeskScheduler | None = None


class ConfigureRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    skip_validation: bool = False


class CostEstimateRequest(BaseModel):
    model: str
    horizon: ReportPeriod = "daily"
    desk_count: int | None = Field(default=None, ge=1, le=100)
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)


class RunResearchRequest(BaseModel):
    period: ReportPeriod = "daily"
    desk_ids: list[str] | None = Field(default=None)
    async_mode: bool = Field(default=True, description="Run in background and return job_id")


class GenerateReportRequest(BaseModel):
    period: ReportPeriod = "monthly"
    desk_ids: list[str] | None = Field(default=None)
    async_mode: bool = Field(default=True)


class FullPipelineRequest(BaseModel):
    period: ReportPeriod = "monthly"
    desk_ids: list[str] | None = Field(default=None)
    async_mode: bool = Field(default=True)


def _require_api_key() -> None:
    if not get_settings().openai_api_key:
        raise HTTPException(status_code=400, detail="API key not configured. POST /api/configure first.")


def _resolve_desk_keys(desk_ids: list[str] | None) -> list[str] | None:
    if not desk_ids:
        return None
    try:
        resolve_desks(desk_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return desk_ids


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    job_manager.start()
    global _scheduler
    settings = get_settings()
    if settings.scheduler_enabled:
        _scheduler = TechDeskScheduler()
        _scheduler.start()
        logger.info("Automated scheduler enabled")
    logger.info("Tech Desk API v%s started (env=%s)", __version__, settings.env)
    yield
    if _scheduler:
        _scheduler.stop()
    job_manager.shutdown()
    from tech_desk.research.images import close_http_client
    close_http_client()
    logger.info("Tech Desk API shutdown")


app = FastAPI(
    title="Cotiviti Tech Desk",
    description="Automated Gen AI research, aggregation, and stakeholder reporting",
    version=__version__,
    lifespan=lifespan,
)

settings = get_settings()
# The CORS spec forbids credentialed requests with a wildcard origin, and
# browsers reject that combination — only allow credentials for explicit origins.
_cors_origins = settings.cors_origin_list
_allow_credentials = _cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    detail = str(exc) if not get_settings().is_production else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail})


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    if not request.url.path.startswith("/static"):
        logger.debug("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code, elapsed)
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    dashboard_path = STATIC_DIR / "index.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Cotiviti Tech Desk</h1><p>Visit /docs for API documentation.</p>")


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.env,
        "api_key_configured": bool(settings.openai_api_key),
        "provider": settings.llm_provider,
        "model": settings.openai_model,
        "scheduler_enabled": settings.scheduler_enabled,
    }


@app.get("/api/ready")
async def ready():
    checks: dict[str, Any] = {}
    try:
        t0 = time.perf_counter()
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": str(exc)}

    settings = get_settings()
    data_dir = settings.tech_desk_data_dir
    checks["disk_writable"] = {"ok": data_dir.exists() and data_dir.is_dir()}
    checks["api_key_configured"] = {"ok": bool(settings.openai_api_key)}

    all_ok = all(c.get("ok", False) for c in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@app.get("/api/diagnostics")
async def diagnostics():
    """Admin connectivity check — disabled in production by default."""
    settings = get_settings()
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Diagnostics disabled in production")

    _require_api_key()
    llm = LLMClient()
    try:
        validation = llm.validate_api_key()
        return {"ok": validation.ok, "message": validation.message, "model": settings.openai_model}
    finally:
        llm.close()


@app.get("/api/desks")
async def list_desks():
    config = load_desk_config()
    branding = config.get("branding", {})
    return {
        "desks": config.get("desks", []),
        "organization": config.get("organization"),
        "branding": branding,
    }


@app.get("/api/models")
async def list_models():
    """Provider + model catalog with pricing, plus current selection and desk count."""
    settings = get_settings()
    desk_count = len(load_desk_config().get("desks", []))

    return {
        **get_catalog(),
        "current": {
            "provider": settings.llm_provider,
            "model": settings.openai_model,
            "base_url": settings.openai_base_url,
            "configured": bool(settings.openai_api_key),
        },
        "desk_count": desk_count,
        "measured": all_token_samples(),
    }


@app.post("/api/cost-estimate")
async def cost_estimate(req: CostEstimateRequest):
    desk_count = req.desk_count or len(load_desk_config().get("desks", [])) or 1
    sample = get_token_sample(req.horizon)
    in_per = sample["input_per_desk"] if sample else None
    out_per = sample["output_per_desk"] if sample else None
    source = f"measured ({sample['samples']} run{'s' if sample['samples'] != 1 else ''})" if sample else "modeled"
    return estimate_cost(
        req.model,
        req.horizon,
        desk_count,
        input_price=req.input_price,
        output_price=req.output_price,
        input_tokens_per_desk=in_per,
        output_tokens_per_desk=out_per,
        token_source=source,
    )


@app.post("/api/configure")
async def configure(req: ConfigureRequest, session: Session = Depends(get_db_session)):
    api_key = req.api_key.strip()
    model = (req.model or "gpt-4o").strip()

    provider = (req.provider or "").strip() or provider_for_model(model) or "openai"
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'.")

    default_base = PROVIDERS[provider]["base_url"]
    base_url = (req.base_url or default_base or "https://api.openai.com/v1").strip().rstrip("/")

    llm = LLMClient(api_key=api_key, base_url=base_url, model=model, provider=provider)
    try:
        if not req.skip_validation:
            result = llm.validate_api_key()
            if not result.ok:
                raise HTTPException(status_code=400, detail=result.message)
    finally:
        llm.close()

    env_path = Path.cwd() / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updates = {
        "LLM_PROVIDER": provider,
        "OPENAI_API_KEY": api_key,
        "OPENAI_BASE_URL": base_url,
        "OPENAI_MODEL": model,
    }
    existing_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = line.split("=")[0] if "=" in line else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            existing_keys.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    get_settings.cache_clear()
    settings = get_settings()

    session.merge(AppConfigORM(key="api_key_set", value="true"))
    session.merge(AppConfigORM(key="model", value=settings.openai_model))
    session.merge(AppConfigORM(key="provider", value=settings.llm_provider))
    return {"status": "configured", "provider": settings.llm_provider, "model": settings.openai_model}


@app.get("/api/jobs")
async def list_jobs(limit: int = 20):
    return {"jobs": [j.to_dict() for j in job_manager.list_recent(limit=min(limit, 50))]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post("/api/research/run")
async def run_research(req: RunResearchRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "research",
            run_research_job,
            period=req.period,
            desk_keys=desk_keys,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_research_job(period=req.period, desk_keys=desk_keys)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/reports/generate")
async def generate_report(req: GenerateReportRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "report",
            run_report_job,
            period=req.period,
            desk_keys=desk_keys,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_report_job(period=req.period, desk_keys=desk_keys)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/run")
async def run_full_pipeline(req: FullPipelineRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "pipeline",
            run_pipeline_job,
            period=req.period,
            desk_keys=desk_keys,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_pipeline_job(period=req.period, desk_keys=desk_keys)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/vendors")
async def list_vendors(session: Session = Depends(get_db_session)):
    """All tracked vendors with update counts, sorted by latest activity."""
    return {"vendors": list_vendor_summaries(session)}


@app.get("/api/vendors/{vendor_name}/updates")
async def vendor_updates(
    vendor_name: str,
    limit: int = 100,
    session: Session = Depends(get_db_session),
):
    """Chronological news feed for a single vendor, tagged by tech desk."""
    data = get_vendor_updates(session, vendor_name, limit=min(limit, 200))
    if data is None:
        raise HTTPException(status_code=404, detail=f"No updates found for vendor: {vendor_name}")
    return data


@app.get("/api/updates")
async def list_updates(
    desk_id: str | None = None,
    vendor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    limit = min(limit, 200)
    desk_map = desk_lookup()
    q = session.query(UpdateORM)
    if desk_id:
        q = q.filter(UpdateORM.desk_id == desk_id)
    if vendor:
        tracked = list(build_vendor_registry().keys())
        canon = resolve_canonical_vendor(vendor, tracked) or vendor
        q = q.filter(UpdateORM.vendor.ilike(f"%{canon}%"))
    rows = q.all()
    rows.sort(
        key=lambda u: u.published_date or u.discovered_at,
        reverse=True,
    )
    updates = rows[:limit]
    return {"updates": [serialize_update(u, desk_map) for u in updates]}


@app.get("/api/research/runs")
async def list_research_runs(limit: int = 20, session: Session = Depends(get_db_session)):
    runs = session.query(ResearchRunORM).order_by(ResearchRunORM.started_at.desc()).limit(min(limit, 100)).all()
    return {
        "runs": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "status": r.status,
                "period": r.period,
                "desks_processed": r.desks_processed,
                "updates_found": r.updates_found,
                "error_message": r.error_message,
            }
            for r in runs
        ]
    }


@app.get("/api/reports")
async def list_reports(limit: int = 20, session: Session = Depends(get_db_session)):
    reports = session.query(ReportORM).order_by(ReportORM.generated_at.desc()).limit(min(limit, 100)).all()
    return {
        "reports": [
            {
                "id": r.id,
                "period": r.period,
                "title": r.title,
                "generated_at": r.generated_at.isoformat(),
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "has_html": bool(r.html_path),
                "has_pdf": bool(r.pdf_path),
            }
            for r in reports
        ]
    }


@app.get("/api/reports/{report_id}")
async def get_report(report_id: int, session: Session = Depends(get_db_session)):
    report = session.query(ReportORM).filter_by(id=report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "id": report.id,
        "period": report.period,
        "title": report.title,
        "generated_at": report.generated_at.isoformat(),
        "executive_summary": report.executive_summary,
        "content": json.loads(report.content_json),
        "html_path": report.html_path,
        "markdown_path": report.markdown_path,
        "pdf_path": report.pdf_path,
    }


@app.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(report_id: int, session: Session = Depends(get_db_session)):
    report = session.query(ReportORM).filter_by(id=report_id).first()
    if not report or not report.html_path:
        raise HTTPException(status_code=404, detail="Report HTML not found")
    path = Path(report.html_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report file missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/api/reports/{report_id}/download/{fmt}")
async def download_report(report_id: int, fmt: str, session: Session = Depends(get_db_session)):
    report = session.query(ReportORM).filter_by(id=report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    path_map = {"html": report.html_path, "markdown": report.markdown_path, "md": report.markdown_path, "pdf": report.pdf_path}
    path_str = path_map.get(fmt)
    if not path_str:
        raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")

    path = Path(path_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    media = {"html": "text/html", "markdown": "text/markdown", "md": "text/markdown", "pdf": "application/pdf"}
    return FileResponse(path, media_type=media.get(fmt, "application/octet-stream"), filename=path.name)


def create_app() -> FastAPI:
    return app
