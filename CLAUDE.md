# Machine Yearning

A radio station built from machine sounds: boot chimes, low-battery beeps, fan hums, modem handshakes, error tones. The MVP is a web player with four channels. The endgame is an ESP32 inside a hacked 80s boombox.

## Channels (MVP taxonomy)

Each channel has a snake_case **ID** (used in manifests and `web/channels.json`) and a **display title** (the evocative phrase shown to the listener). Both live in `scraper/manifest.py` — `CHANNELS` and `CHANNEL_TITLES` are the single source of truth. Don't rename without migrating existing manifests.

- `turn_me_on` ("turn me on") — startup chimes, POST beeps, OS bootloader sounds, shutdown jingles. The "machine waking up / going to sleep" channel.
- `charge_me` ("charge me") — low-battery beeps, charge indicators, UPS alarms, plug/unplug chimes.
- `in_your_ear` ("put me in your ear") — cooling fans, HDD spin-up/seek, optical drives, server-room ambience. The "still alive" background channel.
- `talk_to_me` ("talk to me") — error chimes, modem handshakes, dial-up, fax tones, notification dings. "Something is trying to tell you something."

Target ~20–30 clips per channel for MVP.

## License rules — read before adding sources

- **Freesound**: only download clips with a CC license (`CC0`, `CC-BY`, `CC-BY-NC`, etc.). Filter via the API; never download `All Rights Reserved`. Always record the license + uploader attribution in the manifest.
- **archive.org**: only public-domain or CC-licensed items.
- **BBC Sound Effects**: their stated license restricts commercial reuse. OK for personal/art-show use; **re-check the current license before any public-web deployment**. Downloads gated behind `--accept-license`.
- **No YouTube.** Even with yt-dlp, the licensing for redistribution is unclear and risky. Don't add a YouTube source without a separate conversation.
- **Own recordings**: license `self`. Annotate generously — these are the rarest and most interesting clips.

Every clip manifest must include `source_url` (or `null` for own recordings) and `license_attribution` (required for CC-BY).

## Audio standard

All clips in `data/normalized/`:
- Mono
- MP3 @ 128 kbps
- 44.1 kHz
- Loudness-normalized to **-16 LUFS** (broadcast-ish; prevents jarring loud→quiet transitions)
- Silence trimmed at head and tail (threshold ≈ -50 dB)

`scraper/normalize.py` enforces this. Don't bypass it for "just one clip."

## Manifest schema

`scraper/manifest.py` is the **single source of truth**. Don't duplicate field lists in other files — import the Pydantic model. One JSON file per clip in `data/manifests/<id>.json`.

## CLI surface

```bash
# Scrape (per source, per channel)
python -m scraper freesound  --channel <id> --limit 30
python -m scraper archive    --channel <id> --limit 30
python -m scraper bbc        --channel <id> --limit 30 --accept-license
python -m scraper local ingest <path-to-audio-file>

# Normalize raw → normalized + update manifests
python -m scraper normalize [--id <clip_id>] [--force]

# Aggregate manifests into the web player's data file
python scripts/build_channels.py
```

## Dev loop

1. Scrape: `python -m scraper freesound --channel turn_me_on --limit 10`
2. Normalize: `python -m scraper normalize`
3. Build channel index: `python scripts/build_channels.py`
4. Serve: `python -m http.server -d web 8000` → open <http://localhost:8000>

## Project structure

- `scraper/` — Python pipeline. `manifest.py` is the schema; `sources/` per-source clients; `normalize.py` for ffmpeg; `cli.py` is the click entry point.
- `data/raw/<source>/` — original downloads, untouched. Gitignored.
- `data/normalized/` — post-ffmpeg, what the web player serves. Gitignored.
- `data/manifests/` — committed JSON metadata. **This is the editorial spine.** Edit by hand to fix mis-tagging.
- `scripts/build_channels.py` — aggregator, emits `web/channels.json`.
- `web/` — vanilla JS player. No build step.

## External tools

- `ffmpeg` and `ffprobe` must be on PATH.
- Freesound API key in `.env` (see `.env.example`).
