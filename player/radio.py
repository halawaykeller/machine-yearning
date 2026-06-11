"""Headless radio player with channel cross-fade.

Single mpv instance is launched with --input-ipc-server pointed at a Unix
socket; we drive it from Python by sending JSON commands. Channel switches
are animated: fade out current → static burst → fade in new.

Channel-switch trigger today is stdin (1/2/3/4 keys). When the rotary pot
is wired, it'll call player.switch_to(channel_id) on the same Player object.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket as sock
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANNELS_FILE = REPO / "web" / "channels.json"
AUDIO_DIR = REPO / "data" / "normalized"
TRANSITIONS_DIR = REPO / "data" / "transitions"

DEFAULT_CHANNEL = "talk_to_me"
DEFAULT_DEVICE = "alsa/hw:1"
SOCKET_PATH = "/tmp/machine-yearning-mpv.sock"

# Cross-fade timings (ms)
FADE_OUT_MS = 400
FADE_IN_MS = 400
STATIC_FADE_MS = 200
STATIC_HEAD_TRIM_MS = 200  # leave a bit at the end of static to fade out

CHANNEL_KEY_MAP = {
    "1": "turn_me_on",
    "2": "charge_me",
    "3": "in_your_ear",
    "4": "talk_to_me",
}


class MPV:
    """Tiny JSON-IPC client over the mpv unix socket."""

    def __init__(self, sock_path: str):
        self.sock_path = sock_path
        self.sock: sock.socket | None = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self, retries: int = 40):
        for _ in range(retries):
            try:
                s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
                s.connect(self.sock_path)
                self.sock = s
                return
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        raise RuntimeError(f"could not connect to mpv socket {self.sock_path}")

    def command(self, *args) -> None:
        msg = json.dumps({"command": list(args)}).encode() + b"\n"
        with self._lock:
            self.sock.sendall(msg)

    def set_volume(self, vol: float) -> None:
        self.command("set_property", "volume", round(vol, 2))

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


def _ffprobe_duration(path: str) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return float(p.stdout.strip())
    except Exception:
        return 4.0


def _fade(mpv: MPV, from_vol: float, to_vol: float, duration_ms: int, steps: int = 16) -> None:
    if duration_ms <= 0 or from_vol == to_vol:
        mpv.set_volume(to_vol)
        return
    step_ms = duration_ms / steps
    for i in range(1, steps + 1):
        mpv.set_volume(from_vol + (to_vol - from_vol) * (i / steps))
        time.sleep(step_ms / 1000)


def _load_channels() -> tuple[dict[str, list[dict]], dict[str, str]]:
    if not CHANNELS_FILE.exists():
        sys.exit(f"channels.json not found at {CHANNELS_FILE}. "
                 "Run `python scripts/build_channels.py` first.")
    data = json.loads(CHANNELS_FILE.read_text())
    return data["channels"], data["titles"]


def _channel_files(channel: str, channels: dict[str, list[dict]]) -> list[str]:
    files = [str(AUDIO_DIR / Path(c["url"]).name) for c in channels[channel]]
    files = [f for f in files if Path(f).exists()]
    random.shuffle(files)
    return files


def _pick_transition() -> tuple[str, float] | None:
    files = sorted(TRANSITIONS_DIR.glob("*.mp3"))
    if not files:
        return None
    chosen = str(random.choice(files))
    return chosen, _ffprobe_duration(chosen)


class Player:
    def __init__(self, device: str):
        self.device = device
        self.channels, self.titles = _load_channels()
        self.current_channel: str | None = None
        self._mpv_proc: subprocess.Popen | None = None
        self._mpv: MPV | None = None
        self._switch_lock = threading.Lock()

    def start(self, channel: str) -> None:
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass
        cmd = [
            "mpv", "--no-video", "--no-config", "--idle=yes",
            f"--input-ipc-server={SOCKET_PATH}",
            f"--audio-device={self.device}",
            "--volume=100",
            "--loop-playlist=inf",
            "--keep-open=no",
            "--gapless-audio=yes",
        ]
        # Keep mpv's stderr so we can see playback errors
        mpv_log = open("/tmp/machine-yearning-mpv.log", "w")
        self._mpv_proc = subprocess.Popen(
            cmd, stdout=mpv_log, stderr=mpv_log
        )
        self._mpv = MPV(SOCKET_PATH)
        self._load_channel(channel)

    def _load_channel(self, channel: str) -> None:
        files = _channel_files(channel, self.channels)
        if not files:
            print(f"channel {channel!r} has no playable clips", file=sys.stderr)
            return
        self._mpv.command("loadfile", files[0], "replace")
        for f in files[1:]:
            self._mpv.command("loadfile", f, "append")
        self.current_channel = channel
        print(f"♪ {self.titles[channel]}  ({len(files)} clips)")

    def switch_to(self, channel: str) -> None:
        if channel == self.current_channel:
            return
        if channel not in self.channels:
            print(f"unknown channel: {channel!r}", file=sys.stderr)
            return
        with self._switch_lock:
            # Fade music out
            _fade(self._mpv, 100, 0, FADE_OUT_MS)
            # Play static, fade it up briefly
            t = _pick_transition()
            if t is not None:
                static_path, static_dur = t
                self._mpv.command("loadfile", static_path, "replace")
                _fade(self._mpv, 0, 80, STATIC_FADE_MS, steps=8)
                # Hold at volume for most of the static, then fade out
                hold_ms = max(200, int(static_dur * 1000) - STATIC_FADE_MS * 2 - STATIC_HEAD_TRIM_MS)
                time.sleep(hold_ms / 1000)
                _fade(self._mpv, 80, 0, STATIC_FADE_MS, steps=8)
            # Load new channel playlist while volume is at 0
            files = _channel_files(channel, self.channels)
            if not files:
                print(f"  ! no playable files for {channel}", file=sys.stderr)
                return
            print(f"  → loading {len(files)} files; first: {Path(files[0]).name}")
            self._mpv.command("playlist-clear")
            self._mpv.command("loadfile", files[0], "replace")
            for f in files[1:]:
                self._mpv.command("loadfile", f, "append")
            # Explicitly unpause in case loadfile left mpv paused
            self._mpv.command("set_property", "pause", False)
            # Give mpv a moment to actually start playback before the fade
            time.sleep(0.25)
            # FADE-IN DISABLED while we debug — just slam volume to 100.
            self._mpv.set_volume(100)
            time.sleep(0.05)
            self._mpv.set_volume(100)
            self.current_channel = channel
            print(f"♪ {self.titles[channel]}  ({len(files)} clips)")

    def stop(self) -> None:
        if self._mpv:
            self._mpv.close()
        if self._mpv_proc:
            self._mpv_proc.terminate()
            try:
                self._mpv_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._mpv_proc.kill()


def _interactive_loop(player: Player) -> None:
    print("\nChannels:")
    print("  1=turn_me_on   2=charge_me   3=in_your_ear   4=talk_to_me")
    print("  (also accepts full channel IDs, or 'q' to quit)\n")
    while True:
        try:
            line = input("> ").strip().lower()
        except EOFError:
            break
        if line in ("q", "quit", "exit"):
            break
        if not line:
            continue
        if line in CHANNEL_KEY_MAP:
            player.switch_to(CHANNEL_KEY_MAP[line])
        elif line in player.channels:
            player.switch_to(line)
        else:
            print(f"unknown: {line!r}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description="Machine Yearning radio player")
    p.add_argument("channel", nargs="?", default=DEFAULT_CHANNEL,
                   help=f"starting channel (default: {DEFAULT_CHANNEL})")
    p.add_argument("--device", default=DEFAULT_DEVICE,
                   help=f"mpv audio device (default: {DEFAULT_DEVICE})")
    p.add_argument("--list", action="store_true",
                   help="list channels and exit")
    p.add_argument("--no-input", action="store_true",
                   help="don't read stdin; play one channel and never switch "
                        "(use this for systemd autostart)")
    args = p.parse_args()

    if args.list:
        channels, titles = _load_channels()
        for cid, clips in channels.items():
            print(f"  {cid:14s}  {titles[cid]:24s}  {len(clips)} clips")
        return

    player = Player(args.device)
    try:
        player.start(args.channel)
        if args.no_input:
            # Keep the process alive while mpv plays
            while player._mpv_proc and player._mpv_proc.poll() is None:
                time.sleep(1)
        else:
            _interactive_loop(player)
    except KeyboardInterrupt:
        print()
    finally:
        player.stop()


if __name__ == "__main__":
    main()
