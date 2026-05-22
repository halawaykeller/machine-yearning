// Machine Yearning — minimal radio player.
// Loads channels.json, shuffles per channel, plays clips with a small gap.

const CHANNEL_LABELS = {
  boot_shutdown: "Boot / Shutdown",
  power_battery: "Power & Battery",
  fans_drives:   "Fans & Drives",
  alerts_errors: "Alerts & Errors",
};

const INTER_CLIP_GAP_MS = 800;
const FADE_MS = 200;

const state = {
  channels: {},        // id -> array of clip objects
  currentChannel: null,
  queue: [],           // shuffled clip ids for current channel
  cursor: 0,
  playing: false,
  audio: new Audio(),
  gapTimer: null,
};

state.audio.preload = "auto";

// ---------- bootstrap ----------

async function init() {
  try {
    const res = await fetch("channels.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.channels = await res.json();
  } catch (e) {
    setDisplay({ title: "channels.json not found — run scripts/build_channels.py" });
    console.error(e);
    return;
  }

  renderChannels();
  wireControls();
}

function renderChannels() {
  const bank = document.getElementById("channel-bank");
  bank.innerHTML = "";
  let i = 1;
  for (const id of Object.keys(CHANNEL_LABELS)) {
    const count = (state.channels[id] || []).length;
    const btn = document.createElement("button");
    btn.className = "channel-btn";
    btn.type = "button";
    btn.dataset.channel = id;
    btn.disabled = count === 0;
    btn.innerHTML = `
      <span class="ch-num">CH ${String(i).padStart(2, "0")} · ${count} clips</span>
      <span class="ch-name">${CHANNEL_LABELS[id]}</span>
    `;
    btn.addEventListener("click", () => selectChannel(id));
    bank.appendChild(btn);
    i++;
  }
}

function wireControls() {
  document.getElementById("btn-toggle").addEventListener("click", togglePlay);
  document.getElementById("btn-skip").addEventListener("click", skip);
  state.audio.addEventListener("ended", onClipEnded);
  state.audio.addEventListener("error", (e) => {
    console.warn("audio error", e, state.audio.src);
    onClipEnded();
  });
}

// ---------- channel selection ----------

function selectChannel(channelId) {
  const clips = state.channels[channelId] || [];
  if (clips.length === 0) return;

  if (state.currentChannel === channelId) {
    if (!state.playing) startPlayback();
    return;
  }

  // Fade out current clip, then switch
  fadeOut(() => {
    state.currentChannel = channelId;
    state.queue = shuffle(clips.map(c => c.id));
    state.cursor = 0;

    document.querySelectorAll(".channel-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.channel === channelId);
    });
    document.getElementById("channel-name").textContent = CHANNEL_LABELS[channelId];
    document.getElementById("channel-stats").textContent = `${clips.length} clips`;

    startPlayback();
  });
}

// ---------- playback ----------

function startPlayback() {
  clearTimeout(state.gapTimer);
  state.playing = true;
  document.getElementById("signal-dot").classList.add("on");
  document.getElementById("btn-toggle").textContent = "❚❚";
  playCurrent();
}

function stopPlayback() {
  clearTimeout(state.gapTimer);
  state.playing = false;
  state.audio.pause();
  document.getElementById("signal-dot").classList.remove("on");
  document.getElementById("btn-toggle").textContent = "▶";
}

function togglePlay() {
  if (!state.currentChannel) {
    // Pick the first non-empty channel
    const first = Object.keys(CHANNEL_LABELS).find(c => (state.channels[c] || []).length > 0);
    if (first) selectChannel(first);
    return;
  }
  if (state.playing) stopPlayback();
  else startPlayback();
}

function skip() {
  if (!state.currentChannel) return;
  fadeOut(() => {
    advanceCursor();
    if (state.playing) playCurrent();
  });
}

function playCurrent() {
  const clip = currentClip();
  if (!clip) return;
  state.audio.src = clip.url;
  state.audio.volume = 1.0;
  setDisplay(clip);
  updateCounter();
  state.audio.play().catch(err => {
    // Autoplay blocked or 404 — log and move on
    console.warn("play failed:", err);
    state.gapTimer = setTimeout(onClipEnded, 400);
  });
}

function onClipEnded() {
  if (!state.playing) return;
  state.gapTimer = setTimeout(() => {
    advanceCursor();
    playCurrent();
  }, INTER_CLIP_GAP_MS);
}

function advanceCursor() {
  state.cursor++;
  if (state.cursor >= state.queue.length) {
    // Reshuffle when we exhaust the queue
    state.queue = shuffle(state.queue);
    state.cursor = 0;
  }
}

function currentClip() {
  const id = state.queue[state.cursor];
  return (state.channels[state.currentChannel] || []).find(c => c.id === id);
}

// ---------- ui helpers ----------

function setDisplay(clip) {
  document.getElementById("now-title").textContent = clip?.title || "—";

  const machine = clip?.machine_specifics
    ? `${clip.machine_type} — ${clip.machine_specifics}`
    : clip?.machine_type || "—";
  document.getElementById("now-machine").textContent = machine;

  const lic = clip?.license || "—";
  const attr = clip?.license_attribution ? ` · ${clip.license_attribution}` : "";
  document.getElementById("now-license").textContent = lic + attr;

  const srcEl = document.getElementById("now-source");
  if (clip?.source_url) {
    srcEl.textContent = clip.source;
    srcEl.href = clip.source_url;
  } else {
    srcEl.textContent = clip?.source || "—";
    srcEl.removeAttribute("href");
  }
}

function updateCounter() {
  const n = state.queue.length;
  if (!n) {
    document.getElementById("counter").textContent = "—";
    return;
  }
  document.getElementById("counter").textContent =
    `${String(state.cursor + 1).padStart(2, "0")} / ${String(n).padStart(2, "0")}`;
}

function fadeOut(onDone) {
  if (state.audio.paused || state.audio.volume === 0) {
    onDone?.();
    return;
  }
  const steps = 8;
  const stepMs = FADE_MS / steps;
  const start = state.audio.volume;
  let i = 0;
  const t = setInterval(() => {
    i++;
    state.audio.volume = Math.max(0, start * (1 - i / steps));
    if (i >= steps) {
      clearInterval(t);
      state.audio.pause();
      state.audio.volume = 1.0;
      onDone?.();
    }
  }, stepMs);
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

init();
