"""
Pompeii atrium house — Blender authoring script (lab test)
Model version: pompeii-house 0.2.0
  0.2.0  oil lamps on stands, braziers and the lararium flame, with emissive
         flames/coals (glow in ArcGIS SDK 5.x)
  0.1.0  first build

A REPRESENTATIVE house, not a survey of one building. Proportions follow
Gell's 1832 measurements of the House of the Tragic Poet (atrium ~28 x 20 ft,
entrance passage ~6 ft wide, rooms ~12 ft high) and Vitruvius' rule that the
tablinum is two-thirds the atrium's width.

Layout, street to back: street with stepping stones, raised pavement, two shops
(tabernae) either side of the entrance passage (fauces) with an upper storey,
atrium with impluvium under the compluvium roof opening, cubicula and an ala,
tablinum, then a colonnaded peristyle garden with a triclinium, kitchen
(culina) and lararium.

Run headless:
    pip install bpy scipy
    python pompeii_house.py --out pompeii_house.glb --preview-dir previews [--split]
    gltf-transform draco pompeii_house.glb pompeii_house.draco.glb

Units: metres. Blender axes: x across the plot, y away from the street, z up.
"""
import argparse
import math
import os
import sys

import bpy  # must come first: it makes bmesh and mathutils importable
import bmesh
import numpy as np
from mathutils import Vector
from scipy.ndimage import zoom

MODEL_VERSION = "0.2.0"
W, D = 14.0, 30.0      # plot width and depth
T = 0.4                # wall thickness (rubble-and-mortar walls were ~0.4-0.5 m)
PPM = 128              # texture pixels per metre (most textures)
RNG = np.random.default_rng(79)

# metres covered by one repeat of each texture (u, v)
TILE = {
    "wall_red": (2.5, 8.0), "wall_yellow": (2.5, 8.0), "plaster_int": (2.0, 8.0),
    "plaster_ext": (4.0, 8.0), "floor": (2.0, 2.0), "mosaic": (1.0, 1.0),
    "roof_tiles": (1.0, 1.2), "basalt": (3.0, 3.0), "pavement": (2.0, 2.0),
    "column": (1.0, 8.0), "garden": (4.0, 4.0), "wood": (2.0, 2.0),
    "marble": (1.0, 1.0), "water": (1.0, 1.0), "shrub": (1.0, 1.0),
    "wall_top": (1.0, 1.0), "bronze": (1.0, 1.0), "flame": (1.0, 1.0), "embers": (1.0, 1.0),
}

# --------------------------------------------------------------------- textures

def noise(h, w, cell):
    small = RNG.random((h // cell + 2, w // cell + 2))
    return zoom(small, cell, order=1)[:h, :w]


def fbm(h, w):
    return 0.6 * noise(h, w, 32) + 0.4 * noise(h, w, 5)


def grid(h_m, w_m, ppm=PPM):
    """z (height up the image, metres) and x (metres) for every pixel; row 0 = top."""
    H, Wp = int(round(h_m * ppm)), int(round(w_m * ppm))
    z = ((H - 1 - np.arange(H)) / ppm)[:, None] * np.ones((1, Wp))
    x = (np.arange(Wp) / ppm)[None, :] * np.ones((H, 1))
    return z, x, H, Wp


def voronoi(h, w, n, wrap_y=True):
    pts = RNG.random((n, 2)) * [w, h]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.empty((n, h, w), dtype=np.float32)
    for i, (px, py) in enumerate(pts):
        dx = np.abs(xx - px); dx = np.minimum(dx, w - dx)
        dy = np.abs(yy - py)
        if wrap_y:
            dy = np.minimum(dy, h - dy)
        d[i] = np.hypot(dx, dy)
    two = np.partition(d, 1, axis=0)
    cell = np.argmin(d, axis=0)
    return cell, two[1] - two[0]


def shade(img, amount=0.08):
    h, w, _ = img.shape
    return np.clip(img * (1 - amount + amount * 2 * fbm(h, w))[..., None], 0, 1)


C = lambda *rgb: np.array(rgb, dtype=float)
POMPEIAN_RED = C(0.60, 0.17, 0.11)
OCHRE = C(0.80, 0.60, 0.25)
BLACK = C(0.10, 0.09, 0.09)
CREAM = C(0.90, 0.86, 0.77)


def tex_wall(field, divider, line):
    z, x, H, Wp = grid(8.0, 2.5)
    img = np.empty((H, Wp, 3)); img[:] = CREAM
    def band(z0, z1, col): img[(z >= z0) & (z < z1)] = col
    band(0.0, 0.9, BLACK)                 # dado
    band(0.9, 1.0, C(0.82, 0.77, 0.66))
    band(1.0, 3.3, field)                 # main zone, one panel per repeat
    img[(z >= 1.0) & (z < 3.3) & ((x < 0.08) | (x > 2.42))] = divider
    inner = (z >= 1.15) & (z < 3.15) & (x >= 0.25) & (x <= 2.25)
    edge = inner & ((np.abs(x - 0.25) < 0.015) | (np.abs(x - 2.25) < 0.015) |
                    (np.abs(z - 1.15) < 0.015) | (np.abs(z - 3.15) < 0.015))
    img[edge] = line
    band(3.3, 3.34, BLACK)
    band(3.34, 3.75, C(0.86, 0.80, 0.68))  # frieze; plain plaster above
    return shade(img, 0.07)


def tex_plaster_int():
    z, x, H, Wp = grid(8.0, 2.0)
    img = np.empty((H, Wp, 3)); img[:] = C(0.84, 0.79, 0.70)
    img[z < 0.25] *= 0.82                 # scuffed base
    return shade(img, 0.10)


def tex_plaster_ext():
    z, x, H, Wp = grid(8.0, 4.0)
    img = np.empty((H, Wp, 3)); img[:] = C(0.80, 0.72, 0.58)
    streak = zoom(RNG.random((H // 64 + 2, Wp // 6 + 2)), (64, 6), order=1)[:H, :Wp]
    img *= (0.92 + 0.08 * streak)[..., None]
    # lower 1 m: exposed rubble masonry (opus incertum) of lava and limestone
    rows = int(1.0 * PPM)
    cell, gap = voronoi(rows, Wp, 70, wrap_y=False)
    stones = np.array([[0.36, 0.34, 0.33], [0.52, 0.48, 0.42], [0.62, 0.57, 0.48],
                       [0.30, 0.29, 0.30], [0.58, 0.50, 0.40]])
    pick = RNG.integers(0, len(stones), cell.max() + 1)
    jitter = 0.9 + 0.2 * RNG.random(cell.max() + 1)
    low = stones[pick[cell]] * jitter[cell][..., None]
    low[gap < 3] = C(0.74, 0.69, 0.60)
    img[H - rows:] = low
    return shade(img, 0.08)


def tex_floor():
    z, x, H, Wp = grid(2.0, 2.0)
    img = np.empty((H, Wp, 3)); img[:] = C(0.66, 0.40, 0.32)   # cocciopesto
    img = shade(img, 0.12)
    s = 0.2
    lattice = ((np.abs(((x + (np.floor(z / s) % 2) * s / 2) % s) - s / 2) < 0.012) &
               (np.abs((z % s) - s / 2) < 0.012))
    img[lattice] = C(0.90, 0.88, 0.82)                          # white tesserae
    return img


def tex_mosaic():
    z, x, H, Wp = grid(1.0, 1.0)
    chk = ((np.floor(x / 0.1) + np.floor(z / 0.1)) % 2).astype(bool)
    img = np.where(chk[..., None], C(0.14, 0.13, 0.13), C(0.88, 0.86, 0.80))
    return shade(img, 0.06)


def tex_roof():
    ppm = 256
    z, x, H, Wp = grid(1.2, 1.0, ppm)
    base = C(0.66, 0.31, 0.20)
    img = np.empty((H, Wp, 3)); img[:] = base
    # per-tile brightness (two tegulae across, two courses up)
    tile_id = (np.floor(x / 0.5) + 2 * np.floor(z / 0.6)).astype(int)
    tone = 0.85 + 0.3 * RNG.random(4)
    img *= tone[tile_id][..., None]
    # imbrices over each joint: rounded cover tiles, lit on top, shadow on one side
    dj = ((x + 0.25) % 0.5) - 0.25
    imb = np.abs(dj) < 0.08
    prof = np.cos(np.clip(dj / 0.08, -1, 1) * math.pi / 2)
    img[imb] = (base * 1.08)[None, :] * (0.7 + 0.45 * prof[imb])[:, None]
    img[(dj > 0.08) & (dj < 0.12)] *= 0.6
    # course overlaps
    dc = z % 0.6
    img[dc < 0.025] *= 0.55
    return shade(img, 0.10)


def tex_basalt():
    z, x, H, Wp = grid(3.0, 3.0)
    cell, gap = voronoi(H, Wp, 32)
    tone = 0.24 + 0.10 * RNG.random(cell.max() + 1)
    img = np.stack([tone[cell] * 0.97, tone[cell] * 0.98, tone[cell] * 1.04], -1)
    img[gap < 4] = C(0.12, 0.11, 0.11)
    return shade(img, 0.12)


def tex_pavement():
    z, x, H, Wp = grid(2.0, 2.0)
    img = np.empty((H, Wp, 3)); img[:] = C(0.56, 0.50, 0.43)
    return shade(img, 0.15)


def tex_column():
    z, x, H, Wp = grid(8.0, 1.0)
    img = np.empty((H, Wp, 3)); img[:] = C(0.90, 0.88, 0.83)
    img[z < 1.1] = POMPEIAN_RED           # lower third painted red, unfluted
    flute = (np.abs(((x + 1 / 32) % (1 / 16)) - 1 / 32) < 0.006) & (z >= 1.1)
    img[flute] *= 0.75
    return shade(img, 0.05)


def tex_garden():
    z, x, H, Wp = grid(4.0, 4.0, 64)
    n = fbm(H, Wp)
    img = np.empty((H, Wp, 3))
    img[:] = C(0.30, 0.40, 0.20)
    img[n > 0.62] = C(0.45, 0.36, 0.24)   # bare earth patches
    return shade(img, 0.15)


def tex_wood():
    z, x, H, Wp = grid(2.0, 2.0)
    grain = zoom(RNG.random((H // 2 + 2, Wp // 64 + 2)), (2, 64), order=1)[:H, :Wp]
    img = C(0.40, 0.27, 0.17)[None, None, :] * (0.8 + 0.3 * grain)[..., None]
    return np.clip(img, 0, 1)


TEX_BUILDERS = {
    "wall_red": lambda: tex_wall(POMPEIAN_RED, BLACK, C(0.85, 0.68, 0.30)),
    "wall_yellow": lambda: tex_wall(OCHRE, POMPEIAN_RED, C(0.25, 0.20, 0.15)),
    "plaster_int": tex_plaster_int, "plaster_ext": tex_plaster_ext,
    "floor": tex_floor, "mosaic": tex_mosaic, "roof_tiles": tex_roof,
    "basalt": tex_basalt, "pavement": tex_pavement, "column": tex_column,
    "garden": tex_garden, "wood": tex_wood,
}
FLAT = {  # name: (sRGB colour, roughness[, emission strength])
    "marble": ((0.91, 0.89, 0.85), 0.35),
    "wall_top": ((0.82, 0.77, 0.68), 0.9),
    "water": ((0.30, 0.42, 0.45), 0.08),
    "shrub": ((0.26, 0.38, 0.18), 0.9),
    "bronze": ((0.42, 0.30, 0.16), 0.45),
    "flame": ((1.00, 0.72, 0.30), 0.9, 1.0),      # emissive: exported as glTF emissiveFactor
    "embers": ((1.00, 0.38, 0.10), 0.9, 1.0),
}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def make_materials(texdir):
    os.makedirs(texdir, exist_ok=True)
    mats = {}
    for name, build in TEX_BUILDERS.items():
        arr = np.clip(build(), 0, 1)
        h, w, _ = arr.shape
        img = bpy.data.images.new(name, w, h, alpha=False)
        rgba = np.concatenate([arr, np.ones((h, w, 1))], axis=2)
        img.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
        img.filepath_raw = os.path.join(texdir, name + ".png")
        img.file_format = "PNG"
        img.save()
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.85
        mats[name] = mat
    for name, spec in FLAT.items():
        rgb, rough = spec[0], spec[1]
        emission = spec[2] if len(spec) > 2 else 0.0
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        lin = (*[srgb_to_linear(c) for c in rgb], 1)
        bsdf.inputs["Base Color"].default_value = lin
        bsdf.inputs["Roughness"].default_value = rough
        if emission > 0:
            bsdf.inputs["Emission Color"].default_value = lin
            bsdf.inputs["Emission Strength"].default_value = emission
        mats[name] = mat
    return mats

# ------------------------------------------------------------------ mesh builder

class MB:
    """Collects faces for one object, with per-face material and UVs in metres."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.mats = []

    def _mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def face(self, pts, mat, mode="box", up=None):
        pts = [Vector(p) for p in pts]
        n = (pts[1] - pts[0]).cross(pts[2] - pts[1]).normalized()
        if up is not None and (n.z > 0) != up:      # enforce facing
            pts.reverse(); n = -n
        f = self.bm.faces.new([self.bm.verts.new(p) for p in pts])
        f.material_index = self._mi(mat)
        tu, tv = TILE[mat]
        for loop in f.loops:
            p = loop.vert.co
            if mode == "slope" and abs(n.z) < 0.999:
                h = Vector((n.x, n.y)).normalized()
                u, v = -p.x * h.y + p.y * h.x, p.x * h.x + p.y * h.y
            elif abs(n.x) >= max(abs(n.y), abs(n.z)):
                u, v = p.y, p.z
            elif abs(n.y) >= abs(n.z):
                u, v = p.x, p.z
            else:
                u, v = p.x, p.y
            loop[self.uv].uv = (u / tu, v / tv)
        return n

    def box(self, x0, y0, z0, x1, y1, z1, matfn, bottom=False):
        faces = [
            ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0)),
            ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
            ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
            ([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], (0, 1, 0)),
            ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
        ]
        if bottom:
            faces.append(([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], (0, 0, -1)))
        for pts, n in faces:
            c = Vector([sum(p[i] for p in pts) / 4 for i in range(3)])
            self.face(pts, matfn(c, Vector(n)))

    def cylinder(self, cx, cy, z0, z1, r, mat, segs=16, sx=1.0, sy=1.0, cap_mat=None):
        ring = [(cx + r * sx * math.cos(2 * math.pi * i / segs),
                 cy + r * sy * math.sin(2 * math.pi * i / segs)) for i in range(segs)]
        tu, tv = TILE[mat]
        for i in range(segs):
            (ax, ay), (bx, by) = ring[i], ring[(i + 1) % segs]
            f = self.bm.faces.new([self.bm.verts.new(v) for v in
                                   [(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)]])
            f.material_index = self._mi(mat)
            for loop, (u, v) in zip(f.loops, [(i, z0), (i + 1, z0), (i + 1, z1), (i, z1)]):
                loop[self.uv].uv = (u / segs / tu, v / tv)
        self.face([(x, y, z1) for x, y in ring], cap_mat or mat, up=True)

    def blob(self, cx, cy, cz, r, mat):
        """Lumpy sphere for shrubs."""
        before = set(self.bm.faces)
        bmesh.ops.create_icosphere(self.bm, subdivisions=2, radius=r)
        new = [f for f in self.bm.faces if f not in before]
        verts = {v for f in new for v in f.verts}
        for v in verts:
            k = 0.85 + 0.3 * RNG.random()
            v.co = Vector((cx + v.co.x * k, cy + v.co.y * k, cz + v.co.z * k * 0.9))
        for f in new:
            f.material_index = self._mi(mat)
            for loop in f.loops:
                loop[self.uv].uv = (loop.vert.co.x, loop.vert.co.y)

    def finish(self, mats):
        mesh = bpy.data.meshes.new(self.name)
        self.bm.normal_update()
        self.bm.to_mesh(mesh)
        self.bm.free()
        for m in self.mats:
            mesh.materials.append(mats[m])
        ob = bpy.data.objects.new(self.name, mesh)
        bpy.context.scene.collection.objects.link(ob)
        return ob

# ------------------------------------------------------------------ house parts

def wall_mat(c, n):
    x, y, z = c
    if n.z > 0.5:
        return "wall_top"
    if ((n.x < -0.5 and x < 0.05) or (n.x > 0.5 and x > W - 0.05) or
            (n.y < -0.5 and y < 0.05) or (n.y > 0.5 and y > D - 0.05)):
        return "plaster_ext"                      # outside faces
    if y < 6.25:
        return "plaster_int"                      # shops, entrance, upper storey
    if y > 19.25:
        return "wall_yellow"                      # peristyle rooms
    return "wall_red"                             # atrium and tablinum rooms


def subtract(span, holes):
    out = [span]
    for b, t in holes:
        nxt = []
        for s, e in out:
            if t <= s or b >= e:
                nxt.append((s, e)); continue
            if b > s: nxt.append((s, b))
            if t < e: nxt.append((t, e))
        out = nxt
    return [(s, e) for s, e in out if e - s > 1e-6]


def wall(mb, axis, c, a0, a1, h, openings=()):
    """Straight wall along `axis` ('x' or 'y') centred on c, from a0 to a1.
    openings: (start, end, bottom, top) along the wall."""
    cuts = sorted({a0, a1, *[o[0] for o in openings], *[o[1] for o in openings]})
    cuts = [p for p in cuts if a0 <= p <= a1]
    for p, q in zip(cuts, cuts[1:]):
        mid = (p + q) / 2
        holes = [(o[2], o[3]) for o in openings if o[0] <= mid <= o[1]]
        for z0, z1 in subtract((0.0, h), holes):
            if axis == "x":
                mb.box(p, c - T / 2, z0, q, c + T / 2, z1, wall_mat, bottom=z0 > 0)
            else:
                mb.box(c - T / 2, p, z0, c + T / 2, q, z1, wall_mat, bottom=z0 > 0)


def build_walls(mats):
    # Walls along x run the full width; walls along y stop at the faces of the
    # x walls, so no two walls overlap (overlaps render as flickering/black faces).
    mb = MB("Walls")
    # street front: two storeys, shop openings, entrance, upper windows
    wall(mb, "x", 0.2, 0, W, 7.2, [
        (1.0, 5.0, 0, 3.2), (6.1, 7.9, 0, 3.0), (9.0, 13.0, 0, 3.2),
        (1.8, 2.6, 4.9, 5.8), (4.0, 4.8, 4.9, 5.8), (9.2, 10.0, 4.9, 5.8), (11.4, 12.2, 4.9, 5.8)])
    wall(mb, "y", 0.2, 0.4, 6.0, 7.2); wall(mb, "y", W - 0.2, 0.4, 6.0, 7.2)
    wall(mb, "y", 5.8, 0.4, 6.0, 7.2); wall(mb, "y", 8.2, 0.4, 6.0, 7.2)   # entrance passage
    wall(mb, "x", 6.2, 0, W, 7.2, [(6.0, 8.0, 0, 3.0)])
    # atrium zone (inner walls kept below the sloping atrium roof)
    wall(mb, "y", 0.2, 6.4, 14.8, 5.0); wall(mb, "y", W - 0.2, 6.4, 14.8, 5.0)
    wall(mb, "y", 3.9, 6.4, 14.8, 4.3, [(7.2, 8.2, 0, 2.6), (10.0, 11.0, 0, 2.6), (12.8, 13.8, 0, 2.6)])
    wall(mb, "x", 9.0, 0.4, 3.7, 4.3); wall(mb, "x", 11.8, 0.4, 3.7, 4.3)
    wall(mb, "y", 10.1, 6.4, 14.8, 4.3, [(7.4, 8.4, 0, 2.6), (9.9, 14.6, 0, 3.6)])
    wall(mb, "x", 9.7, 10.3, 13.6, 4.3)
    wall(mb, "x", 15.0, 0, W, 5.0, [(5.0, 9.0, 0, 3.6), (9.5, 10.7, 0, 2.8)])
    # tablinum zone
    wall(mb, "y", 0.2, 15.2, 18.8, 5.0); wall(mb, "y", W - 0.2, 15.2, 18.8, 5.0)
    for x in (4.8, 9.2, 11.0):
        wall(mb, "y", x, 15.2, 18.8, 4.6)
    wall(mb, "x", 19.0, 0, W, 5.0, [(5.0, 9.0, 0, 3.6), (9.5, 10.7, 0, 2.8), (2.0, 3.4, 0, 3.0), (12.0, 13.0, 0, 2.6)])
    # peristyle zone
    wall(mb, "y", 0.2, 19.2, 29.6, 4.0); wall(mb, "y", W - 0.2, 19.2, 29.6, 4.0)
    wall(mb, "x", D - 0.2, 0, W, 4.0, [(1.8, 2.7, 0, 2.2)])               # back door
    wall(mb, "y", 10.4, 19.2, 29.6, 4.0, [(20.2, 23.6, 0, 3.0), (26.4, 27.4, 0, 2.4)])
    wall(mb, "x", 25.1, 10.6, 13.6, 4.0)
    return mb.finish(mats)


def build_floors(mats):
    mb = MB("Floors")
    floor = lambda c, n: "floor" if n.z > 0.5 else "plaster_ext"
    mb.box(0, 0, -0.42, W, D, 0, floor)                        # sits on the ground
    # street-food counter in the left shop, faced in marble offcuts
    mb.box(1.2, 1.4, 0, 4.6, 2.0, 0.95, lambda c, n: "marble" if n.z > 0.5 else "plaster_ext")
    mb.box(4.0, 2.0, 0, 4.6, 4.2, 0.95, lambda c, n: "marble" if n.z > 0.5 else "plaster_ext")
    for x in (1.9, 2.8, 3.7):                                  # mouths of storage jars set in it
        mb.cylinder(x, 1.7, 0.95, 0.97, 0.2, "wood", segs=12)
    mb.box(6.0, 0.0, 0, 8.0, 6.2, 0.012, lambda c, n: "mosaic" if n.z > 0.5 else "marble")
    # upper storey floor over the shops (timber ceiling below)
    mb.box(0.4, 0.4, 3.9, W - 0.4, 6.0, 4.15,
           lambda c, n: "plaster_int" if n.z > 0.5 else "wood", bottom=True)
    return mb.finish(mats)


def build_street(mats):
    mb = MB("Street")
    mb.box(-3, -8, -0.7, W + 3, D + 2, -0.42, lambda c, n: "pavement")      # ground
    for y0, y1 in ((-1.6, 0.0), (-7.2, -5.6)):                             # raised pavements
        mb.box(-3, y0, -0.42, W + 3, y1, 0.0, lambda c, n: "pavement" if n.z > 0.5 else "basalt")
    mb.box(-3, -5.6, -0.6, W + 3, -1.6, -0.42, lambda c, n: "basalt")      # carriageway
    for y in (-2.4, -3.6, -4.8):                                           # stepping stones
        mb.cylinder(7.0, y, -0.42, 0.0, 0.45, "basalt", segs=14, sx=1.0, sy=0.7)
    return mb.finish(mats)


def build_impluvium(mats):
    mb = MB("Impluvium")
    rim = lambda c, n: "marble"
    for x0, y0, x1, y1 in ((5.9, 9.3, 8.1, 9.5), (5.9, 11.7, 8.1, 11.9),
                           (5.9, 9.5, 6.1, 11.7), (7.9, 9.5, 8.1, 11.7)):
        mb.box(x0, y0, 0, x1, y1, 0.15, rim)
    mb.box(6.1, 9.5, -0.05, 7.9, 11.7, 0.04, lambda c, n: "water")
    mb.cylinder(7.0, 12.4, 0, 0.7, 0.32, "marble", segs=16)               # well-head (puteal)
    return mb.finish(mats)


COLS_S = [(x, 21.3) for x in (2.9, 4.77, 6.63, 8.5)]
COLS_SIDE = [(x, y) for x in (2.9, 8.5) for y in (23.4, 25.5, 27.6)]


def build_peristyle(mats):
    mb = MB("Peristyle")
    for x, y in COLS_S + COLS_SIDE:
        mb.cylinder(x, y, 0, 2.85, 0.21, "column", segs=16, cap_mat="plaster_int")
        mb.box(x - 0.27, y - 0.27, 2.85, x + 0.27, y + 0.27, 3.0, lambda c, n: "plaster_int", bottom=True)
    beam = lambda c, n: "plaster_int"
    mb.box(0.4, 21.15, 3.0, 10.2, 21.45, 3.35, beam, bottom=True)
    mb.box(2.75, 21.45, 3.0, 3.05, 29.6, 3.35, beam, bottom=True)
    mb.box(8.35, 21.45, 3.0, 8.65, 29.6, 3.35, beam, bottom=True)
    mb.box(3.05, 21.45, 0, 8.35, 29.6, 0.05, lambda c, n: "garden")
    for x, y, r in ((4.2, 23.5, 0.55), (7.2, 23.8, 0.5), (4.6, 27.6, 0.7), (7.0, 27.9, 0.6), (5.7, 25.6, 0.4)):
        mb.blob(x, y, r * 0.8, r, "shrub")
    # lararium: household shrine in the back corner
    mb.box(0.45, 28.9, 0, 1.55, 29.6, 1.1, lambda c, n: "plaster_ext")
    mb.box(0.6, 29.25, 1.1, 1.4, 29.6, 1.9, lambda c, n: "wall_red")
    mb.box(0.45, 28.95, 1.9, 1.55, 29.6, 2.05, lambda c, n: "plaster_ext", bottom=True)
    return mb.finish(mats)


def build_lights(mats):
    """Night lighting a household could afford: oil lamps on bronze stands
    (lampadaria), charcoal braziers, and the lamp kept at the lararium."""
    mb = MB("Lamps")
    stands = [(4.6, 7.0), (9.4, 7.0), (4.6, 14.2), (9.4, 14.2),     # atrium corners
              (7.0, 18.4),                                          # tablinum
              (11.0, 20.0), (13.2, 23.4),                           # triclinium
              (3.4, 20.6), (8.0, 20.6)]                             # portico
    for x, y in stands:
        mb.cylinder(x, y, 0.0, 0.06, 0.18, "bronze", segs=8)        # tripod foot
        mb.cylinder(x, y, 0.06, 1.25, 0.025, "bronze", segs=6)      # shaft
        mb.cylinder(x, y, 1.25, 1.29, 0.14, "bronze", segs=10)      # tray
        mb.blob(x, y, 1.36, 0.06, "flame")                          # flame (slightly enlarged)
    for x, y in ((7.0, 13.2), (12.0, 21.6)):                        # braziers: atrium, triclinium
        mb.cylinder(x, y, 0.0, 0.55, 0.05, "bronze", segs=8)
        mb.cylinder(x, y, 0.55, 0.70, 0.32, "bronze", segs=14, cap_mat="embers")
    mb.blob(1.0, 29.1, 1.16, 0.05, "flame")                         # lararium lamp, on the shrine base
    return mb.finish(mats)


def roof(mats, name, faces):
    """faces: list of point lists; each becomes tiles on top and timber below."""
    mb = MB(name)
    for pts in faces:
        mb.face(pts, "roof_tiles", mode="slope", up=True)
        mb.face(pts, "wood", up=False)
    return mb.finish(mats)


def hip(x0, y0, x1, y1, ze, rz, along="x", inset=None):
    """Hipped roof over a rectangle; ridge runs along `along` at height rz."""
    if along == "x":
        ym = (y0 + y1) / 2; i = inset if inset is not None else (y1 - y0) / 2
        a, b = (x0 + i, ym, rz), (x1 - i, ym, rz)
        return [[(x0, y0, ze), (x1, y0, ze), b, a], [(x1, y1, ze), (x0, y1, ze), a, b],
                [(x0, y1, ze), (x0, y0, ze), a], [(x1, y0, ze), (x1, y1, ze), b]]
    xm = (x0 + x1) / 2; i = inset if inset is not None else (x1 - x0) / 2
    a, b = (xm, y0 + i, rz), (xm, y1 - i, rz)
    return [[(x0, y1, ze), (x0, y0, ze), a, b], [(x1, y0, ze), (x1, y1, ze), b, a],
            [(x0, y0, ze), (x1, y0, ze), a], [(x1, y1, ze), (x0, y1, ze), b]]


def build_roofs(mats):
    obs = []
    obs.append(roof(mats, "Roof_front", hip(-0.3, -0.45, W + 0.3, 6.4, 7.2, 8.6)))
    # atrium: four slopes falling inward to the compluvium opening over the impluvium
    o = [(-0.3, 6.2), (W + 0.3, 6.2), (W + 0.3, 15.0), (-0.3, 15.0)]
    i = [(6.0, 9.4), (8.0, 9.4), (8.0, 11.8), (6.0, 11.8)]
    zo, zi = 5.0, 4.2
    obs.append(roof(mats, "Roof_atrium", [
        [(*o[k], zo), (*o[(k + 1) % 4], zo), (*i[(k + 1) % 4], zi), (*i[k], zi)] for k in range(4)]))
    obs.append(roof(mats, "Roof_tablinum", hip(-0.3, 15.0, W + 0.3, 19.0, 5.0, 5.8)))
    obs.append(roof(mats, "Roof_portico", [
        [(0.2, 19.0, 5.0), (10.4, 19.0, 5.0), (10.4, 21.6, 3.4), (0.2, 21.6, 3.4)],
        [(0.2, 21.6, 4.0), (0.2, 29.8, 4.0), (3.15, 29.8, 3.4), (3.15, 21.6, 3.4)],
        [(10.4, 21.6, 4.0), (10.4, 29.8, 4.0), (8.25, 29.8, 3.4), (8.25, 21.6, 3.4)]]))
    obs.append(roof(mats, "Roof_triclinium", hip(10.4, 19.0, W + 0.3, D + 0.3, 4.0, 4.9, along="y", inset=2.0)))
    return obs

# ------------------------------------------------------------------- pipeline

def build(texdir):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials(texdir)
    objs = [build_street(mats), build_floors(mats), build_walls(mats),
            build_impluvium(mats), build_peristyle(mats), build_lights(mats), *build_roofs(mats)]
    for ob in objs:
        ob["model_version"] = MODEL_VERSION
    return objs


def export_glb(path, objects=None):
    """Export all objects, or only `objects` (same origin, so parts line up)."""
    for ob in bpy.data.objects:
        ob.select_set(objects is None or ob in objects)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True,
                              export_image_format="JPEG", export_jpeg_quality=85,
                              export_extras=True, use_selection=objects is not None)


def render(path, cam_loc, target, hide_roofs=False, lens=35, res=(1000, 700)):
    scene = bpy.context.scene
    for ob in bpy.data.objects:
        if ob.name.startswith("Roof"):
            ob.hide_render = hide_roofs
    cam = bpy.data.objects.get("PreviewCam")
    if cam is None:
        cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
        scene.collection.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (Vector(target) - Vector(cam_loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)


def setup_render_scene():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    try:
        scene.cycles.use_denoising = True
    except Exception:
        pass
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.5
    sun.data.angle = math.radians(1.5)
    sun.rotation_euler = (math.radians(48), 0, math.radians(-35))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.45, 0.60, 0.85, 1)
    bg.inputs[1].default_value = 0.9
    scene.world = world


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="pompeii_house.glb")
    p.add_argument("--preview-dir", default=None)
    p.add_argument("--texdir", default="textures")
    p.add_argument("--split", action="store_true", help="also export body and roofs as separate GLBs")
    args = p.parse_args(argv)

    objs = build(args.texdir)
    export_glb(args.out)
    print(f"Exported {args.out} (pompeii-house {MODEL_VERSION})")
    if args.split:
        # ArcGIS places a GLB as one symbol, so roofs need their own file to be switchable
        stem = os.path.splitext(args.out)[0]
        roofs = [o for o in objs if o.name.startswith("Roof")]
        export_glb(f"{stem}_body.glb", [o for o in objs if o not in roofs])
        export_glb(f"{stem}_roofs.glb", roofs)
        print(f"Exported {stem}_body.glb and {stem}_roofs.glb")
    if args.preview_dir:
        os.makedirs(args.preview_dir, exist_ok=True)
        setup_render_scene()
        render(f"{args.preview_dir}/aerial.png", (-9, -14, 22), (7, 14, 0))
        render(f"{args.preview_dir}/aerial_no_roofs.png", (-9, -14, 22), (7, 14, 0), hide_roofs=True)
        render(f"{args.preview_dir}/street.png", (2.5, -4.6, 1.7), (8.5, 4, 2.8), lens=24)
        render(f"{args.preview_dir}/atrium.png", (7.0, 7.0, 1.6), (7.0, 17, 1.8), lens=20)
        # night: sun off, faint sky, so only the emissive flames and embers give light
        bpy.data.objects["Sun"].hide_render = True
        bpy.context.scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.03
        render(f"{args.preview_dir}/night_aerial.png", (-9, -14, 22), (7, 14, 0), hide_roofs=True)
        render(f"{args.preview_dir}/night_atrium.png", (7.0, 7.0, 1.6), (7.0, 17, 1.8), lens=20)
        print("Previews written")


if __name__ == "__main__":
    main(sys.argv[1:])
