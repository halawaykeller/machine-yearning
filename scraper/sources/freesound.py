"""Freesound scraper.

Uses the v2 API with a personal token. Downloads HQ MP3 *previews* rather than
originals — previews don't require OAuth, are already MP3, and inherit the
clip's CC license. Plenty good for radio.

API docs: https://freesound.org/docs/api/
Get a token: https://freesound.org/apiv2/apply/
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from ..manifest import Clip, Channel, RAW_DIR

API_BASE = "https://freesound.org/apiv2"
SEARCH_URL = f"{API_BASE}/search/text/"

# Freesound's `query` param does not support OR; we issue one search per term
# and dedupe across them. Tunable — the editorial pass will fix mis-tagging.
CHANNEL_QUERIES: dict[str, list[str]] = {
    "turn_me_on":  ["boot chime", "startup sound", "shutdown sound", "power on", "POST beep", "computer chime"],
    "charge_me":   ["low battery", "battery beep", "charge sound", "UPS alarm", "plug in"],
    "in_your_ear": ["computer fan", "hard drive", "floppy drive", "cooling fan", "server hum", "hdd"],
    "talk_to_me":  ["error beep", "modem", "dial-up", "fax tone", "notification sound", "alert"],
}

# Map Freesound license values to our SPDX-ish tags. Filter out non-CC.
# Freesound returns license as a URL (e.g. http://creativecommons.org/publicdomain/zero/1.0/).
# Older API responses sometimes used a human-readable name; we accept both.
LICENSE_URL_MAP = {
    "creativecommons.org/publicdomain/zero/1.0":  "CC0-1.0",
    "creativecommons.org/licenses/by/3.0":         "CC-BY-3.0",
    "creativecommons.org/licenses/by/4.0":         "CC-BY-4.0",
    "creativecommons.org/licenses/by-nc/3.0":      "CC-BY-NC-3.0",
    "creativecommons.org/licenses/by-nc/4.0":      "CC-BY-NC-4.0",
    "creativecommons.org/licenses/sampling+/1.0":  "CC-Sampling-Plus-1.0",
}
LICENSE_NAME_MAP = {
    "Creative Commons 0":             "CC0-1.0",
    "Attribution":                    "CC-BY-4.0",
    "Attribution 3.0":                "CC-BY-3.0",
    "Attribution 4.0":                "CC-BY-4.0",
    "Attribution Noncommercial":      "CC-BY-NC-4.0",
    "Attribution NonCommercial 4.0":  "CC-BY-NC-4.0",
    "Sampling+":                      "CC-Sampling-Plus-1.0",
}


def _token() -> str:
    load_dotenv()
    tok = os.environ.get("FREESOUND_API_KEY", "").strip()
    if not tok:
        raise RuntimeError(
            "FREESOUND_API_KEY missing. Copy .env.example to .env and add your "
            "token from https://freesound.org/apiv2/apply/"
        )
    return tok


def _headers() -> dict[str, str]:
    return {"Authorization": f"Token {_token()}"}


def _slugify(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:max_len] or "untitled"


def _normalize_license(raw: str | None) -> str | None:
    """Return our license tag, or None if the clip should be skipped."""
    if not raw:
        return None
    if raw in LICENSE_NAME_MAP:
        return LICENSE_NAME_MAP[raw]
    # URL form: match by substring against the path
    needle = raw.lower().rstrip("/")
    for url_frag, tag in LICENSE_URL_MAP.items():
        if url_frag in needle:
            return tag
    # Fallback name-fuzzy match
    for name, tag in LICENSE_NAME_MAP.items():
        if name.lower() in raw.lower():
            return tag
    return None  # All Rights Reserved or unknown — skip


def search(query: str, page: int = 1, page_size: int = 30) -> dict:
    params = {
        "query": query,
        "page": page,
        "page_size": page_size,
        "fields": "id,name,license,username,url,previews,duration,tags,description,type",
        # Bias to short clips — radio interludes, not field recordings
        "filter": "duration:[0.3 TO 30]",
        "sort": "score",
    }
    r = requests.get(SEARCH_URL, params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=_headers(), stream=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)


def _infer_machine_type(name: str, tags: list[str]) -> str:
    """Best-effort. The editorial pass will fix the rest by hand."""
    blob = (name + " " + " ".join(tags)).lower()
    for needle, label in [
        ("laptop", "laptop"),
        ("macbook", "laptop"),
        ("thinkpad", "laptop"),
        ("modem", "modem"),
        ("dial", "modem"),
        ("fax", "fax"),
        ("ups", "ups"),
        ("fan", "fan"),
        ("hdd", "hdd"),
        ("hard drive", "hdd"),
        ("floppy", "floppy"),
        ("printer", "printer"),
        ("camera", "camera"),
        ("phone", "phone"),
        ("battery", "battery"),
        ("computer", "computer"),
        ("server", "server"),
    ]:
        if needle in blob:
            return label
    return "unknown"


def scrape_channel(channel: Channel, limit: int = 30) -> list[Clip]:
    """Search across each per-channel query, filter to CC, download previews, write manifests."""
    queries = CHANNEL_QUERIES[channel]
    new_clips: list[Clip] = []
    seen_ids: set[str] = set()

    for query in queries:
        if len(new_clips) >= limit:
            break
        print(f"  query: {query!r}")
        try:
            data = search(query, page=1, page_size=30)
        except requests.HTTPError as e:
            print(f"  search failed for {query!r}: {e}")
            continue

        results = data.get("results", [])
        print(f"    {len(results)} results")
        if not results:
            continue

        for r in results:
            if len(new_clips) >= limit:
                break

            fs_id = str(r["id"])
            if fs_id in seen_ids:
                continue
            seen_ids.add(fs_id)

            license_tag = _normalize_license(r.get("license"))
            if license_tag is None:
                continue  # Skip non-CC / unknown

            clip_id = f"freesound_{fs_id}"
            manifest_path = Path(f"data/manifests/{clip_id}.json")
            if manifest_path.exists():
                continue

            preview_url = (r.get("previews") or {}).get("preview-hq-mp3")
            if not preview_url:
                continue

            slug = _slugify(r.get("name", "untitled"))
            raw_filename = f"{fs_id}_{slug}.mp3"
            raw_path = RAW_DIR / "freesound" / raw_filename

            try:
                _download(preview_url, raw_path)
            except requests.HTTPError as e:
                print(f"    download failed for {fs_id}: {e}")
                continue

            try:
                clip = Clip(
                    id=clip_id,
                    filename=raw_filename,
                    title=r.get("name", "untitled"),
                    channel=channel,
                    source="freesound",
                    source_url=r.get("url"),
                    source_id=fs_id,
                    license=license_tag,
                    license_attribution=r.get("username"),
                    duration_sec=float(r.get("duration", 0.0)),
                    machine_type=_infer_machine_type(r.get("name", ""), r.get("tags", []) or []),
                    machine_specifics=None,
                    mood_tags=list(r.get("tags", []) or []),
                    recorded_or_scraped="scraped",
                    scraped_at=datetime.now(timezone.utc),
                )
            except Exception as e:
                print(f"    manifest validation failed for {fs_id}: {e}")
                continue

            clip.write()
            new_clips.append(clip)
            print(f"    + {clip.id}  {clip.title!r}  [{clip.license}]")
            time.sleep(0.2)

    return new_clips
