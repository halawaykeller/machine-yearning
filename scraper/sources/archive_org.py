"""archive.org scraper.

Uses the `internetarchive` Python library to search the audio collection.
Filters to public-domain / CC items and downloads original audio files.

Library docs: https://archive.org/developers/internetarchive/
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ..manifest import Clip, Channel, RAW_DIR

CHANNEL_QUERIES: dict[str, str] = {
    "boot_shutdown": 'subject:"boot sound" OR subject:"startup" OR title:"boot chime"',
    "power_battery": 'subject:"low battery" OR title:"battery beep" OR title:"UPS"',
    "fans_drives":   'subject:"hard drive" OR title:"floppy drive" OR title:"server fan"',
    "alerts_errors": 'subject:"modem" OR title:"dial-up" OR title:"error beep" OR title:"fax"',
}

# archive.org license URLs we'll accept
ACCEPTED_LICENSES = {
    "https://creativecommons.org/publicdomain/zero/1.0/":     "CC0-1.0",
    "https://creativecommons.org/licenses/by/4.0/":            "CC-BY-4.0",
    "https://creativecommons.org/licenses/by/3.0/":            "CC-BY-3.0",
    "https://creativecommons.org/licenses/publicdomain/":      "PD",
    "https://creativecommons.org/publicdomain/mark/1.0/":      "PD",
}

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aiff"}


def _slugify(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:max_len] or "untitled"


def _normalize_license(raw: str | None) -> str | None:
    if not raw:
        return None
    return ACCEPTED_LICENSES.get(raw.rstrip("/") + "/")


def scrape_channel(channel: Channel, limit: int = 30) -> list[Clip]:
    try:
        import internetarchive as ia
    except ImportError as e:
        raise RuntimeError(
            "internetarchive package not installed. Run `pip install -e .` or "
            "`pip install internetarchive`."
        ) from e

    query = f"mediatype:audio AND ({CHANNEL_QUERIES[channel]})"
    new_clips: list[Clip] = []

    search = ia.search_items(query, fields=["identifier", "title", "licenseurl", "creator"])
    for hit in search:
        if len(new_clips) >= limit:
            break

        license_tag = _normalize_license(hit.get("licenseurl"))
        if license_tag is None:
            continue

        identifier = hit["identifier"]
        clip_id_prefix = f"archive_{_slugify(identifier, 80)}"
        if any(Path("data/manifests").glob(f"{clip_id_prefix}*.json")):
            continue

        item = ia.get_item(identifier)
        # Pick the smallest audio file under 30s if possible; otherwise the first audio file
        audio_files = [f for f in item.files if Path(f.get("name", "")).suffix.lower() in AUDIO_EXTS]
        if not audio_files:
            continue
        # Prefer "original" source over derivatives
        audio_files.sort(key=lambda f: (f.get("source") != "original", float(f.get("size", 1e12))))
        chosen = audio_files[0]
        fname = chosen["name"]

        raw_dir = RAW_DIR / "archive_org"
        raw_dir.mkdir(parents=True, exist_ok=True)
        # `internetarchive` downloads to <identifier>/<filename> by default
        try:
            ia.download(identifier, files=[fname], destdir=str(raw_dir), no_directory=False, verbose=False)
        except Exception as e:
            print(f"  download failed for {identifier}: {e}")
            continue

        local_raw = raw_dir / identifier / fname
        if not local_raw.exists():
            continue

        # Re-home into RAW_DIR/archive_org/ with a flat name
        flat_name = f"{_slugify(identifier, 40)}_{Path(fname).name}"
        flat_path = raw_dir / flat_name
        local_raw.replace(flat_path)
        # Clean up the per-identifier subdir if empty
        try:
            local_raw.parent.rmdir()
        except OSError:
            pass

        clip = Clip(
            id=f"archive_{_slugify(identifier, 80)}",
            filename=flat_name,
            title=hit.get("title") or identifier,
            channel=channel,
            source="archive_org",
            source_url=f"https://archive.org/details/{identifier}",
            source_id=identifier,
            license=license_tag,
            license_attribution=hit.get("creator"),
            duration_sec=0.0,  # Filled by normalize step
            machine_type="unknown",
            machine_specifics=None,
            mood_tags=[],
            recorded_or_scraped="scraped",
            scraped_at=datetime.now(timezone.utc),
        )
        clip.write()
        new_clips.append(clip)
        print(f"  + {clip.id}  [{license_tag}]")
        time.sleep(0.3)

    return new_clips
