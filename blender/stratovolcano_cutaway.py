"""
Stratovolcano cutaway — Blender authoring script (lab test)
Model version: stratovolcano-cutaway 0.1.0

A representative stratovolcano cut in half, drawn at true scale apart from the
conduit (drawn wider so it can be seen). Loosely based on Mount St Helens before
1980: the cone stands about 2 km above its base and is 12 km across. The magma
chamber is placed at the depths measured under Mount St Helens: top about 4 km and
bottom about 13 km below sea level (IRIS science highlight on Kiser et al.), with
the base of the cone at about 1 km above sea level.

The cone is built eruption by eruption: 10 layers, alternating lava flows and ash
(tephra), each a separate object (Layer_01 ... Layer_10) so a page can show the
volcano growing. Each layer stores the summit height it reaches (extras.summit_km).
Also: Bedrock (crust), Conduit, Chamber (emissive), Dike and SideVent (a small
cone on the flank fed by the dike, from layer 8), Pluton (magma that cooled
underground, granite-like rock).

Units: 1 Blender unit = 1 km. Blender axes: x across the cut, y away from the
viewer (only y >= 0 is kept: the front half is cut away), z up; z = 0 is the
base of the cone.

Run headless:
    pip install bpy
    python stratovolcano_cutaway.py --out models/stratovolcano_cutaway.glb --preview-dir previews
"""
import argparse
import math
import os
import sys

import bpy  # must come first: it makes bmesh and mathutils importable
import bmesh
from mathutils import Vector

MODEL_VERSION = "0.1.0"

H, R = 2.0, 6.0          # final cone height and base radius (km)
PROFILE_P = 1.8          # z = H (1 - r/R)^p : about 31 deg near the top, a few degrees at the foot
N_LAYERS = 10
RC = 0.15                # conduit radius (exaggerated; real conduits are tens of metres)
CRATER_R, CRATER_D = 0.45, 0.2
BASE_ASL = 1.0           # base of the cone above sea level (km)
CH_TOP, CH_BOT = -(4 + BASE_ASL), -(13 + BASE_ASL)   # chamber top and bottom (z, km)
CH_A = 2.4               # chamber half-width (shape simplified)
BLOCK_X, BLOCK_Y, BLOCK_Z = 12.0, 8.0, 15.5
SEG = 40                 # steps round the half circle
FRONT = -0.02            # cut faces of the magma parts sit 20 m in front of the bedrock and layers, so they never flicker
SIDE_X = 3.1             # side vent position on the flank (on the cut, x > 0)


def srgb(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def material(name, rgb, rough=0.85, emission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    lin = (*[srgb(c) for c in rgb], 1)
    b.inputs["Base Color"].default_value = lin
    b.inputs["Roughness"].default_value = rough
    if emission:
        b.inputs["Emission Color"].default_value = lin
        b.inputs["Emission Strength"].default_value = emission
    return m


# ---------------------------------------------------------------- profiles
def cone_z(r, k):
    """Height of the cone surface after eruption k (0 = no cone) at radius r."""
    if k <= 0:
        return 0.0
    f = k / N_LAYERS
    hk, rk = H * f ** 0.75, R * f ** 0.6
    if r >= rk:
        return 0.0
    return hk * (1 - r / rk) ** PROFILE_P


def summit(k):
    return H * (k / N_LAYERS) ** 0.75


def top_z(r, k):
    """Top of layer k, with the crater cut into the last layer."""
    z = cone_z(r, k)
    if k == N_LAYERS and r < CRATER_R:
        z = max(cone_z(r, k - 1) + 0.01, z - CRATER_D * (1 - (r / CRATER_R) ** 2))
    return z


# ---------------------------------------------------------------- half solids of revolution
def half_revolution(name, outline, mat, centre=(0.0, 0.0), seg=SEG):
    """Sweep a closed outline [(r, z), ...] (r >= 0, counter-clockwise in the r-z plane)
    round the z axis through the back half (y >= 0), and close both cut faces."""
    bm = bmesh.new()
    cx, cy = centre
    rings = []
    for i in range(seg + 1):
        th = math.pi * i / seg
        c, s = math.cos(th), math.sin(th)
        rings.append([bm.verts.new((cx + r * c, cy + r * s, z)) for r, z in outline])
    n = len(outline)
    for i in range(seg):
        a, b = rings[i], rings[i + 1]
        for j in range(n):
            j2 = (j + 1) % n
            quad = [a[j], a[j2], b[j2], b[j]]
            if len({v.co.to_tuple(6) for v in quad}) >= 3:
                try:
                    bm.faces.new(quad)
                except ValueError:
                    pass
    for ring in (rings[0], rings[-1]):        # the two cut faces, in the plane y = cy
        uniq = []
        for v in ring:
            if not uniq or (v.co - uniq[-1].co).length > 1e-6:
                uniq.append(v)
        if (uniq[0].co - uniq[-1].co).length < 1e-6:
            uniq.pop()
        if len(uniq) >= 3:
            try:
                bm.faces.new(uniq)
            except ValueError:
                pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def layer_outline(k, nr=28):
    """Region between the cone after eruption k-1 and after eruption k, from the conduit wall out."""
    f = k / N_LAYERS
    rk = R * f ** 0.6
    rs = [RC + (rk - RC) * (i / nr) ** 1.3 for i in range(nr + 1)]
    bottom = [(r, cone_z(r, k - 1)) for r in rs]
    top = [(r, top_z(r, k)) for r in reversed(rs)]
    return bottom + top[1:-1] + [(RC, top_z(RC, k))]


def ellipse_outline(a, c, zc, n=40):
    return [(a * math.sin(math.pi * i / n), zc + c * math.cos(math.pi * i / n)) for i in range(n + 1)][::-1]


# ---------------------------------------------------------------- the model
def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    M = {
        "lava": [material(f"Lava_{i}", c) for i, c in enumerate([(0.29, 0.27, 0.27), (0.35, 0.32, 0.31)])],
        "ash": [material(f"Ash_{i}", c) for i, c in enumerate([(0.72, 0.62, 0.47), (0.80, 0.70, 0.55)])],
        "rock": material("Bedrock", (0.52, 0.47, 0.42)),
        "ground": material("Ground", (0.36, 0.42, 0.27)),
        "magma": material("Magma", (1.0, 0.36, 0.08), emission=2.0),
        "pluton": material("Cooled_magma", (0.71, 0.62, 0.60)),
    }
    objs = []

    # cone layers, oldest first; odd layers lava, even layers ash
    for k in range(1, N_LAYERS + 1):
        kind = "lava" if k % 2 else "ash"
        ob = half_revolution(f"Layer_{k:02d}_{kind}", layer_outline(k), M[kind][(k // 2) % 2])
        ob["layer"] = k
        ob["kind"] = kind
        ob["summit_km"] = round(summit(k), 4)
        objs.append(ob)

    # the magma chamber, conduit and an old intrusion that cooled underground
    chamber = half_revolution("Chamber", ellipse_outline(CH_A, (CH_TOP - CH_BOT) / 2, (CH_TOP + CH_BOT) / 2), M["magma"], centre=(0.0, FRONT))
    crater_floor = top_z(0, N_LAYERS)
    conduit = half_revolution("Conduit", [(0, CH_TOP - 0.3), (RC, CH_TOP - 0.3), (RC, crater_floor), (0, crater_floor)], M["magma"], centre=(0.0, FRONT))
    conduit["top_km"] = round(crater_floor, 4)
    pluton = half_revolution("Pluton", ellipse_outline(2.0, 1.4, -7.0), M["pluton"], centre=(-6.0, FRONT))
    objs += [chamber, conduit, pluton]

    # bedrock: the back half of a block. No holes are cut: the parts inside it only show on the cut face,
    # and their cut faces sit just in front of it.
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * 2 * BLOCK_X, (v.co.y + 0.5) * BLOCK_Y, (v.co.z - 0.5) * BLOCK_Z))
    mesh = bpy.data.meshes.new("Bedrock")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(M["rock"])
    mesh.materials.append(M["ground"])
    rock = bpy.data.objects.new("Bedrock", mesh)
    bpy.context.scene.collection.objects.link(rock)
    for poly in mesh.polygons:                 # the top face is ground
        if poly.normal.z > 0.9:
            poly.material_index = 1
    objs.append(rock)

    # dike and side vent: a sheet of magma from the conduit to a small cone on the flank (from layer 8)
    zs = top_z(SIDE_X, N_LAYERS)
    bm = bmesh.new()
    a0, a1 = Vector((RC, 0, -1.6)), Vector((SIDE_X, 0, zs - 0.02))   # rises from the conduit 1.6 km below the base
    d = (a1 - a0).normalized()
    nrm = Vector((-d.z, 0, d.x)) * 0.05
    quad = [a0 - nrm, a1 - nrm, a1 + nrm, a0 + nrm]
    vs_front = [bm.verts.new((p.x, -0.02, p.z)) for p in quad]
    vs_back = [bm.verts.new((p.x, 0.35, p.z)) for p in quad]
    bm.faces.new(vs_front)
    bm.faces.new(list(reversed(vs_back)))
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new([vs_front[i], vs_back[i], vs_back[j], vs_front[j]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Dike")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(M["magma"])
    dike = bpy.data.objects.new("Dike", mesh)
    bpy.context.scene.collection.objects.link(dike)
    dike["from_layer"] = 8
    # the side vent's base follows the flank on its downhill side and is buried on the uphill side;
    # its cut faces sit 10 m in front of the layers' so the two don't flicker
    side_r, side_h = 0.55, 0.22
    rs = [side_r * i / 16 for i in range(17)]
    z0 = top_z(SIDE_X, N_LAYERS)
    base = [(r, top_z(SIDE_X + r, N_LAYERS) - 0.01) for r in rs]           # axis -> rim, along the bottom
    top = [(r, z0 + side_h * (1 - r / side_r) ** 1.4) for r in reversed(rs)]  # rim -> axis, along the top
    side = half_revolution("SideVent", base + top, M["lava"][1], centre=(SIDE_X, -0.01))
    side["from_layer"] = 8
    objs += [dike, side]

    for ob in objs:
        ob["model_version"] = MODEL_VERSION
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
    return objs


def export_glb(path):
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, export_extras=True)


def render(path, cam_loc, target, lens=35, res=(1100, 760)):
    scene = bpy.context.scene
    cam = bpy.data.objects.get("Cam") or bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (Vector(target) - Vector(cam_loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    cam.data.clip_end = 500
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)


def setup_render():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)
    w = bpy.data.worlds.new("Sky"); w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.68, 0.85, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    scene.world = w


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="stratovolcano_cutaway.glb")
    p.add_argument("--preview-dir", default=None)
    a = p.parse_args(argv)
    build()
    export_glb(a.out)
    print(f"Exported {a.out} (stratovolcano-cutaway {MODEL_VERSION})")
    if a.preview_dir:
        os.makedirs(a.preview_dir, exist_ok=True)
        setup_render()
        render(f"{a.preview_dir}/whole.png", (-14, -30, 6), (0, 3, -6), lens=32)
        render(f"{a.preview_dir}/cone.png", (-3.5, -11, 2.2), (0.5, 0, 0.6), lens=35)
        print("Previews written")


if __name__ == "__main__":
    main(sys.argv[1:])
