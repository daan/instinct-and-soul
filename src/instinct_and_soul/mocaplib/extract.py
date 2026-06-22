"""Extract per-frame joint positions/orientations + synthetic IMU from mocap.

`bake-mocap <raw.npz|clip.bvh>` reads an AMASS stage-II .npz or a BVH file
(e.g. a stitched loop from the bvh-stitch repo), runs forward kinematics,
synthesizes both wrists' IMU (device units + range), and writes a self-contained
**clip directory** under data/mocap/<stem>/:

    data/mocap/<stem>/
      source.bvh|.npz      # the input, copied in (the regeneration root)
      skeleton_view.json   # stride-decimated skeleton + IMU, for the viewer
      imu_left.jsonl       # full-rate left-wrist  {t, ax..az, gx..gz}
      imu_right.jsonl      # full-rate right-wrist  (acc in g, gyro in deg/s)
      clip.json            # manifest (fps, frames, source, regen command)

The heavy full-rate skeleton (every joint, every frame) is *not* written by
default — re-bake from source for it (`bake-mocap <dir>/source.* --full`). The
viewer reads the decimated skeleton_view.json; the simulator reads imu_*.jsonl.

`skeleton_view.json` schema:
{
  fps, n_frames, joint_names, parents, bones,
  frames: [ { p: [[x,y,z]*J], q: [[x,y,z,w]*J] }, ... ],
  imu: { left: {acc, gyro}, right: {acc, gyro} }   # acc in g, gyro in deg/s
}

Coordinate frame: AMASS world (Z-up, meters). BVH input (Y-up, arbitrary
units) is scaled by the dancer's rest-pose height and rotated to match.
For BVH the virtual sensor is a *watch*: distal forearm position, FOREARM
bone orientation (wrist flexion does not contaminate the signal).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from . import find_repo_root

# SMPL/SMPL-X body skeleton (first 22 joints; hands/face omitted).
JOINT_NAMES = [
    "pelvis",       # 0
    "l_hip", "r_hip", "spine1",         # 1-3
    "l_knee", "r_knee", "spine2",       # 4-6
    "l_ankle", "r_ankle", "spine3",     # 7-9
    "l_foot", "r_foot", "neck",         # 10-12
    "l_collar", "r_collar", "head",     # 13-15
    "l_shoulder", "r_shoulder",         # 16-17
    "l_elbow", "r_elbow",               # 18-19
    "l_wrist", "r_wrist",               # 20-21
]

PARENTS = np.array([
    -1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19
])

# Parent-relative rest offsets in SMPL canonical frame (Y-up, meters).
# Approximate neutral proportions; bone lengths only — rotations are unaffected.
BONE_OFFSETS = np.array([
    [ 0.000,  0.000,  0.000],   # 0  pelvis (root; offset unused)
    [ 0.090, -0.090,  0.000],   # 1  l_hip       from pelvis
    [-0.090, -0.090,  0.000],   # 2  r_hip       from pelvis
    [ 0.000,  0.120,  0.000],   # 3  spine1      from pelvis
    [ 0.000, -0.400,  0.000],   # 4  l_knee      from l_hip
    [ 0.000, -0.400,  0.000],   # 5  r_knee      from r_hip
    [ 0.000,  0.140,  0.000],   # 6  spine2      from spine1
    [ 0.000, -0.400,  0.030],   # 7  l_ankle     from l_knee
    [ 0.000, -0.400,  0.030],   # 8  r_ankle     from r_knee
    [ 0.000,  0.060,  0.000],   # 9  spine3      from spine2
    [ 0.000, -0.060,  0.130],   # 10 l_foot      from l_ankle
    [ 0.000, -0.060,  0.130],   # 11 r_foot      from r_ankle
    [ 0.000,  0.215,  0.000],   # 12 neck        from spine3
    [ 0.080,  0.180,  0.000],   # 13 l_collar    from spine3
    [-0.080,  0.180,  0.000],   # 14 r_collar    from spine3
    [ 0.000,  0.090,  0.020],   # 15 head        from neck
    [ 0.110, -0.020,  0.000],   # 16 l_shoulder  from l_collar
    [-0.110, -0.020,  0.000],   # 17 r_shoulder  from r_collar
    [ 0.260, -0.040, -0.010],   # 18 l_elbow     from l_shoulder
    [-0.260, -0.040, -0.010],   # 19 r_elbow     from r_shoulder
    [ 0.260, -0.020,  0.000],   # 20 l_wrist     from l_elbow
    [-0.260, -0.020,  0.000],   # 21 r_wrist     from r_elbow
])

BONES = [(int(c), int(PARENTS[c])) for c in range(1, 22)]


def axis_angle_to_matrix(aa: np.ndarray) -> np.ndarray:
    """Rodrigues. aa: (..., 3). Returns (..., 3, 3)."""
    theta = np.linalg.norm(aa, axis=-1, keepdims=True)
    safe = np.where(theta < 1e-8, 1.0, theta)
    k = aa / safe
    kx, ky, kz = k[..., 0], k[..., 1], k[..., 2]
    K = np.stack([
        np.stack([np.zeros_like(kx), -kz,  ky], axis=-1),
        np.stack([ kz, np.zeros_like(kx), -kx], axis=-1),
        np.stack([-ky,  kx, np.zeros_like(kx)], axis=-1),
    ], axis=-2)
    I = np.broadcast_to(np.eye(3), K.shape).copy()
    s = np.sin(theta)[..., None]
    c = np.cos(theta)[..., None]
    R = I + s * K + (1 - c) * (K @ K)
    # When theta≈0, R should be identity; the formula already gives that.
    return R


def matrix_to_quat_xyzw(R: np.ndarray) -> np.ndarray:
    """Convert (..., 3, 3) rotation matrices to (..., 4) quaternions [x, y, z, w]."""
    m = R
    t = m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2]
    q = np.empty(m.shape[:-2] + (4,), dtype=m.dtype)

    cond_t = t > 0
    s = np.sqrt(np.where(cond_t, t + 1.0, 1.0)) * 2
    q_t = np.stack([
        (m[..., 2, 1] - m[..., 1, 2]) / s,
        (m[..., 0, 2] - m[..., 2, 0]) / s,
        (m[..., 1, 0] - m[..., 0, 1]) / s,
        0.25 * s,
    ], axis=-1)

    # Fallback: per-element computation when t<=0. The per-element path is
    # rarely hit (only near 180° rotations) so a small loop is fine.
    flat_R = m.reshape(-1, 3, 3)
    flat_cond = cond_t.reshape(-1)
    flat_q = q_t.reshape(-1, 4).copy()
    for i in range(flat_R.shape[0]):
        if flat_cond[i]:
            continue
        Ri = flat_R[i]
        d0, d1, d2 = Ri[0, 0], Ri[1, 1], Ri[2, 2]
        if d0 > d1 and d0 > d2:
            s = np.sqrt(1.0 + d0 - d1 - d2) * 2
            flat_q[i] = [
                0.25 * s,
                (Ri[0, 1] + Ri[1, 0]) / s,
                (Ri[0, 2] + Ri[2, 0]) / s,
                (Ri[2, 1] - Ri[1, 2]) / s,
            ]
        elif d1 > d2:
            s = np.sqrt(1.0 + d1 - d0 - d2) * 2
            flat_q[i] = [
                (Ri[0, 1] + Ri[1, 0]) / s,
                0.25 * s,
                (Ri[1, 2] + Ri[2, 1]) / s,
                (Ri[0, 2] - Ri[2, 0]) / s,
            ]
        else:
            s = np.sqrt(1.0 + d2 - d0 - d1) * 2
            flat_q[i] = [
                (Ri[0, 2] + Ri[2, 0]) / s,
                (Ri[1, 2] + Ri[2, 1]) / s,
                0.25 * s,
                (Ri[1, 0] - Ri[0, 1]) / s,
            ]
    q = flat_q.reshape(m.shape[:-2] + (4,))
    # Normalize.
    q /= np.linalg.norm(q, axis=-1, keepdims=True)
    return q


def forward_kinematics(root_orient: np.ndarray, pose_body: np.ndarray,
                       trans: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute world joint positions and rotation matrices.

    Args:
        root_orient: (T, 3) axis-angle for joint 0.
        pose_body:   (T, 63) axis-angle for joints 1..21.
        trans:       (T, 3) world translation of the pelvis.

    Returns:
        positions: (T, 22, 3)
        rot_world: (T, 22, 3, 3)
    """
    T = root_orient.shape[0]
    aa = np.concatenate([root_orient[:, None, :], pose_body.reshape(T, 21, 3)], axis=1)  # (T,22,3)
    R_local = axis_angle_to_matrix(aa)  # (T,22,3,3)

    R_world = np.zeros_like(R_local)
    pos = np.zeros((T, 22, 3), dtype=R_local.dtype)

    R_world[:, 0] = R_local[:, 0]
    pos[:, 0] = trans

    for j in range(1, 22):
        p = PARENTS[j]
        R_world[:, j] = R_world[:, p] @ R_local[:, j]
        # Bone offset is in SMPL canonical (Y-up). AMASS's root_orient already
        # includes the Y-up → Z-up rotation, so propagating offsets through the
        # world rotations lands them in AMASS world (Z-up) correctly.
        offset = BONE_OFFSETS[j]
        pos[:, j] = pos[:, p] + np.einsum('tij,j->ti', R_world[:, p], offset)

    return pos, R_world


def matrix_to_rotvec(R: np.ndarray) -> np.ndarray:
    """Inverse of Rodrigues. R: (..., 3, 3) → (..., 3) rotation vector (axis * angle)."""
    trace = R[..., 0, 0] + R[..., 1, 1] + R[..., 2, 2]
    cos_t = np.clip((trace - 1.0) * 0.5, -1.0, 1.0)
    theta = np.arccos(cos_t)
    sin_t = np.sin(theta)
    # Skew components, used for both regular and small-angle cases.
    rx = R[..., 2, 1] - R[..., 1, 2]
    ry = R[..., 0, 2] - R[..., 2, 0]
    rz = R[..., 1, 0] - R[..., 0, 1]
    small = sin_t < 1e-6
    safe = np.where(small, 1.0, 2.0 * sin_t)
    vec = np.stack([rx / safe, ry / safe, rz / safe], axis=-1) * theta[..., None]
    # Small-angle limit: log(R) ≈ (R - R^T) / 2  (already encoded in rx/ry/rz/2).
    vec_small = np.stack([rx * 0.5, ry * 0.5, rz * 0.5], axis=-1)
    return np.where(small[..., None], vec_small, vec)


G = 9.81  # m/s² per g — gravity magnitude, also the accel unit conversion.

# Real BMI270 limits (M5StickS3/CoreS3 default full-scale ranges). The physical
# chip saturates here, so the synthetic signal must too — otherwise the
# differentiation noise floor sits orders of magnitude above anything the device
# can actually report. See instinct-and-soul/test/CORES3/calibrate_imu.
ACCEL_CLIP_G = 8.0       # ±8 g  (BMI270 default accel FSR)
GYRO_CLIP_DPS = 2000.0   # ±2000 deg/s (BMI270 default gyro FSR)

# Low-pass cutoff applied before clamping. Differentiating 120 fps mocap
# amplifies per-frame reconstruction jitter into huge spurious accelerations
# (raw p90 ≈ 12 g, max ≈ 770 g — none of it real). Human limb motion lives
# below ~10-15 Hz, so a gentle low-pass removes the synthesis noise while
# preserving real dance accents. Smoothing commutes with the (linear) finite
# differences, so filtering the world-frame acceleration is equivalent to
# pre-smoothing positions, but keeps the gravity vector exact.
LOWPASS_HZ = 12.0


def _gaussian_smooth(x: np.ndarray, sigma_frames: float) -> np.ndarray:
    """Low-pass each column of x (T, C) with a Gaussian kernel along time.

    Reflect-padded at both ends so the signal isn't pulled toward zero there.
    sigma_frames <= 0 is a no-op.
    """
    if sigma_frames <= 0:
        return x
    radius = int(max(1, round(3.0 * sigma_frames)))
    if radius >= x.shape[0]:
        return x
    t = np.arange(-radius, radius + 1)
    k = np.exp(-0.5 * (t / sigma_frames) ** 2)
    k /= k.sum()
    pad = np.concatenate([x[radius:0:-1], x, x[-2:-radius - 2:-1]], axis=0)
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        out[:, c] = np.convolve(pad[:, c], k, mode="valid")
    return out


def synthesize_imu(pos: np.ndarray, R: np.ndarray, fps: float, *,
                   lowpass_hz: float = LOWPASS_HZ,
                   accel_clip_g: float = ACCEL_CLIP_G,
                   gyro_clip_dps: float = GYRO_CLIP_DPS) -> dict:
    """Compute accelerometer and gyroscope signals for one sensor.

    Output units and range match the real M5StickS3/CoreS3 BMI270 (measured
    2026-06-05, see instinct-and-soul/test/CORES3/calibrate_imu): accelerometer
    in **g** (1 g ≈ 9.81 m/s²; reads ≈ +1 g along the up axis at rest, opposing
    gravity), gyroscope in **deg/s**, both low-passed and clamped to the chip's
    full-scale range. This lets the output feed the creature simulator's
    NpzImuSource directly, which expects g + deg/s.

    Args:
        pos: (T, 3) world-frame sensor positions (joint center).
        R:   (T, 3, 3) world-frame sensor orientations (sensor-to-world).
        fps: sample rate (Hz).
        lowpass_hz: Gaussian low-pass cutoff (Hz) applied to the synthesized
            acceleration and angular velocity to suppress mocap differentiation
            noise. None or <= 0 disables it.
        accel_clip_g: per-axis accelerometer saturation (g). None disables.
        gyro_clip_dps: per-axis gyroscope saturation (deg/s). None disables.

    Returns:
        {"acc": (T, 3) in g, "gyro": (T, 3) in deg/s} — both in sensor-local frame.
    """
    dt = 1.0 / fps
    g_world = np.array([0.0, 0.0, -G])

    # World-frame linear acceleration via central 2nd difference.
    a_world = np.zeros_like(pos)
    a_world[1:-1] = (pos[:-2] - 2.0 * pos[1:-1] + pos[2:]) / (dt * dt)
    a_world[0] = a_world[1]
    a_world[-1] = a_world[-2]

    # Body-frame angular velocity via central log-map difference.
    # ΔR_body[t] = R[t-1]^T @ R[t+1]; ω ≈ log(ΔR_body) / (2 dt).
    R_prev = R[:-2]
    R_next = R[2:]
    R_rel = np.einsum("tji,tjk->tik", R_prev, R_next)
    gyro_sensor = np.zeros_like(pos)
    gyro_sensor[1:-1] = matrix_to_rotvec(R_rel) / (2.0 * dt)
    gyro_sensor[0] = gyro_sensor[1]
    gyro_sensor[-1] = gyro_sensor[-2]

    # Low-pass before unit conversion. Filter the linear acceleration in world
    # frame (so gravity, added next, stays a clean DC term) and the angular
    # velocity in sensor frame. Convert cutoff Hz → Gaussian sigma in frames:
    # the half-power point of a Gaussian is fc ≈ 0.1874 / sigma_seconds.
    if lowpass_hz and lowpass_hz > 0:
        sigma_frames = 0.1874 * fps / lowpass_hz
        a_world = _gaussian_smooth(a_world, sigma_frames)
        gyro_sensor = _gaussian_smooth(gyro_sensor, sigma_frames)

    # Specific force in world frame, then rotate to sensor frame and to g.
    sp_world = a_world - g_world
    acc_sensor = np.einsum("tji,tj->ti", R, sp_world) / G
    gyro_sensor = np.degrees(gyro_sensor)

    # Saturate to the chip's full-scale range (per-axis, as a real sensor does).
    if accel_clip_g:
        acc_sensor = np.clip(acc_sensor, -accel_clip_g, accel_clip_g)
    if gyro_clip_dps:
        gyro_sensor = np.clip(gyro_sensor, -gyro_clip_dps, gyro_clip_dps)

    return {"acc": acc_sensor, "gyro": gyro_sensor}


def default_mocap_dir() -> Path:
    """The clip collection root: <repo>/data/mocap, or ./data/mocap."""
    root = find_repo_root()
    return Path(root) / "data" / "mocap" if root else Path("data/mocap")


def default_clip_dir(stem: str) -> Path:
    """Where a baked clip's bundle lands: <repo>/data/mocap/<stem>/."""
    return default_mocap_dir() / stem


def write_imu_jsonl(t_ms: np.ndarray, accel: np.ndarray, gyro: np.ndarray,
                    out_path: Path) -> Path:
    """Write a one-sensor {t, ax..az, gx..gz} jsonl stream (g & deg/s).

    This is the IMU-stream contract the simulator reads (docs/SIM.md Decision 2);
    the harness's bridge re-exports it. `t` in ms, accel in g, gyro in deg/s.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for i in range(len(t_ms)):
            a, g = accel[i], gyro[i]
            f.write(json.dumps({
                "t": round(float(t_ms[i]), 3),
                "ax": round(float(a[0]), 4), "ay": round(float(a[1]), 4), "az": round(float(a[2]), 4),
                "gx": round(float(g[0]), 4), "gy": round(float(g[1]), 4), "gz": round(float(g[2]), 4),
            }) + "\n")
    return out_path


def _skeleton_payload(pos: np.ndarray, quat: np.ndarray, joint_names: list,
                      parents: list, fps: float, imus: dict) -> dict:
    """Build the viewer/skeleton JSON payload (skeleton frames + embedded IMU)."""
    return {
        "fps": fps,
        "n_frames": int(pos.shape[0]),
        "joint_names": joint_names,
        "parents": list(parents),
        "bones": [(c, int(parents[c])) for c in range(1, len(parents))],
        "frames": [
            {"p": pos[t].round(5).tolist(), "q": quat[t].round(5).tolist()}
            for t in range(pos.shape[0])
        ],
        "imu": {
            side: {"acc": d["acc"].round(4).tolist(), "gyro": d["gyro"].round(4).tolist()}
            for side, d in imus.items()
        },
    }


def _dump(path: Path, obj: dict, indent: int | None = None) -> Path:
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":") if indent is None else (",", ": "),
                  indent=indent)
    return path


def _write_bundle(out_dir: Path, *, source: Path, pos: np.ndarray, quat: np.ndarray,
                  joint_names: list, parents: list, fps: float, imus: dict,
                  view_stride: int, write_full: bool, manifest_extra: dict) -> Path:
    """Write a self-contained clip directory (see module docstring)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # The input, copied in as the regeneration root.
    src_dst = out_dir / f"source{source.suffix.lower()}"
    shutil.copy2(source, src_dst)

    # Full-rate per-wrist IMU streams (what the simulator reads).
    n = pos.shape[0]
    t_ms = np.arange(n, dtype=np.float64) / fps * 1000.0
    for side, d in imus.items():
        write_imu_jsonl(t_ms, d["acc"], d["gyro"], out_dir / f"imu_{side}.jsonl")

    # Decimated skeleton + IMU for the viewer.
    sv = max(1, int(view_stride))
    view_imus = {s: {"acc": d["acc"][::sv], "gyro": d["gyro"][::sv]} for s, d in imus.items()}
    view = _skeleton_payload(pos[::sv], quat[::sv], joint_names, parents, fps / sv, view_imus)
    vp = _dump(out_dir / "skeleton_view.json", view)
    print(f"  wrote {vp.name}  ({vp.stat().st_size / 1e6:.1f} MB, {view['n_frames']} frames @ {fps/sv:.1f} Hz)")

    # Optional heavy full-rate skeleton (regeneration / debugging only).
    if write_full:
        full = _skeleton_payload(pos, quat, joint_names, parents, fps, imus)
        fp = _dump(out_dir / "skeleton.json", full)
        print(f"  wrote {fp.name}  ({fp.stat().st_size / 1e6:.1f} MB, full rate)")

    root = find_repo_root()
    try:
        rel_dir = out_dir.resolve().relative_to(root) if root else out_dir
    except ValueError:
        rel_dir = out_dir
    manifest = {
        "name": out_dir.name,
        "source": src_dst.name,
        "origin": str(source),
        "fps": round(fps, 4),
        "n_frames": int(n),
        "duration_s": round(n / fps, 2),
        "view_stride": sv,
        "wrists": list(imus.keys()),
        "regenerate": f"bake-mocap {rel_dir}/{src_dst.name}  (add --full for skeleton.json)",
        **manifest_extra,
    }
    _dump(out_dir / "clip.json", manifest, indent=2)
    print(f"  wrote clip.json  →  {out_dir}/")
    return out_dir


def _trim_start(pos, quat, imus, fps, start):
    """Drop the first `start` seconds (e.g. an opening static T-pose).

    Sliced AFTER IMU synthesis so the first kept frame keeps the accel/gyro it
    derived from its real neighbours (no boundary spike). The clip stays 0-based.
    """
    if not start:
        return pos, quat, imus
    start_frame = round(start * fps)
    if start_frame >= pos.shape[0]:
        raise ValueError(
            f"--start {start}s leaves no frames (clip is {pos.shape[0] / fps:.1f}s)")
    pos = pos[start_frame:]
    quat = quat[start_frame:]
    imus = {s: {"acc": d["acc"][start_frame:], "gyro": d["gyro"][start_frame:]}
            for s, d in imus.items()}
    print(f"  trimmed {start:.1f}s ({start_frame} frames) → {pos.shape[0]} frames "
          f"({pos.shape[0] / fps:.1f}s)")
    return pos, quat, imus


def process(npz_path: Path, out_dir: Path | None = None, *, view_stride: int = 4,
            write_full: bool = False, start: float = 0.0) -> Path:
    """Bake an AMASS .npz into a clip directory. Returns the directory path."""
    npz_path = Path(npz_path)
    data = np.load(npz_path, allow_pickle=True)
    fps = float(data["mocap_frame_rate"])
    root_orient, pose_body, trans = data["root_orient"], data["pose_body"], data["trans"]

    print(f"Loaded {npz_path.name}: T={len(trans)}, fps={fps}, gender={data['gender']}")

    pos, R_world = forward_kinematics(root_orient, pose_body, trans)
    quat = matrix_to_quat_xyzw(R_world)  # (T,22,4) xyzw

    # Sanity: bone-length invariance (fixed offsets => constant; catches bugs).
    var = np.linalg.norm(pos[:, 1:] - pos[:, PARENTS[1:]], axis=-1).std(axis=0).max()
    print(f"  bone-length std max: {var:.2e} m  (expect ~0)")
    if not np.isfinite(pos).all() or not np.isfinite(quat).all():
        raise ValueError("non-finite values in output")

    l_idx, r_idx = JOINT_NAMES.index("l_wrist"), JOINT_NAMES.index("r_wrist")
    imus = {"left":  synthesize_imu(pos[:, l_idx], R_world[:, l_idx], fps),
            "right": synthesize_imu(pos[:, r_idx], R_world[:, r_idx], fps)}
    _report_imu(imus)

    pos, quat, imus = _trim_start(pos, quat, imus, fps, start)

    out_dir = Path(out_dir) if out_dir else default_clip_dir(npz_path.stem)
    return _write_bundle(out_dir, source=npz_path, pos=pos, quat=quat,
                         joint_names=list(JOINT_NAMES), parents=PARENTS.tolist(),
                         fps=fps, imus=imus, view_stride=view_stride,
                         write_full=write_full,
                         manifest_extra=({"trim_start_s": start} if start else {}))


def process_bvh(bvh_path: Path, out_dir: Path | None = None, *, view_stride: int = 4,
                height_m: float = 1.70, write_full: bool = False,
                start: float = 0.0) -> Path:
    """Bake a BVH clip into a clip directory. Returns the directory path."""
    from . import bvh as B

    bvh_path = Path(bvh_path)
    clip = B.load(str(bvh_path))
    motion = clip.motion
    fps = clip.fps
    print(f"Loaded {bvh_path.name}: T={len(motion)}, fps={fps:.1f}, "
          f"{len(clip.joints)} joints")

    scale = B.meters_per_unit(clip, height_m)
    print(f"  scale: {scale:.4f} m/unit (rest-pose height {height_m} m)")

    pos_yup, rot_yup = B.forward_kinematics(clip, motion)

    # watch sensors before any reframing (mount is defined in BVH rest pose)
    imus = {}
    for side in ("left", "right"):
        p, R = B.watch_frames(clip, pos_yup, rot_yup, side)
        p_z, R_z = B.to_z_up(p * scale, R)
        imus[side] = synthesize_imu(p_z, R_z, fps)
    _report_imu(imus)

    pos, rot = B.to_z_up(pos_yup * scale, rot_yup)
    quat = matrix_to_quat_xyzw(rot)

    parents = [j.parent for j in clip.joints]
    var = np.linalg.norm(pos[:, 1:] - pos[:, parents[1:]], axis=-1).std(axis=0).max()
    print(f"  bone-length std max: {var:.2e} m  (expect ~0)")
    if not np.isfinite(pos).all() or not np.isfinite(quat).all():
        raise ValueError("non-finite values in output")

    # name the hand joints l_wrist / r_wrist so the viewer highlights them
    rename = {B.find_chain(clip, "left")[1]: "l_wrist",
              B.find_chain(clip, "right")[1]: "r_wrist"}
    joint_names = [rename.get(i, j.name) for i, j in enumerate(clip.joints)]

    pos, quat, imus = _trim_start(pos, quat, imus, fps, start)

    out_dir = Path(out_dir) if out_dir else default_clip_dir(bvh_path.stem)
    return _write_bundle(out_dir, source=bvh_path, pos=pos, quat=quat,
                         joint_names=joint_names, parents=parents, fps=fps,
                         imus=imus, view_stride=view_stride, write_full=write_full,
                         manifest_extra={"height_m": height_m,
                                         **({"trim_start_s": start} if start else {})})


def _report_imu(imus: dict) -> None:
    for side, d in imus.items():
        amax = np.linalg.norm(d["acc"], axis=-1).max()
        gmax = np.linalg.norm(d["gyro"], axis=-1).max()
        print(f"  IMU {side:>5}: |acc|_max={amax:6.2f} g  |gyro|_max={gmax:7.1f} deg/s")


def process_any(path: Path, out_dir: Path | None = None, *, view_stride: int = 4,
                height_m: float = 1.70, write_full: bool = False,
                start: float = 0.0) -> Path:
    """Dispatch on suffix: .npz -> AMASS path, .bvh -> BVH path."""
    path = Path(path)
    if path.suffix.lower() == ".bvh":
        return process_bvh(path, out_dir, view_stride=view_stride, height_m=height_m,
                           write_full=write_full, start=start)
    return process(path, out_dir, view_stride=view_stride, write_full=write_full,
                   start=start)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bake a mocap .npz (AMASS) or .bvh into a data/mocap/<stem>/ clip directory.")
    ap.add_argument("input", type=Path, help="AMASS .npz or BVH file")
    ap.add_argument("-o", "--out-dir", type=Path, default=None,
                    help="Output clip directory (default: data/mocap/<stem>/)")
    ap.add_argument("--view-stride", type=int, default=4,
                    help="Decimation for skeleton_view.json (default: 4, e.g. 120->30 Hz).")
    ap.add_argument("--full", action="store_true",
                    help="Also write the heavy full-rate skeleton.json.")
    ap.add_argument("--height", type=float, default=1.70,
                    help="Dancer height in meters; sets the BVH unit scale.")
    ap.add_argument("--start", type=float, default=0.0, metavar="SECONDS",
                    help="Drop the first SECONDS (e.g. an opening static T-pose).")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        process_any(args.input, args.out_dir, view_stride=args.view_stride,
                    height_m=args.height, write_full=args.full, start=args.start)
    except ValueError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
