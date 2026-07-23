// orient3d — the CoreS3Recorder device-orientation scene, as a tracer stage
// module. Ported from ../CoreS3Recorder/tools/web/index.html: device proxy
// with labeled screen face, device-frame axis arrows (x red = display right,
// y green = display top, z blue = out of the display), orbit controls, grid.
// Driven by a baked quaternion track ([t, w, x, y, z], session seconds):
// setTime(sec) slerps the proxy to the recorded attitude at that moment.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export function createOrient3d(container, quatTrack) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(2.6, 2.0, 2.6);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;
  controls.minDistance = 1.2;
  controls.maxDistance = 15;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x334, 1.2));
  const dir = new THREE.DirectionalLight(0xffffff, 1.5);
  dir.position.set(3, 5, 2);
  scene.add(dir);
  scene.add(new THREE.GridHelper(4, 8, 0x333340, 0x22222a));

  // Device proxy: CoreS3 footprint, screen face = device +Z.
  const device = new THREE.Group();
  device.add(new THREE.Mesh(
    new THREE.BoxGeometry(1.4, 0.35, 1.4),
    new THREE.MeshStandardMaterial({ color: 0x2a2a30, roughness: 0.6 })));
  const screen = new THREE.Mesh(
    new THREE.BoxGeometry(1.1, 0.03, 1.1),
    new THREE.MeshStandardMaterial({ color: 0x2f6fdb, emissive: 0x112233, roughness: 0.3 }));
  screen.position.y = 0.19;
  device.add(screen);

  function makeScreenTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 512;
    const g = c.getContext('2d');
    g.fillStyle = '#2f6fdb'; g.fillRect(0, 0, 512, 512);
    g.strokeStyle = 'rgba(255,255,255,.4)'; g.lineWidth = 6;
    g.strokeRect(12, 12, 488, 488);
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = 'bold 84px sans-serif'; g.fillText('DISPLAY', 256, 256);
    g.font = 'bold 52px sans-serif';
    g.fillText('↑ +Y', 256, 70);
    g.fillText('+X →', 400, 440);
    return new THREE.CanvasTexture(c);
  }
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(1.05, 1.05),
    new THREE.MeshBasicMaterial({ map: makeScreenTexture() }));
  label.rotation.x = -Math.PI / 2;
  label.position.y = 0.212;
  device.add(label);

  const axisLen = 1.2;
  device.add(new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), axisLen, 0xe5484d));   // device +X
  device.add(new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(), axisLen, 0x46a758));  // device +Y
  device.add(new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(), axisLen, 0x3b82f6));   // device +Z
  scene.add(device);

  function resize() {
    const w = container.clientWidth || 220, h = container.clientHeight || 220;
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  // Device frame is Z-up, three.js is Y-up: (x, y, z) -> (x, z, -y).
  const targetQ = new THREE.Quaternion();
  function setQuat(w, x, y, z) { targetQ.set(x, z, -y, w); }

  const T = quatTrack.map(q => q[0]);
  function setTime(sec) {
    if (!quatTrack.length) return;
    let lo = 0, hi = T.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; (T[m] < sec) ? lo = m + 1 : hi = m; }
    const q = quatTrack[Math.max(0, Math.min(quatTrack.length - 1, lo))];
    setQuat(q[1], q[2], q[3], q[4]);
  }

  let alive = true;
  (function animate() {
    if (!alive) return;
    requestAnimationFrame(animate);
    controls.update();
    device.quaternion.slerp(targetQ, 0.35);
    renderer.render(scene, camera);
  })();

  return { setTime, dispose() { alive = false; renderer.dispose(); } };
}
