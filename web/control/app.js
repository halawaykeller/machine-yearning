// Machine Yearning — control surface
// Polls /state, posts /switch and /volume.

const POLL_MS = 1500;
const VOLUME_DEBOUNCE_MS = 90;

const $ = (sel) => document.querySelector(sel);
const els = {
  channels: $("#channels"),
  vol: $("#vol"),
  signalDot: $("#signal-dot"),
  nowChannel: $("#now-channel"),
  nowCount: $("#now-count"),
  nowVol: $("#now-vol"),
  status: $("#status"),
};

const state = {
  channels: [],
  current: null,
  pending: null,
  volume: 100,
  online: false,
  volumeDirty: false,    // true while user is actively dragging
  volumeTimer: null,
};

// ──────── rendering ────────

function renderChannels() {
  els.channels.innerHTML = "";
  state.channels.forEach((c, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ch";
    btn.dataset.ch = c.id;
    btn.disabled = c.clip_count === 0;
    if (c.id === state.current) btn.classList.add("active");
    if (c.id === state.pending) btn.classList.add("pending");
    btn.innerHTML = `
      <span class="ch-num">CH ${String(i + 1).padStart(2, "0")} · ${c.clip_count} clips</span>
      <span class="ch-name">${c.title}</span>
    `;
    btn.addEventListener("click", () => onChannelClick(c.id));
    els.channels.appendChild(btn);
  });
}

function renderDisplay() {
  const cur = state.channels.find((c) => c.id === state.current);
  const pen = state.channels.find((c) => c.id === state.pending);
  if (pen && pen.id !== state.current) {
    els.nowChannel.textContent = `→ ${pen.title}…`;
    els.nowCount.textContent = `${pen.clip_count}`;
  } else if (cur) {
    els.nowChannel.textContent = cur.title;
    els.nowCount.textContent = `${cur.clip_count}`;
  } else {
    els.nowChannel.textContent = "—";
    els.nowCount.textContent = "—";
  }
  els.nowVol.textContent = `${state.volume}`;
}

function renderVolume() {
  if (!state.volumeDirty) {
    els.vol.value = state.volume;
  }
  const pct = (state.volume / 100) * 100;
  els.vol.style.setProperty("--vol", `${pct}%`);
}

function renderSignal() {
  els.signalDot.classList.toggle("off", !state.online);
}

function renderStatus(text, kind) {
  els.status.textContent = text;
  els.status.className = "status" + (kind ? " " + kind : "");
}

function renderAll() {
  renderChannels();
  renderDisplay();
  renderVolume();
  renderSignal();
}

// ──────── actions ────────

async function onChannelClick(chId) {
  if (chId === state.current && !state.pending) return;
  state.pending = chId;
  renderAll();
  renderStatus(`tuning to "${state.channels.find(c => c.id === chId)?.title}"…`);
  try {
    const r = await fetch(`/switch?ch=${encodeURIComponent(chId)}`, { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (e) {
    state.pending = null;
    renderStatus(`switch failed: ${e.message}`, "error");
    renderAll();
  }
}

function onVolumeInput() {
  state.volume = Number(els.vol.value);
  state.volumeDirty = true;
  renderDisplay();
  renderVolume();
  clearTimeout(state.volumeTimer);
  state.volumeTimer = setTimeout(commitVolume, VOLUME_DEBOUNCE_MS);
}

function onVolumeRelease() {
  // Final commit on release
  clearTimeout(state.volumeTimer);
  commitVolume();
  state.volumeDirty = false;
}

async function commitVolume() {
  try {
    await fetch(`/volume?v=${state.volume}`, { method: "POST" });
  } catch (e) {
    renderStatus(`vol send failed: ${e.message}`, "error");
  }
}

// ──────── polling ────────

async function poll() {
  try {
    const r = await fetch("/state", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.channels = data.channels;
    if (data.current_channel === state.pending) {
      state.pending = null;
      renderStatus("ready", "ok");
    } else if (state.pending) {
      // still tuning
    } else {
      renderStatus("ready", "ok");
    }
    state.current = data.current_channel;
    if (!state.volumeDirty) state.volume = data.volume;
    state.online = true;
  } catch (e) {
    state.online = false;
    renderStatus("offline", "error");
  }
  renderAll();
}

// ──────── boot ────────

els.vol.addEventListener("input", onVolumeInput);
els.vol.addEventListener("change", onVolumeRelease);
els.vol.addEventListener("pointerup", onVolumeRelease);

poll();
setInterval(poll, POLL_MS);
