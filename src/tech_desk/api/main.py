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
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from tech_desk import __version__
from tech_desk.api.jobs import job_manager
from tech_desk.api.rate_limit import configure_limiter, pipeline_limiter, rate_limit
from tech_desk.api.services import run_pipeline_job, run_report_job, run_research_job
from tech_desk.api.vendor_routes import router as vendor_router
from tech_desk.config import ReportPeriod, add_vendor_to_desk, get_settings, load_desk_config, resolve_desks
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
WEB_DIST_DIR = Path(__file__).resolve().parent / "web" / "dist"
_scheduler: TechDeskScheduler | None = None



class ConfigureRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_version: str | None = None
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
    custom_instructions: str | None = Field(default=None, max_length=2000)


class GenerateReportRequest(BaseModel):
    period: ReportPeriod = "monthly"
    desk_ids: list[str] | None = Field(default=None)
    async_mode: bool = Field(default=True)
    custom_instructions: str | None = Field(default=None, max_length=2000)


class FullPipelineRequest(BaseModel):
    period: ReportPeriod = "monthly"
    desk_ids: list[str] | None = Field(default=None)
    async_mode: bool = Field(default=True)
    custom_instructions: str | None = Field(default=None, max_length=2000)


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
    logger.info(
        "Tech Desk API v%s started (env=%s, database=%s)",
        __version__,
        settings.env,
        settings.db_backend,
    )
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

if WEB_DIST_DIR.exists():
    # Built React frontend takes priority once `npm run build` has been run
    # (see frontend/README or Dockerfile for the build step).
    assets_dir = WEB_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")
elif STATIC_DIR.exists():
    # Legacy static dashboard — served until the frontend has been built.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(vendor_router)


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
    index = WEB_DIST_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    legacy = STATIC_DIR / "index.html"
    if legacy.exists():
        return HTMLResponse(legacy.read_text(encoding="utf-8"))
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
        "database": settings.db_backend,
        "scheduler_enabled": settings.scheduler_enabled,
    }


@app.get("/api/ready")
async def ready():
    checks: dict[str, Any] = {}
    settings = get_settings()
    try:
        t0 = time.perf_counter()
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {
            "ok": True,
            "backend": settings.db_backend,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    except Exception as exc:
        checks["database"] = {"ok": False, "backend": settings.db_backend, "error": str(exc)}

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


class AddVendorRequest(BaseModel):
    vendor: str = Field(..., min_length=1, max_length=128)


@app.post("/api/desks/{desk_id}/vendors", dependencies=[Depends(rate_limit(configure_limiter, "add-vendor"))])
async def add_desk_vendor(desk_id: str, req: AddVendorRequest):
    """Add a vendor to a desk's tracked list — automatically picked up by
    research (vendor-targeted search queries), Vendor News, and reports,
    since none of those read a cached copy of the desk config.
    """
    try:
        desk = add_vendor_to_desk(desk_id, req.vendor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"desk": desk.model_dump()}


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
            "api_version": settings.azure_openai_api_version,
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


@app.post("/api/configure", dependencies=[Depends(rate_limit(configure_limiter, "configure"))])
async def configure(req: ConfigureRequest, session: Session = Depends(get_db_session)):
    api_key = req.api_key.strip()
    model = (req.model or "gpt-4o").strip()

    provider = (req.provider or "").strip() or provider_for_model(model) or "openai"
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'.")

    if provider == "azure_openai" and not (req.base_url or "").strip():
        raise HTTPException(status_code=400, detail="Azure OpenAI requires your resource endpoint as the Base URL.")

    default_base = PROVIDERS[provider]["base_url"]
    base_url = (req.base_url or default_base or "https://api.openai.com/v1").strip().rstrip("/")
    api_version = (req.api_version or "").strip() or get_settings().azure_openai_api_version

    llm = LLMClient(api_key=api_key, base_url=base_url, model=model, provider=provider, api_version=api_version)
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
        "AZURE_OPENAI_API_VERSION": api_version,
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
async def list_jobs(limit: int = 20, offset: int = 0):
    jobs = job_manager.list_recent(limit=min(limit, 50) + offset)[offset:]
    return {"jobs": [j.to_dict() for j in jobs]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post("/api/research/run", dependencies=[Depends(rate_limit(pipeline_limiter, "research"))])
async def run_research(req: RunResearchRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "research",
            run_research_job,
            period=req.period,
            desk_keys=desk_keys,
            custom_instructions=req.custom_instructions,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_research_job(period=req.period, desk_keys=desk_keys, custom_instructions=req.custom_instructions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/reports/generate", dependencies=[Depends(rate_limit(pipeline_limiter, "report"))])
async def generate_report(req: GenerateReportRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "report",
            run_report_job,
            period=req.period,
            desk_keys=desk_keys,
            custom_instructions=req.custom_instructions,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_report_job(period=req.period, desk_keys=desk_keys, custom_instructions=req.custom_instructions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/run", dependencies=[Depends(rate_limit(pipeline_limiter, "pipeline"))])
async def run_full_pipeline(req: FullPipelineRequest):
    _require_api_key()
    desk_keys = _resolve_desk_keys(req.desk_ids)

    if req.async_mode:
        job_id = job_manager.submit(
            "pipeline",
            run_pipeline_job,
            period=req.period,
            desk_keys=desk_keys,
            custom_instructions=req.custom_instructions,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_pipeline_job(period=req.period, desk_keys=desk_keys, custom_instructions=req.custom_instructions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/vendors")
async def list_vendors(limit: int = 100, offset: int = 0, session: Session = Depends(get_db_session)):
    """All tracked vendors with update counts, sorted by latest activity."""
    return list_vendor_summaries(session, limit=min(limit, 500), offset=max(offset, 0))


@app.get("/api/vendors/{vendor_name}/updates")
async def vendor_updates(
    vendor_name: str,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db_session),
):
    """Chronological news feed for a single vendor, tagged by tech desk."""
    data = get_vendor_updates(session, vendor_name, limit=min(limit, 200), offset=max(offset, 0))
    if data is None:
        raise HTTPException(status_code=404, detail=f"No updates found for vendor: {vendor_name}")
    return data


@app.get("/api/updates")
async def list_updates(
    desk_id: str | None = None,
    vendor: str | None = None,
    limit: int = 50,
    offset: int = 0,
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

    total = q.count()
    sort_expr = func.coalesce(UpdateORM.published_date, UpdateORM.discovered_at)
    updates = q.order_by(sort_expr.desc()).offset(max(offset, 0)).limit(limit).all()
    return {"updates": [serialize_update(u, desk_map) for u in updates], "total": total}


@app.get("/api/research/runs")
async def list_research_runs(limit: int = 20, offset: int = 0, session: Session = Depends(get_db_session)):
    total = session.query(ResearchRunORM).count()
    runs = (
        session.query(ResearchRunORM)
        .order_by(ResearchRunORM.started_at.desc())
        .offset(max(offset, 0))
        .limit(min(limit, 100))
        .all()
    )
    def _vendors_added(metadata_json: str | None) -> list[str]:
        if not metadata_json:
            return []
        try:
            return json.loads(metadata_json).get("vendors_added", [])
        except (json.JSONDecodeError, AttributeError):
            return []

    return {
        "total": total,
        "runs": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "status": r.status,
                "period": r.period,
                "desks_processed": r.desks_processed,
                "updates_found": r.updates_found,
                "vendors_added": _vendors_added(r.metadata_json),
                "error_message": r.error_message,
            }
            for r in runs
        ],
    }


@app.get("/api/reports")
async def list_reports(limit: int = 20, offset: int = 0, session: Session = Depends(get_db_session)):
    total = session.query(ReportORM).count()
    reports = (
        session.query(ReportORM)
        .order_by(ReportORM.generated_at.desc())
        .offset(max(offset, 0))
        .limit(min(limit, 100))
        .all()
    )
    return {
        "total": total,
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
        ],
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


# —— SPA fallback ——
# Must be registered last: any path not already matched by an API route or a
# mounted static/asset directory falls back to the built frontend's
# index.html so React Router can handle client-side routes on full page loads
# (e.g. a browser refresh on /vendors/Acme).
_SPA_EXCLUDED_PREFIXES = ("api/", "assets/", "static/")
_SPA_EXCLUDED_EXACT = {"docs", "redoc", "openapi.json"}


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path in _SPA_EXCLUDED_EXACT or full_path.startswith(_SPA_EXCLUDED_PREFIXES):
        raise HTTPException(status_code=404, detail="Not found")
    index = WEB_DIST_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Not found")
