"""Extract per-frame joint positions/orientations + synthetic IMU from mocap.

`bake-mocap <raw.npz>` reads an AMASS stage-II .npz, runs forward kinematics,
synthesizes both wrists' IMU (device units + range), and writes a JSON for the
skeleton viewer and the simulator:
{
  fps, n_frames, joint_names, parents, bones,
  frames: [ { p: [[x,y,z]*22], q: [[x,y,z,w]*22] }, ... ],
  imu: { left: {acc, gyro}, right: {acc, gyro} }   # acc in g, gyro in deg/s
}

Coordinate frame: AMASS world (Z-up, meters). No rotation is baked in.
"""

import argparse
import json
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


def default_out_dir() -> Path:
    """Where baked JSON lands: <repo>/data/mocap/out, or ./data/mocap/out."""
    root = find_repo_root()
    return Path(root) / "data" / "mocap" / "out" if root else Path("data/mocap/out")


def process(npz_path: Path, out_path: Path | None = None, stride: int = 1,
            start: float = 0.0) -> Path:
    """Bake a mocap .npz into a skeleton+IMU JSON. Returns the output path."""
    npz_path = Path(npz_path)
    data = np.load(npz_path, allow_pickle=True)
    fps = float(data["mocap_frame_rate"]) / stride
    root_orient = data["root_orient"][::stride]
    pose_body = data["pose_body"][::stride]
    trans = data["trans"][::stride]

    print(f"Loaded {npz_path.name}: T={len(trans)}, fps={fps}, gender={data['gender']}")

    pos, R_world = forward_kinematics(root_orient, pose_body, trans)
    quat = matrix_to_quat_xyzw(R_world)  # (T,22,4) xyzw

    # Sanity: bone-length invariance (since we use fixed offsets they MUST be
    # constant; this catches axis-angle/quaternion bugs).
    bone_len = np.linalg.norm(pos[:, 1:] - pos[:, PARENTS[1:]], axis=-1)  # (T,21)
    var = bone_len.std(axis=0).max()
    print(f"  bone-length std max: {var:.2e} m  (expect ~0)")

    if not np.isfinite(pos).all() or not np.isfinite(quat).all():
        raise ValueError("non-finite values in output")

    # ---- Synthetic IMU for both wrists ------------------------------------
    l_idx = JOINT_NAMES.index("l_wrist")
    r_idx = JOINT_NAMES.index("r_wrist")
    imu_l = synthesize_imu(pos[:, l_idx], R_world[:, l_idx], fps)
    imu_r = synthesize_imu(pos[:, r_idx], R_world[:, r_idx], fps)
    for side, imu in (("left", imu_l), ("right", imu_r)):
        amax = np.linalg.norm(imu["acc"], axis=-1).max()
        gmax = np.linalg.norm(imu["gyro"], axis=-1).max()
        print(f"  IMU {side:>5}: |acc|_max={amax:6.2f} g  |gyro|_max={gmax:7.1f} deg/s")

    # Trim a static prefix (e.g. AMASS opens with a calibration T-pose). Slice
    # AFTER IMU synthesis so the first kept frame keeps the accel/gyro it derived
    # from its real neighbours — no boundary spike. The clip stays 0-based.
    start_frame = round(start * fps)
    if start_frame > 0:
        if start_frame >= pos.shape[0]:
            raise ValueError(
                f"--start {start}s leaves no frames (clip is {pos.shape[0] / fps:.1f}s)")
        pos = pos[start_frame:]
        quat = quat[start_frame:]
        imu_l = {k: v[start_frame:] for k, v in imu_l.items()}
        imu_r = {k: v[start_frame:] for k, v in imu_r.items()}
        print(f"  trimmed {start:.1f}s ({start_frame} frames) → {pos.shape[0]} frames "
              f"({pos.shape[0] / fps:.1f}s)")

    out_path = Path(out_path) if out_path else (default_out_dir() / f"{npz_path.stem}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fps": fps,
        "n_frames": int(pos.shape[0]),
        "trim_start_s": start,
        "joint_names": JOINT_NAMES,
        "parents": PARENTS.tolist(),
        "bones": BONES,
        "frames": [
            {
                "p": pos[t].round(5).tolist(),
                "q": quat[t].round(5).tolist(),
            }
            for t in range(pos.shape[0])
        ],
        "imu": {
            "left":  {"acc": imu_l["acc"].round(4).tolist(),  "gyro": imu_l["gyro"].round(4).tolist()},
            "right": {"acc": imu_r["acc"].round(4).tolist(), "gyro": imu_r["gyro"].round(4).tolist()},
        },
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  wrote {out_path}  ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Bake a mocap .npz into skeleton+IMU JSON.")
    ap.add_argument("npz", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="Output JSON path (default: data/mocap/out/<stem>.json)")
    ap.add_argument("--stride", type=int, default=1,
                    help="Frame stride (e.g. 2 to halve framerate).")
    ap.add_argument("--start", type=float, default=0.0, metavar="SECONDS",
                    help="Drop the first SECONDS (e.g. an opening static T-pose).")
    args = ap.parse_args()

    if not args.npz.exists():
        print(f"input not found: {args.npz}", file=sys.stderr)
        return 1
    try:
        process(args.npz, args.out, args.stride, args.start)
    except ValueError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
