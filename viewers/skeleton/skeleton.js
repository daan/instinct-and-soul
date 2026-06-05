import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { state, bus, setFrame, setPlaying } from './state.js';

const JOINT_RADIUS = 0.025;
const AXIS_LEN = 0.06;

const canvasWrap = document.getElementById('canvas-wrap');
const hud = document.getElementById('hud');
const playBtn = document.getElementById('play');
const frameLabel = document.getElementById('frame-label');

const { data, N, FPS } = state;
const J = data.joint_names.length;
const BONES = data.bones;

hud.textContent = `${J} joints • ${N} frames @ ${FPS} fps`;
frameLabel.textContent = `0 / ${N - 1}`;

// ---- Three.js setup ---------------------------------------------------------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);

const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
camera.position.set(2.4, 1.6, 2.4);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
canvasWrap.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1, 0);
controls.update();

scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 0.5);
sun.position.set(3, 5, 2);
scene.add(sun);

scene.add(new THREE.GridHelper(6, 12, 0x444444, 0x222222));

// Root group: Z-up AMASS data → Y-up Three.js view.
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2;
scene.add(root);

function resize() {
  const w = canvasWrap.clientWidth;
  const h = canvasWrap.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

// ---- Skeleton ---------------------------------------------------------------
const LEFT  = new THREE.Color(0xf4a261);
const RIGHT = new THREE.Color(0x2a9d8f);
const DEFAULT = new THREE.Color(0xcccccc);

function jointColor(name) {
  if (name === 'l_wrist') return LEFT;
  if (name === 'r_wrist') return RIGHT;
  return DEFAULT;
}

const joints = [];
for (let j = 0; j < J; j++) {
  const g = new THREE.Group();
  const isWrist = data.joint_names[j].endsWith('_wrist');
  g.add(new THREE.Mesh(
    new THREE.SphereGeometry(isWrist ? JOINT_RADIUS * 1.6 : JOINT_RADIUS, 12, 8),
    new THREE.MeshStandardMaterial({ color: jointColor(data.joint_names[j]), roughness: 0.6 })
  ));
  g.add(new THREE.AxesHelper(AXIS_LEN));
  root.add(g);
  joints.push(g);
}

const boneGeom = new THREE.BufferGeometry();
const bonePositions = new Float32Array(BONES.length * 2 * 3);
boneGeom.setAttribute('position', new THREE.BufferAttribute(bonePositions, 3));
const bones = new THREE.LineSegments(
  boneGeom,
  new THREE.LineBasicMaterial({ color: 0x66aaff })
);
root.add(bones);

function applyFrame(i) {
  const f = data.frames[i];
  for (let j = 0; j < J; j++) {
    const p = f.p[j];
    const q = f.q[j];
    joints[j].position.set(p[0], p[1], p[2]);
    joints[j].quaternion.set(q[0], q[1], q[2], q[3]);
  }
  for (let b = 0; b < BONES.length; b++) {
    const [c, par] = BONES[b];
    const pc = f.p[c], pp = f.p[par];
    bonePositions[b * 6 + 0] = pp[0];
    bonePositions[b * 6 + 1] = pp[1];
    bonePositions[b * 6 + 2] = pp[2];
    bonePositions[b * 6 + 3] = pc[0];
    bonePositions[b * 6 + 4] = pc[1];
    bonePositions[b * 6 + 5] = pc[2];
  }
  boneGeom.attributes.position.needsUpdate = true;
  frameLabel.textContent = `${i} / ${N - 1}  (${(i / FPS).toFixed(2)}s)`;
}

// ---- Wire up state ----------------------------------------------------------
bus.addEventListener('frame', (e) => applyFrame(e.detail));
bus.addEventListener('play', (e) => {
  playBtn.textContent = e.detail ? '❚❚' : '▶';
});

playBtn.addEventListener('click', () => setPlaying(!state.playing));
window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    setPlaying(!state.playing);
  }
});

// ---- Render / playback loop -------------------------------------------------
let lastT = performance.now();
let playFrame = 0;

function tick(now) {
  const dt = (now - lastT) / 1000;
  lastT = now;
  if (state.playing) {
    playFrame += dt * FPS;
    if (playFrame >= N) playFrame -= N;
    setFrame(playFrame);
  } else {
    playFrame = state.frame;
  }
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}

resize();
applyFrame(0);
requestAnimationFrame(tick);
