"""
bastion CLI.

Commands:
    bastion fetch --source <source_id> [--url <override_url>]
        Fetch a single source. If --url is omitted, uses the first seed_url.

    bastion queue [--limit N]
        Show what's due for refresh (the v_crawl_queue view).

    bastion status [--source <source_id>]
        Show last_attempt / last_success / consecutive_failures.

    bastion run-due [--limit N]
        Fetch the top N due sources, in priority order.
"""
from __future__ import annotations
import sys
import logging

import click
import structlog

from .core import db
from .scrapers import get_scraper_class

# Structured logging setup — JSON in prod, pretty in dev.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger("bastion.cli")


@click.group()
def main() -> None:
    """Bastion ingestion CLI."""


@main.command()
@click.option("--source", "source_id", required=True, help="Source slug from the catalogue.")
@click.option("--url", "url", default=None, help="Override URL; defaults to first seed_url.")
def fetch(source_id: str, url: str | None) -> None:
    """Fetch a single source."""
    src = db.fetch_source(source_id)
    if src is None:
        click.echo(f"unknown source: {source_id}", err=True)
        sys.exit(2)
    if url is None:
        seeds = src.get("seed_urls") or []
        if not seeds:
            click.echo(f"source {source_id} has no seed_urls; pass --url", err=True)
            sys.exit(2)
        url = seeds[0]

    scraper_cls = get_scraper_class(src["scrape_class"])
    scraper = scraper_cls(src)
    outcome = scraper.ingest(url)
    click.echo(f"{outcome.outcome}\t{outcome.url}\tsha256={outcome.sha256}\tsize={outcome.size_bytes}\tartifact_id={outcome.artifact_id}")
    sys.exit(0 if outcome.outcome in ("success", "skipped_dup") else 1)


@main.command()
@click.option("--limit", default=20, help="How many to show.")
def queue(limit: int) -> None:
    """Show the crawl queue (sources due for refresh)."""
    rows = db.list_due_sources(limit=limit)
    click.echo(f"{'priority':<8} {'source_id':<35} {'class':<14} {'last_attempt':<25} {'fails':<5}")
    click.echo("-" * 90)
    for r in rows:
        click.echo(f"{r['priority']:<8} {r['source_id']:<35} {r['scrape_class']:<14} {str(r['last_attempt_at']):<25} {r['consecutive_failures']:<5}")


@main.command(name="run-due")
@click.option("--limit", default=10, help="How many sources to fetch.")
def run_due(limit: int) -> None:
    """Run the top-N due sources."""
    rows = db.list_due_sources(limit=limit)
    successes = failures = 0
    for r in rows:
        seeds = r.get("seed_urls") or []
        if not seeds:
            click.echo(f"skip {r['source_id']}: no seeds")
            continue
        scraper_cls = get_scraper_class(r["scrape_class"])
        scraper = scraper_cls(r)
        outcome = scraper.ingest(seeds[0])
        click.echo(f"{outcome.outcome:<14} {r['source_id']:<35} {seeds[0]}")
        if outcome.outcome in ("success", "skipped_dup"):
            successes += 1
        else:
            failures += 1
    click.echo(f"\n{successes} ok, {failures} failed")


@main.command()
@click.option("--artifact-id", required=True, help="UUID of an existing raw_artifacts row.")
def extract(artifact_id: str) -> None:
    """Run the source-specific extractor against an artifact."""
    art = db.fetch_artifact(artifact_id)
    if art is None:
        click.echo(f"unknown artifact: {artifact_id}", err=True)
        sys.exit(2)
    from .sources import EXTRACTOR_BY_SOURCE
    extractor_cls = EXTRACTOR_BY_SOURCE.get(art["source_id"])
    if extractor_cls is None:
        click.echo(f"no extractor registered for source_id={art['source_id']}", err=True)
        sys.exit(2)
    n = extractor_cls().extract(artifact_id)
    click.echo(f"wrote {n} new claims")


if __name__ == "__main__":
    main()
