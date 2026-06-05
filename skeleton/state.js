// Shared playback state across the 3D viewer and the D3 charts.
// Data is loaded here so both modules block on the same promise.

// Path comes from the `skeleton` server via ?data=…; falls back to the sample.
const DATA_URL = new URLSearchParams(location.search).get('data')
  || '/data/mocap/out/Vasso_Happy_01_stageii.json';

const data = await fetch(DATA_URL).then(r => {
  if (!r.ok) throw new Error(`failed to load ${DATA_URL}: ${r.status}`);
  return r.json();
});

export const bus = new EventTarget();

export const state = {
  data,
  frame: 0,
  playing: false,
  N: data.n_frames,
  FPS: data.fps,
};

export function setFrame(f) {
  const clamped = Math.max(0, Math.min(state.N - 1, f | 0));
  if (clamped === state.frame) return;
  state.frame = clamped;
  bus.dispatchEvent(new CustomEvent('frame', { detail: clamped }));
}

export function setPlaying(p) {
  if (p === state.playing) return;
  state.playing = p;
  bus.dispatchEvent(new CustomEvent('play', { detail: p }));
}
