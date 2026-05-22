# Machine Yearning

A radio station of machine sounds. Four channels of beeps, hums, chimes, and handshakes scraped from CC-licensed corners of the internet and recorded around the apartment.

MVP: web player. Long-term: ESP32 inside a hacked 80s boombox.

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure
cp .env.example .env
# edit .env to add your Freesound API key (https://freesound.org/apiv2/apply/)

# 3. Make sure ffmpeg is on PATH
ffmpeg -version

# 4. Scrape, normalize, build, serve
python -m scraper freesound --channel boot_shutdown --limit 10
python -m scraper normalize
python scripts/build_channels.py
python -m http.server -d web 8000
# open http://localhost:8000
```

See `CLAUDE.md` for conventions, license rules, and the audio standard.
