#!/usr/bin/env python3
"""Aggregate per-clip manifests into web/channels.json.

Scans data/manifests/, validates each, groups by channel, and emits a single
JSON file the web player can fetch. Also verifies that referenced normalized
audio files exist, and warns when channels are below the MVP target.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow running as a script from repo root
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scraper.manifest import CHANNEL_TITLES, CHANNELS, Clip, NORMALIZED_DIR  # noqa: E402

OUT = REPO / "web" / "channels.json"
MVP_MIN_PER_CHANNEL = 20


def main() -> int:
    clips = Clip.load_all()
    by_channel: dict[str, list[dict]] = defaultdict(list)
    missing_audio: list[str] = []

    for c in clips:
        if not c.normalized_path().exists():
            missing_audio.append(c.id)
            continue
        by_channel[c.channel].append({
            "id": c.id,
            # Served via web/audio/, a symlink to data/normalized/
            "url": f"audio/{c.normalized_path().name}",
            "title": c.title,
            "machine_type": c.machine_type,
            "machine_specifics": c.machine_specifics,
            "duration_sec": c.duration_sec,
            "license": c.license,
            "license_attribution": c.license_attribution,
            "source": c.source,
            "source_url": str(c.source_url) if c.source_url else None,
        })

    # Stable order per channel — alphabetical by id
    channels_out = {ch: sorted(by_channel.get(ch, []), key=lambda x: x["id"]) for ch in CHANNELS}
    out_data = {
        "titles": {ch: CHANNEL_TITLES[ch] for ch in CHANNELS},
        "channels": channels_out,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out_data, indent=2))

    print(f"Wrote {OUT} with:")
    for ch in CHANNELS:
        n = len(channels_out[ch])
        flag = "  ⚠ below MVP target" if n < MVP_MIN_PER_CHANNEL else ""
        print(f"  {ch} ({CHANNEL_TITLES[ch]}): {n}{flag}")

    if missing_audio:
        print(f"\nSkipped {len(missing_audio)} clip(s) without normalized audio:")
        for cid in missing_audio[:10]:
            print(f"  - {cid}")
        if len(missing_audio) > 10:
            print(f"  ... and {len(missing_audio) - 10} more")
        print("Run `python -m scraper normalize` to process them.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
