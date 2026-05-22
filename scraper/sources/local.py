"""Ingest your own recordings.

Copies an audio file into data/raw/local/ and writes a manifest. Pass metadata
via CLI flags; we deliberately don't try to auto-detect machine type from a
filename — your judgment is better.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..manifest import Clip, Channel, RAW_DIR


def _slugify(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:max_len] or "untitled"


def ingest(
    path: Path,
    channel: Channel,
    title: str,
    machine_type: str,
    machine_specifics: str | None = None,
    mood_tags: list[str] | None = None,
) -> Clip:
    today = datetime.now(timezone.utc).date().isoformat()
    base = f"local_{today}_{_slugify(title, 40)}"

    # Disambiguate if a clip with the same slug exists for the day
    clip_id = base
    n = 2
    while Path(f"data/manifests/{clip_id}.json").exists():
        clip_id = f"{base}-{n}"
        n += 1

    dest_dir = RAW_DIR / "local"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{clip_id}{path.suffix.lower()}"
    dest = dest_dir / dest_name
    shutil.copy2(path, dest)

    clip = Clip(
        id=clip_id,
        filename=dest_name,
        title=title,
        channel=channel,
        source="local",
        source_url=None,
        source_id=None,
        license="self",
        license_attribution=None,
        duration_sec=0.0,  # Filled by normalize step
        machine_type=machine_type,
        machine_specifics=machine_specifics,
        mood_tags=mood_tags or [],
        recorded_or_scraped="recorded",
        scraped_at=datetime.now(timezone.utc),
    )
    clip.write()
    return clip
