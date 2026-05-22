"""CLI entry point: `python -m scraper <subcommand>`"""
from __future__ import annotations

from pathlib import Path

import click

from .manifest import CHANNELS, Channel


@click.group()
def cli() -> None:
    """Machine Yearning scraper & audio pipeline."""


@cli.command()
@click.option("--channel", type=click.Choice(CHANNELS), required=True)
@click.option("--limit", default=30, show_default=True, help="Max new clips per run.")
def freesound(channel: Channel, limit: int) -> None:
    """Scrape Freesound for the given channel."""
    from .sources import freesound as fs
    click.echo(f"Scraping Freesound → {channel} (limit={limit})")
    clips = fs.scrape_channel(channel, limit=limit)
    click.echo(f"Added {len(clips)} new clips.")


@cli.command()
@click.option("--channel", type=click.Choice(CHANNELS), required=True)
@click.option("--limit", default=30, show_default=True)
def archive(channel: Channel, limit: int) -> None:
    """Scrape archive.org for the given channel."""
    from .sources import archive_org
    click.echo(f"Scraping archive.org → {channel} (limit={limit})")
    clips = archive_org.scrape_channel(channel, limit=limit)
    click.echo(f"Added {len(clips)} new clips.")


@cli.command()
@click.option("--channel", type=click.Choice(CHANNELS), required=True)
@click.option("--limit", default=30, show_default=True)
@click.option(
    "--accept-license",
    is_flag=True,
    help="Acknowledge BBC's personal-use license. Required.",
)
def bbc(channel: Channel, limit: int, accept_license: bool) -> None:
    """Scrape BBC Sound Effects for the given channel."""
    from .sources import bbc as bbc_src
    if not accept_license:
        raise click.UsageError(
            "Pass --accept-license to confirm you've read the BBC Sound Effects "
            "license terms. Personal/art-show use is fine; public-web is not."
        )
    click.echo(f"Scraping BBC → {channel} (limit={limit})")
    clips = bbc_src.scrape_channel(channel, limit=limit)
    click.echo(f"Added {len(clips)} new clips.")


@cli.group()
def local() -> None:
    """Ingest your own recordings."""


@local.command("ingest")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--channel", type=click.Choice(CHANNELS), required=True)
@click.option("--title", required=True)
@click.option("--machine-type", required=True)
@click.option("--machine-specifics", default=None)
@click.option("--mood-tags", default="", help="Comma-separated.")
def local_ingest(
    path: Path,
    channel: Channel,
    title: str,
    machine_type: str,
    machine_specifics: str | None,
    mood_tags: str,
) -> None:
    """Copy a local audio file into the library."""
    from .sources import local as local_src
    tags = [t.strip() for t in mood_tags.split(",") if t.strip()]
    clip = local_src.ingest(
        path=path,
        channel=channel,
        title=title,
        machine_type=machine_type,
        machine_specifics=machine_specifics,
        mood_tags=tags,
    )
    click.echo(f"Ingested {clip.id}")


@cli.command()
@click.option("--id", "clip_id", default=None, help="Normalize one clip by ID.")
@click.option("--force", is_flag=True, help="Re-normalize even if output exists.")
def normalize(clip_id: str | None, force: bool) -> None:
    """Run the ffmpeg normalization pipeline on raw clips."""
    from . import normalize as norm
    n = norm.run(clip_id=clip_id, force=force)
    click.echo(f"Normalized {n} clip(s).")


if __name__ == "__main__":
    cli()
