"""Manifest schema — single source of truth for clip metadata.

One JSON file per clip lives in `data/manifests/<id>.json`. Every scraper writes
through this model; every consumer (normalize, build_channels) reads through it.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

CHANNELS = ("turn_me_on", "charge_me", "in_your_ear", "talk_to_me")
Channel = Literal["turn_me_on", "charge_me", "in_your_ear", "talk_to_me"]

# Display titles shown to the listener. IDs above are machine identifiers;
# these are the editorial names the player surfaces.
CHANNEL_TITLES: dict[str, str] = {
    "turn_me_on":  "turn me on",
    "charge_me":   "charge me",
    "in_your_ear": "put me in your ear",
    "talk_to_me":  "talk to me",
}

Source = Literal["freesound", "archive_org", "bbc", "bigsoundbank", "local"]
RecordedOrScraped = Literal["recorded", "scraped"]

MANIFEST_DIR = Path("data/manifests")
RAW_DIR = Path("data/raw")
NORMALIZED_DIR = Path("data/normalized")


class Clip(BaseModel):
    id: str
    filename: str
    title: str
    channel: Channel
    source: Source
    source_url: HttpUrl | None = None
    source_id: str | None = None
    license: str
    license_attribution: str | None = None
    duration_sec: float
    machine_type: str
    machine_specifics: str | None = None
    mood_tags: list[str] = Field(default_factory=list)
    recorded_or_scraped: RecordedOrScraped
    scraped_at: datetime
    loudness_lufs: float | None = None
    sample_rate: int | None = None
    bitrate_kbps: int | None = None

    def manifest_path(self) -> Path:
        return MANIFEST_DIR / f"{self.id}.json"

    def raw_path(self) -> Path:
        return RAW_DIR / self.source / self.filename

    def normalized_path(self) -> Path:
        return NORMALIZED_DIR / f"{self.id}.mp3"

    def write(self) -> Path:
        path = self.manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> "Clip":
        return cls.model_validate_json(path.read_text())

    @classmethod
    def load_all(cls, manifest_dir: Path = MANIFEST_DIR) -> list["Clip"]:
        if not manifest_dir.exists():
            return []
        return [cls.load(p) for p in sorted(manifest_dir.glob("*.json"))]
