from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tech_desk import __version__
from tech_desk.config import ReportPeriod, get_settings, resolve_desks
from tech_desk.database import init_db
from tech_desk.llm import LLMClient
from tech_desk.reports.generator import ReportGenerator
from tech_desk.research.collector import ResearchCollector

app = typer.Typer(
    name="tech-desk",
    help="Cotiviti Tech Desk — automated Gen AI research and reporting",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@app.command()
def version():
    """Show version."""
    console.print(f"tech-desk v{__version__}")


@app.command()
def init(
    api_key: str = typer.Option(..., prompt=True, hide_input=True, help="OpenAI-compatible API key"),
    base_url: str = typer.Option("https://api.openai.com/v1", help="API base URL"),
    model: str = typer.Option("gpt-4o", help="Model name"),
):
    """Initialize Tech Desk with your LLM API key."""
    _setup_logging()
    init_db()

    llm = LLMClient(api_key=api_key, base_url=base_url, model=model)
    console.print("Validating API key...")
    result = llm.validate_api_key()
    if not result.ok:
        console.print(f"[red]{result.message}[/red]")
        raise typer.Exit(1)

    env_path = Path.cwd() / ".env"
    env_content = f"""OPENAI_API_KEY={api_key}
OPENAI_BASE_URL={base_url}
OPENAI_MODEL={model}
TECH_DESK_DATA_DIR=./data
"""
    env_path.write_text(env_content, encoding="utf-8")
    get_settings.cache_clear()

    console.print(Panel.fit(
        "[green]Tech Desk initialized successfully![/green]\n\n"
        f"Model: {model}\n"
        f"Config saved to: {env_path}\n\n"
        "Next steps:\n"
        "  tech-desk pipeline --period monthly\n"
        "  tech-desk serve",
        title="Setup Complete",
    ))


@app.command()
def research(
    period: ReportPeriod = typer.Option("daily", help="Research period context"),
    desk: list[str] = typer.Option(
        None,
        "--desk",
        "-d",
        help="Single desk: id, code (APPS), or name. Repeat for multiple. Omit for all.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run web research and curate updates across tech desks."""
    _setup_logging(verbose)
    init_db()
    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]No API key configured. Run: tech-desk init[/red]")
        raise typer.Exit(1)

    try:
        desks = resolve_desks(desk)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    scope = desks[0].name if len(desks) == 1 else f"{len(desks)} desks"
    console.print(f"[bold]Starting research ({period}) — {scope}...[/bold]")
    collector = ResearchCollector()
    run = collector.run(period=period, desk_keys=desk)

    table = Table(title="Research Complete")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Run ID", str(run.id))
    table.add_row("Status", run.status)
    table.add_row("Desks Processed", str(run.desks_processed))
    table.add_row("New Updates", str(run.updates_found))
    console.print(table)


@app.command()
def report(
    period: ReportPeriod = typer.Option("monthly", help="Report period"),
    desk: list[str] = typer.Option(
        None,
        "--desk",
        "-d",
        help="Single desk: id, code (APPS), or name. Repeat for multiple. Omit for all.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Generate stakeholder report from collected updates."""
    _setup_logging(verbose)
    init_db()
    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]No API key configured. Run: tech-desk init[/red]")
        raise typer.Exit(1)

    try:
        desks = resolve_desks(desk)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    scope = desks[0].name if len(desks) == 1 else f"{len(desks)} desks"
    console.print(f"[bold]Generating {period} report — {scope}...[/bold]")
    generator = ReportGenerator()
    result = generator.generate(period=period, desk_keys=desk)

    console.print(Panel.fit(
        f"[green]Report generated![/green]\n\n"
        f"Title: {result.title}\n"
        f"Updates: {result.metadata.get('total_updates', 0)}\n"
        f"Report ID: {result.id}",
        title="Report Ready",
    ))


@app.command(name="pipeline")
def run_pipeline(
    period: ReportPeriod = typer.Option("monthly", help="Pipeline period"),
    desk: list[str] = typer.Option(
        None,
        "--desk",
        "-d",
        help="Single desk: id, code (APPS), or name. Repeat for multiple. Omit for all.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full automation: research + report generation in one command."""
    _setup_logging(verbose)
    init_db()
    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]No API key configured. Run: tech-desk init[/red]")
        raise typer.Exit(1)

    try:
        desks = resolve_desks(desk)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    scope = desks[0].name if len(desks) == 1 else f"all {len(desks)} desks"
    console.print(Panel.fit(
        f"[bold]Running Tech Desk pipeline ({period}) — {scope}[/bold]\n"
        "This will search the web, analyze updates with AI, and generate a stakeholder report.",
        title="Tech Desk Pipeline",
    ))

    llm = LLMClient()
    collector = ResearchCollector(llm=llm)
    run = collector.run(period=period, desk_keys=desk)
    console.print(f"Research: {run.updates_found} new updates from {run.desks_processed} desks")

    generator = ReportGenerator(llm=llm)
    result = generator.generate(period=period, desk_keys=desk)

    console.print(Panel.fit(
        f"[green bold]Pipeline complete![/green bold]\n\n"
        f"Report: {result.title}\n"
        f"Total curated updates: {result.metadata.get('total_updates', 0)}\n"
        f"Report ID: {result.id}\n\n"
        "View in dashboard: tech-desk serve",
        title="Done",
    ))


@app.command()
def serve(
    host: Optional[str] = typer.Option(None, help="Host"),
    port: Optional[int] = typer.Option(None, help="Port"),
    reload: bool = typer.Option(False, help="Auto-reload"),
):
    """Start the web dashboard and API server."""
    import uvicorn

    settings = get_settings()
    init_db()
    uvicorn.run(
        "tech_desk.api.main:app",
        host=host or settings.tech_desk_host,
        port=port or settings.tech_desk_port,
        reload=reload,
    )


@app.command()
def doctor():
    """Run deploy-readiness checks (DB, migrations, config, search backend).

    Exits non-zero if any blocking check fails — use this after `deploy.sh`
    restarts the service, or before pointing traffic at a new deployment.
    """
    init_db()
    from tech_desk import diagnostics

    result = diagnostics.run_all_checks()
    checks = result["checks"]

    table = Table(title="Tech Desk Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    table.add_column("Details", overflow="fold")

    blocking_failed = False
    for name, check in checks.items():
        ok = check.get("ok", False)
        if name != "search_backend" and not ok:
            blocking_failed = True
        icon = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        details_parts = []
        for key, value in check.items():
            if key == "ok":
                continue
            if value in (None, "", []):
                continue
            details_parts.append(f"{key}={value}")
        table.add_row(name, icon, "\n".join(details_parts))

    console.print(table)

    if blocking_failed:
        console.print("[red bold]One or more checks failed — not ready to deploy.[/red bold]")
        raise typer.Exit(1)
    console.print("[green bold]All checks passed.[/green bold]")


@app.command()
def status():
    """Show system status and recent activity."""
    init_db()
    settings = get_settings()
    from tech_desk.database import get_session_factory, ReportORM, ResearchRunORM, UpdateORM

    session = get_session_factory()()
    try:
        total_updates = session.query(UpdateORM).count()
        total_reports = session.query(ReportORM).count()
        last_run = session.query(ResearchRunORM).order_by(ResearchRunORM.started_at.desc()).first()
        last_report = session.query(ReportORM).order_by(ReportORM.generated_at.desc()).first()

        table = Table(title="Tech Desk Status")
        table.add_column("Setting", style="cyan")
        table.add_column("Value")
        table.add_row("Version", __version__)
        table.add_row("API Key", "Configured" if settings.openai_api_key else "[red]Not set[/red]")
        table.add_row("Model", settings.openai_model)
        table.add_row("Data Dir", str(settings.tech_desk_data_dir))
        table.add_row("Total Updates", str(total_updates))
        table.add_row("Total Reports", str(total_reports))
        if last_run:
            table.add_row("Last Research", f"{last_run.status} — {last_run.updates_found} updates")
        if last_report:
            table.add_row("Last Report", last_report.title)
        console.print(table)
    finally:
        session.close()


if __name__ == "__main__":
    app()
