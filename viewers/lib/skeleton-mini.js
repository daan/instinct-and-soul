// skeleton-mini — a tiny 3D skeleton for the inset. Fixed camera (no controls),
// renders one frame on demand. Lifted from viewers/skeleton/skeleton.js.
import * as THREE from 'three';

export async function createSkeleton(container, mocapUrl) {
  const data = await fetch(mocapUrl).then(r => {
    if (!r.ok) throw new Error(`mocap ${mocapUrl} → ${r.status}`);
    return r.json();
  });
  const J = data.joint_names.length;
  const BONES = data.bones;
  const N = data.n_frames;
  const FPS = data.fps;

  const W = container.clientWidth || 200;
  const H = container.clientHeight || 150;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x14161a);
  const camera = new THREE.PerspectiveCamera(50, W / H, 0.01, 100);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(W, H);                 // updateStyle: true → element fits its box
  container.appendChild(renderer.domElement);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.5);
  sun.position.set(3, 5, 2);
  scene.add(sun);

  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;         // AMASS Z-up → three Y-up
  scene.add(root);

  const joints = [];
  for (let j = 0; j < J; j++) {
    const isWrist = data.joint_names[j].endsWith('_wrist');
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(isWrist ? 0.04 : 0.022, 10, 7),
      new THREE.MeshStandardMaterial({ color: isWrist ? 0xf4a261 : 0xcccccc, roughness: 0.6 })
    );
    root.add(m);
    joints.push(m);
  }
  const boneGeom = new THREE.BufferGeometry();
  const bonePos = new Float32Array(BONES.length * 6);
  boneGeom.setAttribute('position', new THREE.BufferAttribute(bonePos, 3));
  root.add(new THREE.LineSegments(boneGeom, new THREE.LineBasicMaterial({ color: 0x66aaff })));

  // Aim the fixed camera at the motion centroid (in world space).
  let sx = 0, sy = 0, sz = 0, n = 0;
  const step = Math.max(1, Math.floor(N / 200));
  for (let i = 0; i < N; i += step) {
    const p = data.frames[i].p;
    for (let j = 0; j < J; j++) { sx += p[j][0]; sy += p[j][1]; sz += p[j][2]; n++; }
  }
  const center = new THREE.Vector3(sx / n, sy / n, sz / n).applyEuler(root.rotation);
  camera.position.set(center.x + 2.0, center.y + 0.6, center.z + 2.0);
  camera.lookAt(center);

  function applyFrame(i) {
    i = Math.max(0, Math.min(N - 1, i | 0));
    const f = data.frames[i];
    for (let j = 0; j < J; j++) {
      const p = f.p[j], q = f.q[j];
      joints[j].position.set(p[0], p[1], p[2]);
      joints[j].quaternion.set(q[0], q[1], q[2], q[3]);
    }
    for (let b = 0; b < BONES.length; b++) {
      const [c, par] = BONES[b];
      const pc = f.p[c], pp = f.p[par];
      bonePos[b * 6 + 0] = pp[0]; bonePos[b * 6 + 1] = pp[1]; bonePos[b * 6 + 2] = pp[2];
      bonePos[b * 6 + 3] = pc[0]; bonePos[b * 6 + 4] = pc[1]; bonePos[b * 6 + 5] = pc[2];
    }
    boneGeom.attributes.position.needsUpdate = true;
    renderer.render(scene, camera);
  }

  applyFrame(0);
  return { setTime: (sec) => applyFrame(sec * FPS), fps: FPS, nFrames: N };
}
