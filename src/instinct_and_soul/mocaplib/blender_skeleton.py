"""Render a baked mocap clip's skeleton to a video — runs INSIDE Blender.

    blender --background --factory-startup --python blender_skeleton.py -- \
        CLIP.json OUT.mp4 [--fps 30] [--res 1024] [--samples 16] [--frames N]

Reads the baked clip JSON (frames[].p, bones, joint_names, fps, n_frames) and renders a
ball-and-stick skeleton at --fps (subsampled from the clip framerate), video-only — the
sonification audio is muxed on afterward by the host (bake_video.py). AMASS data is
Z-up, which matches Blender, so joint positions are placed directly.
"""
import bpy
import sys
import json
import math
import argparse
from mathutils import Vector


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("clip")
    p.add_argument("out")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--res", type=int, default=1024)
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--frames", type=int, default=0, help="cap render frames (debug)")
    return p.parse_args(argv)


A = parse()
D = json.load(open(A.clip))
FR = D["frames"]
BONES = D["bones"]
NAMES = D["joint_names"]
N = int(D["n_frames"])
CLIP_FPS = float(D["fps"])
J = len(NAMES)

JOINT_R, WRIST_R, BONE_R = 0.028, 0.046, 0.014


def rgb(h):
    return ((h >> 16 & 255) / 255, (h >> 8 & 255) / 255, (h & 255) / 255)


def mat(name, color, rough=0.55):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    return m


# ── scene: keep the (working) factory world, drop the default objects ───────
for _o in list(bpy.data.objects):
    bpy.data.objects.remove(_o, do_unlink=True)
scene = bpy.context.scene
scene.view_settings.view_transform = "Standard"   # avoid AGX darkening
world = scene.world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.065, 1.0)

m_joint = mat("joint", rgb(0xcccccc))
m_lw = mat("lwrist", rgb(0xf4a261))
m_rw = mat("rwrist", rgb(0x2a9d8f))
m_bone = mat("bone", rgb(0x66aaff))
m_ground = mat("ground", (0.02, 0.02, 0.025), rough=0.95)

# ── joints (spheres) ────────────────────────────────────────────────────────
joints = []
for j in range(J):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=9, radius=1.0)
    o = bpy.context.active_object
    isw = NAMES[j].endswith("_wrist")
    o.scale = (WRIST_R if isw else JOINT_R,) * 3
    o.data.materials.append(
        m_lw if NAMES[j] == "l_wrist" else m_rw if NAMES[j] == "r_wrist" else m_joint)
    for poly in o.data.polygons:
        poly.use_smooth = True
    joints.append(o)

# ── bones (cylinders, long axis = local Z) ──────────────────────────────────
bones = []
for (c, par) in BONES:
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=BONE_R, depth=1.0)
    o = bpy.context.active_object
    o.rotation_mode = "QUATERNION"
    o.data.materials.append(m_bone)
    for poly in o.data.polygons:
        poly.use_smooth = True
    bones.append((o, c, par))

# ── camera framing from the bounding box over the whole clip ────────────────
mn = [1e9, 1e9, 1e9]
mx = [-1e9, -1e9, -1e9]
for i in range(0, N, max(1, N // 150)):
    for p in FR[i]["p"]:
        for k in range(3):
            mn[k] = min(mn[k], p[k])
            mx[k] = max(mx[k], p[k])
center = Vector(((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2))
extent = Vector((mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]))
radius = max(extent.length / 2, 0.9)

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 50
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = center + Vector((radius * 1.7, -radius * 2.6, radius * 0.7))
# Point the camera at the centroid explicitly (no constraint to depend on).
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
print(f"[framing] center={tuple(round(c,2) for c in center)} radius={radius:.2f} "
      f"cam={tuple(round(c,2) for c in cam.location)} objs={len(scene.objects)}", file=sys.stderr)

# ── lights + ground ─────────────────────────────────────────────────────────
sun_d = bpy.data.lights.new("Sun", "SUN")
sun_d.energy = 3.2
sun = bpy.data.objects.new("Sun", sun_d)
scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), math.radians(8), math.radians(40))

fill_d = bpy.data.lights.new("Fill", "SUN")
fill_d.energy = 1.0
fill = bpy.data.objects.new("Fill", fill_d)
scene.collection.objects.link(fill)
fill.rotation_euler = (math.radians(60), 0, math.radians(-120))

bpy.ops.mesh.primitive_plane_add(size=40, location=(center.x, center.y, mn[2] - 0.01))
ground = bpy.context.active_object
ground.data.materials.append(m_ground)


# ── per-frame skeleton update ───────────────────────────────────────────────
def update(scene, *args):
    ci = int(round(scene.frame_current * CLIP_FPS / A.fps))
    if ci >= N:
        ci = N - 1
    P = FR[ci]["p"]
    for j in range(J):
        joints[j].location = (P[j][0], P[j][1], P[j][2])
    for (o, c, par) in bones:
        a = Vector(P[par])
        b = Vector(P[c])
        d = b - a
        L = d.length
        o.location = (a + b) / 2
        if L > 1e-6:
            o.rotation_quaternion = d.to_track_quat("Z", "Y")
            o.scale = (1.0, 1.0, L)
        else:
            o.scale = (1.0, 1.0, 1e-4)


bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(update)

# ── render settings ─────────────────────────────────────────────────────────
r = scene.render
r.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
try:
    scene.eevee.taa_render_samples = A.samples
except Exception:
    pass
r.resolution_x = A.res
r.resolution_y = A.res
r.fps = A.fps
total = int(round(N * A.fps / CLIP_FPS))
if A.frames:
    total = min(total, A.frames)
scene.frame_start = 0
scene.frame_end = max(0, total - 1)
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"
r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"
r.ffmpeg.audio_codec = "NONE"
r.filepath = A.out

print(f"[blender_skeleton] {J} joints, {len(bones)} bones, {total} frames @ {A.fps}fps "
      f"-> {A.out}", file=sys.stderr)
bpy.ops.render.render(animation=True)
