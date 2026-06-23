"""BVH input for the mocap factory.

Parses a BVH file (stitched salsa loops from bvh-stitch, CMU-style clips, the
Motorica dance dataset, …), runs forward kinematics, and derives the two
watch-sensor frames that feed `extract.synthesize_imu`.

The parsing is delegated to the maintained `bvhio` library — the hand-rolled
reader this replaced broke (IndexError) on some Motorica hierarchies. We take
`bvhio`'s per-joint *local* rotation keyframes and run the same validated
vectorized FK, scale, and watch-mount the original pipeline used, so the IMU
signal is unchanged for clips both readers handled.

Conventions:
- The virtual sensor is a *watch*: 85 % of the way from elbow to wrist, rigidly
  attached to the FOREARM bone — not the hand, so wrist flexion doesn't
  contaminate the signal (a real watch doesn't rotate when the hand waves).
- Sensor axes are fixed in the rest pose: X along the forearm (elbow→wrist),
  Z out of the watch face (rest-pose up), Y completing the right-handed frame.
- BVH is Y-up in arbitrary units; `meters_per_unit` scales by the dancer's
  rest-pose height and `to_z_up` rotates into the Z-up world the rest of
  mocaplib (and the skeleton viewer) expects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import bvhio

WATCH_ATTACH = 0.85  # along elbow -> wrist

# (forearm, hand) joint-name candidates per side, tried in order
CHAIN_CANDIDATES = {
    "left": [("LeftForeArm", "LeftHand"), ("lForeArm", "lHand"),
             ("LeftLowerArm", "LeftHand"), ("L_ForeArm", "L_Hand")],
    "right": [("RightForeArm", "RightHand"), ("rForeArm", "rHand"),
              ("RightLowerArm", "RightHand"), ("R_ForeArm", "R_Hand")],
}


@dataclass
class BvhJoint:
    name: str
    parent: int          # -1 for root
    offset: np.ndarray   # (3,) rest offset from parent


@dataclass
class Bvh:
    joints: list[BvhJoint]
    rot_local: np.ndarray   # (T, J, 3, 3) per-frame local rotation matrices
    trans: np.ndarray       # (T, 3) root translation per frame
    frame_time: float

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    @property
    def n_frames(self) -> int:
        return self.rot_local.shape[0]

    def joint_index(self, name: str) -> int:
        for i, j in enumerate(self.joints):
            if j.name == name:
                return i
        raise KeyError(name)


def _quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """(..., 4) xyzw quaternions -> (..., 3, 3) rotation matrices."""
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.empty(q.shape[:-1] + (3, 3))
    R[..., 0, 0] = 1 - 2 * (y * y + z * z)
    R[..., 0, 1] = 2 * (x * y - z * w)
    R[..., 0, 2] = 2 * (x * z + y * w)
    R[..., 1, 0] = 2 * (x * y + z * w)
    R[..., 1, 1] = 1 - 2 * (x * x + z * z)
    R[..., 1, 2] = 2 * (y * z - x * w)
    R[..., 2, 0] = 2 * (x * z - y * w)
    R[..., 2, 1] = 2 * (y * z + x * w)
    R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def _flatten(root):
    """Depth-first joint list: (joints, nodes) parallel to each other."""
    joints, nodes = [], []

    def walk(node, parent):
        idx = len(joints)
        joints.append(BvhJoint(node.Name, parent,
                               np.array([node.Offset.x, node.Offset.y, node.Offset.z], float)))
        nodes.append(node)
        for c in node.Children:
            walk(c, idx)

    walk(root, -1)
    return joints, nodes


def load(path: str) -> Bvh:
    """Parse a BVH via `bvhio` into local rotations + root translation."""
    bvh = bvhio.readAsBvh(str(path))
    joints, nodes = _flatten(bvh.Root)
    T = max(len(n.Keyframes) for n in nodes)

    rot_local = np.broadcast_to(np.eye(3), (T, len(nodes), 3, 3)).copy()
    for j, node in enumerate(nodes):
        kf = node.Keyframes
        if len(kf) == T:
            q = np.array([(p.Rotation.x, p.Rotation.y, p.Rotation.z, p.Rotation.w)
                          for p in kf], float)
            rot_local[:, j] = _quat_to_matrix(q)
        # end sites / static joints keep identity rotation

    trans = np.array([(p.Position.x, p.Position.y, p.Position.z)
                      for p in bvh.Root.Keyframes], float)
    return Bvh(joints, rot_local, trans, float(bvh.FrameTime))


def forward_kinematics(bvh: Bvh, motion: np.ndarray | None = None
                       ) -> tuple[np.ndarray, np.ndarray]:
    """World positions (T,J,3) and rotations (T,J,3,3), BVH Y-up world/units.

    `motion` is accepted for signature compatibility but ignored — the per-frame
    local rotations now come from the parsed keyframes on `bvh`.
    """
    R_local = bvh.rot_local
    T, J = R_local.shape[:2]
    offsets = np.array([j.offset for j in bvh.joints])
    parents = [j.parent for j in bvh.joints]

    R_world = np.empty_like(R_local)
    pos = np.zeros((T, J, 3))
    R_world[:, 0] = R_local[:, 0]
    pos[:, 0] = bvh.trans
    for j in range(1, J):
        p = parents[j]
        R_world[:, j] = R_world[:, p] @ R_local[:, j]
        pos[:, j] = pos[:, p] + np.einsum("tij,j->ti", R_world[:, p], offsets[j])
    return pos, R_world


def rest_positions(bvh: Bvh) -> np.ndarray:
    """(J,3) joint positions in the rest pose (all rotations identity)."""
    pos = np.zeros((len(bvh.joints), 3))
    for ji, j in enumerate(bvh.joints):
        base = pos[j.parent] if j.parent >= 0 else np.zeros(3)
        pos[ji] = base + j.offset
    return pos


def meters_per_unit(bvh: Bvh, height_m: float = 1.70) -> float:
    """Unit scale from the dancer's standing height.

    Height is measured as bone-chain length root→head-top plus root→foot
    (not the rest pose's Y extent — rest poses often splay the limbs, which
    would underestimate the height and inflate all IMU amplitudes).
    """
    rest = rest_positions(bvh)

    def chain_len(idx: int) -> float:
        # vertical-dominant bones (legs, spine) stand at full length when
        # upright; lateral bones (pelvis width, feet, clavicles) only
        # contribute their vertical part
        total = 0.0
        while idx > 0:  # the root's own offset is not part of the body
            off = bvh.joints[idx].offset
            length, drop = float(np.linalg.norm(off)), abs(float(off[1]))
            total += length if drop >= 0.7 * length else drop
            idx = bvh.joints[idx].parent
        return total

    lo = int(np.argmin(rest[:, 1]))
    hi = int(np.argmax(rest[:, 1]))
    return height_m / (chain_len(lo) + chain_len(hi))


def find_chain(bvh: Bvh, side: str) -> tuple[int, int]:
    """(forearm_idx, hand_idx) for 'left' / 'right'."""
    for fa, ha in CHAIN_CANDIDATES[side]:
        try:
            return bvh.joint_index(fa), bvh.joint_index(ha)
        except KeyError:
            continue
    names = [j.name for j in bvh.joints]
    raise SystemExit(
        f"could not find {side} forearm/hand joints in BVH (joints: {names})")


def watch_frames(bvh: Bvh, pos: np.ndarray, rot: np.ndarray, side: str
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Sensor position (T,3, BVH units) and orientation (T,3,3, sensor->world).

    Orientation follows the FOREARM bone; the constant mount rotation is
    defined in the rest pose, where world == forearm-local frame.
    """
    fa, ha = find_chain(bvh, side)
    p = pos[:, fa] + WATCH_ATTACH * (pos[:, ha] - pos[:, fa])

    rest = rest_positions(bvh)
    x = rest[ha] - rest[fa]
    x = x / np.linalg.norm(x)
    up = np.array([0.0, 1.0, 0.0])
    z = up - x * np.dot(up, x)
    z = z / np.linalg.norm(z)
    mount = np.stack([x, np.cross(z, x), z], axis=1)
    return p, rot[:, fa] @ mount


# BVH world is Y-up; mocaplib's world (AMASS convention, skeleton viewer) is
# Z-up. v_zup = TO_Z_UP @ v_yup.
TO_Z_UP = np.array([[1.0, 0.0, 0.0],
                    [0.0, 0.0, -1.0],
                    [0.0, 1.0, 0.0]])


def to_z_up(pos: np.ndarray, rot: np.ndarray | None = None):
    """Rotate positions (...,3) and optionally rotations (...,3,3) to Z-up."""
    p = pos @ TO_Z_UP.T
    if rot is None:
        return p
    return p, TO_Z_UP @ rot
