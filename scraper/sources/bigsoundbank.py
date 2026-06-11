"""bigsoundbank.com scraper — museum of sounds, electronic-only.

bigsoundbank is Joseph SARDIN's curated sound library. The "museum of sounds"
section catalogues obsolete devices; many of those entries are CC0 (verified
per-clip on the detail page), some are "free with attribution but no resale"
which we tag as `bigsoundbank-free`.

This scraper is two-pass on purpose:

  1. `gather_candidates()` — visits a hand-picked set of search URLs (only the
     electronic / on-theme museum exhibits) and writes a JSON file listing
     every result with a default `approved: false`.
  2. `download_approved()` — reads that JSON, fetches each `approved: true`
     entry's detail page for license + description, downloads the MP3, and
     writes a manifest.

The user curates between the two passes by flipping `approved` flags in the
JSON. Channels are pre-proposed but editable in the same file.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..manifest import Clip, RAW_DIR

BASE = "https://bigsoundbank.com"
USER_AGENT = "Mozilla/5.0 (machine-yearning radio scraper)"
REQUEST_DELAY_S = 0.6  # be a polite citizen
CANDIDATES_FILE = Path("data/bigsoundbank_candidates.json")

# Hand-picked museum exhibits: only electronic + on-theme for machine yearning.
# (channel, search_term, exhibit_name) — the search_term is the param passed
# to bigsoundbank's /search?q= endpoint.
MUSEUM_SEARCHES: list[tuple[str, str, str]] = [
    ("talk_to_me",  "modem+56k",                 "56k Modem"),
    ("in_your_ear", "disquette+ordinateur",      "3.5\" Floppy Disk"),
    ("in_your_ear", "disque,compact",            "Compact Disc"),
    ("in_your_ear", "ecran+cathodique",          "CRT Screen"),
    ("talk_to_me",  "radiomessagerie",           "Pager"),
    ("talk_to_me",  "touche+telephone",          "Mobile Phone with Keys"),
    ("talk_to_me",  "calculatrice+imprimante",   "Printing Calculator"),
    ("talk_to_me",  "horloge,parlante",          "Speaking Clock"),
    ("talk_to_me",  "message,morse",             "Morse Telegraph"),
]

DETAIL_HREF_RE = re.compile(r"^/[a-z0-9-]+-s(\d{4})\.html$")


@dataclass
class Candidate:
    id: str
    title: str
    duration_sec: float
    detail_url: str
    found_via: str
    museum_exhibit: str
    channel: str
    approved: bool = False


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _fetch(sess: requests.Session, url: str) -> str:
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    time.sleep(REQUEST_DELAY_S)
    return r.text


def _parse_search_results(html: str) -> list[tuple[str, str, float, str]]:
    """Return (sound_id, title, duration_sec, detail_url) for each result on a search page."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, float, str]] = []
    for h2 in soup.find_all("h2"):
        a = h2.find("a", href=DETAIL_HREF_RE)
        if not a:
            continue
        href = a["href"]
        m = DETAIL_HREF_RE.match(href)
        if not m:
            continue
        sound_id = m.group(1)
        title = a.get_text(" ", strip=True)
        # Look for "Length: MM:SS" in the surrounding block
        block = h2.find_parent() or h2
        text = block.get_text(" ", strip=True)
        duration_sec = 0.0
        dm = re.search(r"Length\s*:\s*(\d+):(\d+)", text)
        if dm:
            duration_sec = float(int(dm.group(1)) * 60 + int(dm.group(2)))
        detail_url = f"{BASE}{href}"
        results.append((sound_id, title, duration_sec, detail_url))
    return results


def _parse_detail_page(html: str) -> dict:
    """Return {description, license_tag, tags} from a sound detail page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    license_tag = "bigsoundbank-free"
    if "CC0" in text or "public domain" in text.lower():
        license_tag = "CC0-1.0"

    # Description: bigsoundbank usually has a paragraph before "Length:" or "Format:"
    description = None
    desc_match = re.search(r"(?:Description|This audio[^:]*:)\s*([^.]+\.)", text)
    if desc_match:
        description = desc_match.group(1).strip()

    # Tags: look for #hashtag patterns
    tags = sorted(set(re.findall(r"#([A-Za-z0-9]+)", text)))
    # Drop the museum tag itself; it's metadata, not editorial
    tags = [t for t in tags if t.lower() != "museumofsounds"]

    return {"description": description, "license_tag": license_tag, "tags": tags}


def gather_candidates() -> Path:
    """Visit each museum search, collect candidates, write to CANDIDATES_FILE."""
    sess = _session()
    all_candidates: list[Candidate] = []
    seen_ids: set[str] = set()

    for channel, query, exhibit in MUSEUM_SEARCHES:
        url = f"{BASE}/search?q={query}"
        print(f"  searching: {exhibit!r} ({channel}) → {url}")
        try:
            html = _fetch(sess, url)
        except requests.HTTPError as e:
            print(f"    failed: {e}")
            continue
        results = _parse_search_results(html)
        print(f"    {len(results)} results")
        for sound_id, title, duration_sec, detail_url in results:
            if sound_id in seen_ids:
                continue
            seen_ids.add(sound_id)
            all_candidates.append(Candidate(
                id=sound_id,
                title=title,
                duration_sec=duration_sec,
                detail_url=detail_url,
                found_via=query,
                museum_exhibit=exhibit,
                channel=channel,
            ))

    CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(all_candidates),
        "approved_count": sum(1 for c in all_candidates if c.approved),
        "candidates": [asdict(c) for c in all_candidates],
    }
    CANDIDATES_FILE.write_text(json.dumps(payload, indent=2))
    return CANDIDATES_FILE


def _download_mp3(sess: requests.Session, sound_id: str, dest: Path) -> None:
    url = f"{BASE}/UPLOAD/mp3/{sound_id}.mp3"
    with sess.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            for chunk in r.iter_content(64 * 1024):
                if chunk:
                    f.write(chunk)
    time.sleep(REQUEST_DELAY_S)


def _infer_machine_type(title: str, exhibit: str, tags: list[str]) -> str:
    blob = (title + " " + exhibit + " " + " ".join(tags)).lower()
    for needle, label in [
        ("modem", "modem"),
        ("floppy", "floppy"),
        ("disquette", "floppy"),
        ("compact disc", "cd"),
        ("crt", "crt"),
        ("cathod", "crt"),
        ("pager", "pager"),
        ("radiomessag", "pager"),
        ("telephone", "phone"),
        ("phone", "phone"),
        ("calculator", "calculator"),
        ("calcul", "calculator"),
        ("clock", "clock"),
        ("horloge", "clock"),
        ("morse", "telegraph"),
        ("telegraph", "telegraph"),
    ]:
        if needle in blob:
            return label
    return "unknown"


def download_approved() -> list[Clip]:
    if not CANDIDATES_FILE.exists():
        raise RuntimeError(
            f"{CANDIDATES_FILE} does not exist. Run "
            "`python -m scraper bigsoundbank gather` first."
        )
    payload = json.loads(CANDIDATES_FILE.read_text())
    approved = [c for c in payload["candidates"] if c.get("approved")]
    if not approved:
        print(f"No approved candidates in {CANDIDATES_FILE}. "
              "Edit the file and set approved:true on the ones to keep.")
        return []

    sess = _session()
    new_clips: list[Clip] = []

    for cand in approved:
        sound_id = cand["id"]
        clip_id = f"bigsoundbank_{sound_id}"
        manifest_path = Path(f"data/manifests/{clip_id}.json")
        if manifest_path.exists():
            print(f"  skip (already have manifest): {clip_id}")
            continue

        print(f"  fetching detail: {cand['title']!r}  (s{sound_id})")
        try:
            detail_html = _fetch(sess, cand["detail_url"])
        except requests.HTTPError as e:
            print(f"    detail fetch failed: {e}")
            continue
        detail = _parse_detail_page(detail_html)

        raw_filename = f"{sound_id}.mp3"
        raw_path = RAW_DIR / "bigsoundbank" / raw_filename
        try:
            _download_mp3(sess, sound_id, raw_path)
        except requests.HTTPError as e:
            print(f"    mp3 download failed: {e}")
            continue

        try:
            clip = Clip(
                id=clip_id,
                filename=raw_filename,
                title=cand["title"],
                channel=cand["channel"],
                source="bigsoundbank",
                source_url=cand["detail_url"],
                source_id=sound_id,
                license=detail["license_tag"],
                license_attribution="Joseph SARDIN",
                duration_sec=float(cand.get("duration_sec") or 0.0),
                machine_type=_infer_machine_type(
                    cand["title"], cand["museum_exhibit"], detail["tags"]
                ),
                machine_specifics=cand["museum_exhibit"],
                mood_tags=detail["tags"],
                recorded_or_scraped="scraped",
                scraped_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            print(f"    manifest validation failed: {e}")
            continue

        clip.write()
        new_clips.append(clip)
        print(f"    + {clip.id}  [{clip.license}]")

    return new_clips
