"""mocaplib — turn motion-capture into synthetic IMU + skeleton data.

Reads an AMASS-style stage-II `.npz` (SMPL/SMPL-X body pose), runs forward
kinematics for the 22-joint body skeleton, and synthesizes per-wrist
accelerometer + gyroscope signals in the real device's units and range
(BMI270: accel in g, gyro in deg/s, low-passed and clamped to full-scale —
see test/CORES3/calibrate_imu). The output JSON drives the three.js skeleton
viewer under skeleton/, and feeds the creature simulator.

Two console scripts (mirroring tracelib's bake-trace / trace):
  bake-mocap <raw.npz>   → data/mocap/out/<stem>.json   (extract:main)
  skeleton  [json|npz]   → serve the skeleton viewer     (serve:main)
"""
import os


def find_repo_root(start: str | None = None) -> str | None:
    """Walk up from `start` (or cwd) to the dir containing pyproject.toml."""
    p = os.path.abspath(start or os.getcwd())
    while p != os.path.dirname(p):
        if os.path.exists(os.path.join(p, "pyproject.toml")):
            return p
        p = os.path.dirname(p)
    return None
