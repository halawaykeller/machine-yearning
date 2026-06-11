"""BBC Sound Effects scraper.

The BBC publishes a sound-effects library at https://sound-effects.bbcrewind.co.uk/
under a license that allows personal, educational, and research use but
**restricts commercial use and redistribution**.

This means:
- OK to use clips in a local installation, an art show, or this dev environment.
- NOT OK to host them on a public website without re-reading the license terms
  and confirming what's currently allowed.

The downloader is gated behind --accept-license in the CLI for a reason. If you
later flip the project to a public web build, audit every BBC clip first.

License URL (verify when you use): https://sound-effects.bbcrewind.co.uk/licensing
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..manifest import Clip, Channel, RAW_DIR

API_BASE = "https://sound-effects-api.bbcrewind.co.uk/api/sfx/search"
DOWNLOAD_BASE = "https://sound-effects-media.bbcrewind.co.uk/mp3"

CHANNEL_QUERIES: dict[str, list[str]] = {
    "turn_me_on":  ["computer startup", "boot chime", "power on", "system startup", "computer power"],
    "charge_me":   ["battery low", "battery beep", "charging", "ups alarm", "power adapter"],
    "in_your_ear": ["computer fan", "hard drive", "floppy drive", "server room", "tape drive", "machine hum"],
    "talk_to_me":  ["modem dialup", "fax tone", "telegraph", "pager beep", "error beep", "notification alert"],
}


def _slugify(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:max_len] or "untitled"


def _search(query: str, page: int = 0, size: int = 30) -> dict:
    payload = {
        "criteria": {
            "from": page * size,
            "size": size,
            "tags": None,
            "categories": None,
            "durations": None,
            "continents": None,
            "sortBy": None,
            "source": None,
            "recordist": None,
            "habitat": None,
            "query": query,
        }
    }
    r = requests.post(API_BASE, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def scrape_channel(channel: Channel, limit: int = 30) -> list[Clip]:
    queries = CHANNEL_QUERIES[channel]
    new_clips: list[Clip] = []
    seen_ids: set[str] = set()

    for query in queries:
        if len(new_clips) >= limit:
            break
        print(f"  query: {query!r}")
        page = 0
        while len(new_clips) < limit and page <= 5:
            try:
                data = _search(query, page=page)
            except requests.HTTPError as e:
                print(f"  BBC search failed: {e}")
                break

            results = data.get("results") or data.get("hits") or []
            if not results:
                break

            for hit in results:
                if len(new_clips) >= limit:
                    break
                # The API has shifted over time; tolerate both shapes
                src = hit.get("_source") or hit
                bbc_id = src.get("id") or src.get("CDNumber")
                if not bbc_id:
                    continue
                bbc_id = str(bbc_id)
                if bbc_id in seen_ids:
                    continue
                seen_ids.add(bbc_id)

                clip_id = f"bbc_{_slugify(bbc_id, 40)}"
                manifest_path = Path(f"data/manifests/{clip_id}.json")
                if manifest_path.exists():
                    continue

                mp3_url = f"{DOWNLOAD_BASE}/{bbc_id}.mp3"
                raw_path = RAW_DIR / "bbc" / f"{bbc_id}.mp3"

                try:
                    r = requests.get(mp3_url, stream=True, timeout=60)
                    r.raise_for_status()
                except requests.HTTPError as e:
                    print(f"  download failed for {bbc_id}: {e}")
                    continue

                raw_path.parent.mkdir(parents=True, exist_ok=True)
                with raw_path.open("wb") as f:
                    for chunk in r.iter_content(64 * 1024):
                        if chunk:
                            f.write(chunk)

                clip = Clip(
                    id=clip_id,
                    filename=raw_path.name,
                    title=src.get("description") or bbc_id,
                    channel=channel,
                    source="bbc",
                    source_url=f"https://sound-effects.bbcrewind.co.uk/search?q={bbc_id}",
                    source_id=bbc_id,
                    license="BBC-personal-use",
                    license_attribution="BBC Sound Effects",
                    duration_sec=float(src.get("duration", 0.0)) or 0.0,
                    machine_type="unknown",
                    machine_specifics=None,
                    mood_tags=[t for t in (src.get("category") or []) if t] if isinstance(src.get("category"), list) else [],
                    recorded_or_scraped="scraped",
                    scraped_at=datetime.now(timezone.utc),
                )
                clip.write()
                new_clips.append(clip)
                print(f"  + {clip.id}")
                time.sleep(0.3)

            page += 1

    return new_clips

    return new_clips
