"""Audio normalization pipeline.

For each clip with a raw file:
  1. Trim leading + trailing silence (silenceremove, -50 dB threshold).
  2. Loudness-normalize to -16 LUFS (two-pass loudnorm for accuracy).
  3. Convert to mono, 128 kbps MP3, 44.1 kHz.

Updates the manifest with measured loudness, sample rate, bitrate, duration.
Idempotent: skips clips already normalized unless --force.

Requires `ffmpeg` and `ffprobe` on PATH.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .manifest import Clip, NORMALIZED_DIR

TARGET_LUFS = -16.0
TARGET_TP = -1.5      # True peak ceiling
TARGET_LRA = 11.0     # Loudness range
TARGET_SR = 44100
TARGET_BITRATE_KBPS = 128
SILENCE_THRESHOLD_DB = -50

SILENCE_TRIM = (
    f"silenceremove=start_periods=1:start_silence=0:start_threshold={SILENCE_THRESHOLD_DB}dB,"
    f"aformat=sample_fmts=fltp,areverse,"
    f"silenceremove=start_periods=1:start_silence=0:start_threshold={SILENCE_THRESHOLD_DB}dB,"
    f"aformat=sample_fmts=fltp,areverse"
)


def _measure_loudnorm(raw: Path) -> dict:
    """First-pass loudnorm: measure, return JSON stats."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(raw),
        "-af",
        f"{SILENCE_TRIM},"
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
        "-f", "null", "-",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg measure failed: {p.stderr[-2000:]}")
    # loudnorm prints JSON to stderr; find the {...} block at the end
    err = p.stderr
    start = err.rfind("{")
    end = err.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"no loudnorm json in ffmpeg output:\n{err[-2000:]}")
    return json.loads(err[start : end + 1])


def _is_unmeasurable(stats: dict) -> bool:
    """Very short or near-silent clips measure as -inf — loudnorm can't second-pass them."""
    try:
        i = float(stats.get("input_i", "-inf"))
    except (TypeError, ValueError):
        return True
    return i < -70  # Below this, there's no real signal to normalize


def _apply_loudnorm(raw: Path, out: Path, stats: dict) -> None:
    """Second-pass loudnorm: apply with measured values, encode to MP3.

    For unmeasurable inputs (very short/silent), skip the loudnorm filter and
    just transcode + silence-trim — better than crashing on -inf.
    """
    if _is_unmeasurable(stats):
        af = SILENCE_TRIM
    else:
        af = (
            f"{SILENCE_TRIM},"
            f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}"
            f":measured_I={stats['input_i']}"
            f":measured_LRA={stats['input_lra']}"
            f":measured_TP={stats['input_tp']}"
            f":measured_thresh={stats['input_thresh']}"
            f":offset={stats['target_offset']}"
            f":linear=true:print_format=summary"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(raw),
        "-af", af,
        "-ar", str(TARGET_SR),
        "-ac", "1",
        "-b:a", f"{TARGET_BITRATE_KBPS}k",
        "-codec:a", "libmp3lame",
        str(out),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg apply failed: {p.stderr[-2000:]}")


def _probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(p.stdout.strip())


def normalize_clip(clip: Clip, force: bool = False) -> Clip | None:
    """Normalize one clip. Returns the updated Clip, or None if skipped."""
    raw = clip.raw_path()
    if not raw.exists():
        print(f"  ! raw missing for {clip.id}: {raw}")
        return None

    out = clip.normalized_path()
    if out.exists() and clip.loudness_lufs is not None and not force:
        return None  # Idempotent skip

    print(f"  ~ {clip.id}")
    stats = _measure_loudnorm(raw)
    _apply_loudnorm(raw, out, stats)

    if _is_unmeasurable(stats):
        clip.loudness_lufs = None  # No real signal to measure
    else:
        try:
            clip.loudness_lufs = float(stats.get("output_i", TARGET_LUFS))
        except (TypeError, ValueError):
            clip.loudness_lufs = None
    clip.sample_rate = TARGET_SR
    clip.bitrate_kbps = TARGET_BITRATE_KBPS
    clip.duration_sec = _probe_duration(out)
    clip.write()
    return clip


def run(clip_id: str | None = None, force: bool = False) -> int:
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    clips = Clip.load_all()
    if clip_id:
        clips = [c for c in clips if c.id == clip_id]
        if not clips:
            raise SystemExit(f"No clip with id={clip_id!r}")
    n = 0
    failures: list[tuple[str, str]] = []
    for c in clips:
        try:
            if normalize_clip(c, force=force) is not None:
                n += 1
        except Exception as e:
            failures.append((c.id, str(e).splitlines()[-1] if str(e) else type(e).__name__))
            print(f"  ! {c.id} failed: {failures[-1][1]}")
    if failures:
        print(f"\n{len(failures)} clip(s) failed normalization (skipped, not fatal):")
        for cid, msg in failures:
            print(f"  - {cid}: {msg}")
    return n
