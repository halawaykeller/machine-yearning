// ✿ Machine Yearning control surface ✿

const POLL_MS = 1500;
const VOLUME_DEBOUNCE_MS = 90;

const $ = (sel) => document.querySelector(sel);
const els = {
  channels: $("#channels"),
  vol: $("#vol"),
  volDisplay: $("#vol-display"),
  npTitle: $("#np-title"),
  npMeta: $("#np-meta"),
  npChannel: $("#np-channel"),
  viz: $("#viz"),
};

const state = {
  channels: [],
  current: null,
  pending: null,
  currentClip: null,    // {title, machine_type, license_attribution, source}
  volume: 100,
  online: false,
  volumeDirty: false,
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
    if (c.id === state.current && c.id !== state.pending) btn.classList.add("active");
    if (c.id === state.pending) btn.classList.add("pending");
    btn.innerHTML = `
      <span class="ch-num">CH 0${i + 1} · ${c.clip_count} clips</span>
      <span class="ch-name">${c.title}</span>
    `;
    btn.addEventListener("click", () => onChannelClick(c.id));
    els.channels.appendChild(btn);
  });
}

function renderNowPlaying() {
  const clip = state.currentClip;
  const isTuning = state.pending && state.pending !== state.current;
  const cur = state.channels.find((c) => c.id === state.current);

  if (isTuning) {
    const pen = state.channels.find((c) => c.id === state.pending);
    els.npTitle.innerHTML = `<i>…tuning…</i>`;
    els.npMeta.textContent = `switching to "${pen ? pen.title : state.pending}"`;
    els.npMeta.classList.remove("error");
    els.npChannel.textContent = pen ? pen.title : "—";
    els.viz.classList.remove("paused");
    els.viz.classList.add("tuning");
  } else if (!state.online) {
    els.npTitle.innerHTML = `<i>—</i>`;
    els.npMeta.innerHTML = `connecting<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;
    els.npChannel.textContent = "—";
    els.viz.classList.add("paused");
    els.viz.classList.remove("tuning");
  } else if (clip) {
    els.npTitle.innerHTML = `<i>${escapeHtml(clip.title)}</i>`;
    const bits = [];
    if (clip.machine_type && clip.machine_type !== "unknown") bits.push(clip.machine_type);
    if (clip.license_attribution) bits.push(`by ${clip.license_attribution}`);
    els.npMeta.textContent = bits.length ? bits.join(" · ") : " ";
    els.npMeta.classList.remove("error");
    els.npChannel.textContent = cur ? cur.title : "—";
    els.viz.classList.remove("paused", "tuning");
  } else {
    els.npTitle.innerHTML = `<i>—</i>`;
    els.npMeta.textContent = "waiting for the radio to warm up…";
    els.npMeta.classList.remove("error");
    els.npChannel.textContent = cur ? cur.title : "—";
    els.viz.classList.add("paused");
    els.viz.classList.remove("tuning");
  }
}

function renderVolume() {
  if (!state.volumeDirty) els.vol.value = state.volume;
  els.vol.style.setProperty("--vol", `${state.volume}%`);
  els.volDisplay.textContent = state.volume;
}

function renderAll() {
  renderChannels();
  renderNowPlaying();
  renderVolume();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ──────── actions ────────

async function onChannelClick(chId) {
  if (chId === state.current && !state.pending) return;
  state.pending = chId;
  renderAll();
  try {
    const r = await fetch(`/switch?ch=${encodeURIComponent(chId)}`, { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (e) {
    state.pending = null;
    els.npMeta.textContent = `switch failed: ${e.message}`;
    els.npMeta.classList.add("error");
    renderAll();
  }
}

function onVolumeInput() {
  state.volume = Number(els.vol.value);
  state.volumeDirty = true;
  renderVolume();
  clearTimeout(state.volumeTimer);
  state.volumeTimer = setTimeout(commitVolume, VOLUME_DEBOUNCE_MS);
}

function onVolumeRelease() {
  clearTimeout(state.volumeTimer);
  commitVolume();
  state.volumeDirty = false;
}

async function commitVolume() {
  try { await fetch(`/volume?v=${state.volume}`, { method: "POST" }); }
  catch (e) { /* swallow */ }
}

// ──────── polling ────────

async function poll() {
  try {
    const r = await fetch("/state", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.channels = data.channels;
    state.current = data.current_channel;
    state.currentClip = data.current_clip;
    if (data.current_channel === state.pending) state.pending = null;
    if (!state.volumeDirty) state.volume = data.volume;
    state.online = true;
  } catch (e) {
    state.online = false;
  }
  renderAll();
}

// ──────── boot ────────

els.vol.addEventListener("input", onVolumeInput);
els.vol.addEventListener("change", onVolumeRelease);
els.vol.addEventListener("pointerup", onVolumeRelease);

poll();
setInterval(poll, POLL_MS);
