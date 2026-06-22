"""BVH input for the mocap factory.

Parses a BVH file (e.g. the stitched salsa loops produced by the bvh-stitch
repo, or any CMU-style clip), runs forward kinematics, and derives the two
watch-sensor frames that feed `extract.synthesize_imu`.

Conventions baked in here:
- The virtual sensor is a *watch*: positioned at 85 % of the way from elbow
  to wrist and rigidly attached to the FOREARM bone — not the hand, so wrist
  flexion never contaminates the synthesized signal (a real watch doesn't
  rotate when the hand waves).
- Sensor axes are fixed in the skeleton's rest pose (T-pose, arms
  horizontal): X along the forearm (elbow→wrist), Z out of the watch face
  (rest-pose up), Y completing the right-handed frame.
- BVH files are Y-up in arbitrary units; `scale_to_meters` converts using
  the dancer's rest-pose height, and `to_z_up` rotates into the Z-up world
  the rest of mocaplib (and the skeleton viewer) expects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

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
    parent: int  # -1 for root
    offset: np.ndarray  # (3,) rest offset from parent
    channels: list[str]  # [] for End Sites
    channel_index: int


@dataclass
class Bvh:
    joints: list[BvhJoint]
    motion: np.ndarray  # (frames, channels), rotations in degrees
    frame_time: float

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    def joint_index(self, name: str) -> int:
        for i, j in enumerate(self.joints):
            if j.name == name:
                return i
        raise KeyError(name)


def load(path: str) -> Bvh:
    """Parse a BVH file (handles CRLF, End Sites, any channel layout)."""
    with open(path, "r") as f:
        lines = [ln.strip() for ln in f.read().replace("\r", "").split("\n")]

    joints: list[BvhJoint] = []
    stack: list[int] = []
    channel_count = 0
    n_frames = 0
    frame_time = 1 / 120
    motion_start = None

    for i, ln in enumerate(lines):
        if ln.startswith(("ROOT", "JOINT")):
            joints.append(BvhJoint(ln.split()[1], stack[-1] if stack else -1,
                                   np.zeros(3), [], channel_count))
            stack.append(len(joints) - 1)
        elif ln.startswith("End Site"):
            joints.append(BvhJoint(joints[stack[-1]].name + "_end",
                                   stack[-1], np.zeros(3), [], channel_count))
            stack.append(len(joints) - 1)
        elif ln.startswith("OFFSET"):
            joints[stack[-1]].offset = np.array([float(x) for x in ln.split()[1:4]])
        elif ln.startswith("CHANNELS"):
            parts = ln.split()
            joints[stack[-1]].channels = parts[2:2 + int(parts[1])]
            joints[stack[-1]].channel_index = channel_count
            channel_count += int(parts[1])
        elif ln.startswith("}"):
            stack.pop()
        elif ln.startswith("Frames:"):
            n_frames = int(ln.split()[-1])
        elif ln.startswith("Frame Time:"):
            frame_time = float(ln.split()[-1])
            motion_start = i + 1
            break

    motion = np.array("\n".join(lines[motion_start:]).split(), dtype=np.float64)
    motion = motion[: n_frames * channel_count].reshape(n_frames, channel_count)
    return Bvh(joints, motion, frame_time)


def _axis_rot(angles_rad: np.ndarray, axis: str) -> np.ndarray:
    """(n,) angles -> (n,3,3) rotations about a principal axis."""
    n = angles_rad.shape[0]
    c, s = np.cos(angles_rad), np.sin(angles_rad)
    m = np.zeros((n, 3, 3))
    if axis == "X":
        m[:, 0, 0] = 1
        m[:, 1, 1], m[:, 1, 2] = c, -s
        m[:, 2, 1], m[:, 2, 2] = s, c
    elif axis == "Y":
        m[:, 1, 1] = 1
        m[:, 0, 0], m[:, 0, 2] = c, s
        m[:, 2, 0], m[:, 2, 2] = -s, c
    else:
        m[:, 2, 2] = 1
        m[:, 0, 0], m[:, 0, 1] = c, -s
        m[:, 1, 0], m[:, 1, 1] = s, c
    return m


def forward_kinematics(bvh: Bvh, motion: np.ndarray | None = None
                       ) -> tuple[np.ndarray, np.ndarray]:
    """World positions (T,J,3) and rotations (T,J,3,3), BVH Y-up world/units."""
    motion = bvh.motion if motion is None else motion
    n, nj = motion.shape[0], len(bvh.joints)
    pos = np.zeros((n, nj, 3))
    rot = np.zeros((n, nj, 3, 3))

    for ji, j in enumerate(bvh.joints):
        if not j.channels:  # end site: rigid extension of the parent
            rot[:, ji] = rot[:, j.parent]
            pos[:, ji] = pos[:, j.parent] + np.einsum(
                "nab,b->na", rot[:, j.parent], j.offset)
            continue
        rot_channels = [c for c in j.channels if c.endswith("rotation")]
        rot_start = j.channel_index + len(j.channels) - len(rot_channels)
        rad = np.radians(motion[:, rot_start:rot_start + len(rot_channels)])
        local = _axis_rot(rad[:, 0], rot_channels[0][0])
        for k in range(1, len(rot_channels)):
            local = local @ _axis_rot(rad[:, k], rot_channels[k][0])
        if j.parent < 0:
            rot[:, ji] = local
            pos[:, ji] = motion[:, j.channel_index:j.channel_index + 3]
        else:
            rot[:, ji] = rot[:, j.parent] @ local
            pos[:, ji] = pos[:, j.parent] + np.einsum(
                "nab,b->na", rot[:, j.parent], j.offset)
    return pos, rot


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
