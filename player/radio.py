"""Headless radio player.

Loads web/channels.json, shuffles one channel's clips, plays them via mpv
through the configured ALSA device. Designed for the Pi (MAX98357A on
card 1 by default) but works anywhere mpv is installed.

Usage:
    python -m player.radio                  # default channel
    python -m player.radio talk_to_me       # specific channel
    python -m player.radio --list           # show available channels
    python -m player.radio --device alsa/default
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANNELS_FILE = REPO / "web" / "channels.json"
AUDIO_DIR = REPO / "data" / "normalized"

DEFAULT_CHANNEL = "talk_to_me"
DEFAULT_DEVICE = "alsa/hw:1"


def load_channels() -> tuple[dict[str, list[dict]], dict[str, str]]:
    if not CHANNELS_FILE.exists():
        sys.exit(
            f"channels.json not found at {CHANNELS_FILE}. "
            "Run `python scripts/build_channels.py` first."
        )
    data = json.loads(CHANNELS_FILE.read_text())
    return data["channels"], data["titles"]


def play_channel(channel_id: str, device: str) -> None:
    channels, titles = load_channels()
    if channel_id not in channels:
        sys.exit(f"unknown channel: {channel_id!r}. "
                 f"Available: {', '.join(channels)}")
    clips = channels[channel_id]
    if not clips:
        sys.exit(f"channel {channel_id!r} has no clips.")

    files = [str(AUDIO_DIR / Path(c["url"]).name) for c in clips]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        print(f"warning: {len(missing)} clip file(s) missing from {AUDIO_DIR}",
              file=sys.stderr)
        files = [f for f in files if Path(f).exists()]
        if not files:
            sys.exit("no playable clips. Did you rsync data/normalized/ over?")

    print(f"♪ {titles[channel_id]} — {len(files)} clips, shuffling forever "
          f"(Ctrl-C to stop)")

    try:
        subprocess.run(
            [
                "mpv", "--no-video", "--no-config",
                "--loop-playlist=inf", "--shuffle",
                f"--audio-device={device}",
                *files,
            ],
            check=True,
        )
    except KeyboardInterrupt:
        print("\n— stopped")
    except FileNotFoundError:
        sys.exit("mpv not found. Install it: `sudo apt install mpv`")
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


def main() -> None:
    p = argparse.ArgumentParser(description="Machine Yearning radio player")
    p.add_argument("channel", nargs="?", default=DEFAULT_CHANNEL,
                   help=f"channel ID (default: {DEFAULT_CHANNEL})")
    p.add_argument("--device", default=DEFAULT_DEVICE,
                   help=f"mpv/ALSA audio device (default: {DEFAULT_DEVICE})")
    p.add_argument("--list", action="store_true",
                   help="list available channels and exit")
    args = p.parse_args()

    if args.list:
        channels, titles = load_channels()
        print("Available channels:")
        for cid, clips in channels.items():
            print(f"  {cid:14s}  {titles[cid]:24s}  {len(clips)} clips")
        return

    play_channel(args.channel, args.device)


if __name__ == "__main__":
    main()
