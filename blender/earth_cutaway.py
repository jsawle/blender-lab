"""
Earth cutaway model — Blender authoring script (lab test)
Model version: earth-cutaway 0.2.0
  0.2.0  cores are emissive (glow in ArcGIS SDK 5.x / three.js); 96 segments
  0.1.0  first build

Builds nested spheres for Earth's main layers, removes a wedge so the
layers show on the cut faces, and exports a Draco-compressed GLB for
Three.js or the ArcGIS Maps SDK.

Run headless (no Blender interface needed):
    pip install bpy            # Blender as a Python module
    python earth_cutaway.py --out earth_cutaway.glb [--preview preview.png]
    gltf-transform draco earth_cutaway.glb earth_cutaway.draco.glb   # compress

Scale: 1 scene unit = 1000 km. Radii from the PREM reference Earth model.
The crust is EXAGGERATED (100 km instead of ~7-70 km) so it is visible.
"""
import argparse
import math
import os
import sys

import bpy

MODEL_VERSION = "0.2.0"

# name, outer radius (km), colour (sRGB 0-1), emission strength (0 = none), note
LAYERS = [
    ("Crust",        6371, (0.55, 0.42, 0.30), 0.0, "Shown 100 km thick (exaggerated); real 7-70 km"),
    ("Upper mantle", 6271, (0.85, 0.38, 0.16), 0.0, "To 660 km depth"),
    ("Lower mantle", 5711, (0.62, 0.15, 0.10), 0.0, "660-2,891 km depth"),
    ("Outer core",   3480, (0.95, 0.62, 0.12), 1.0, "Liquid iron-nickel, 2,891-5,150 km depth"),
    ("Inner core",   1221, (1.00, 0.88, 0.45), 1.0, "Solid iron-nickel, 5,150-6,371 km depth"),
]

SEGMENTS = 96    # smoothness around the equator
RINGS = 47       # odd, so no ring sits exactly on the cut plane


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def make_material(name, rgb, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    lin = (*[srgb_to_linear(c) for c in rgb], 1.0)
    bsdf.inputs["Base Color"].default_value = lin
    bsdf.inputs["Roughness"].default_value = 0.7
    if emission > 0:
        # exported as glTF emissiveFactor; ArcGIS reads it with emissive source "emissive"
        bsdf.inputs["Emission Color"].default_value = lin
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build(wedge_deg=90.0):
    clear_scene()

    # Wedge cutter: a box covering one quadrant, upper half only (classic cutaway)
    bpy.ops.mesh.primitive_cube_add(size=1)
    cutter = bpy.context.active_object
    cutter.name = "Cutter"
    cutter.scale = (10, 10, 10)
    cutter.location = (5, 5, 5)          # occupies x>0, y>0, z>0
    # bake scale AND location so the box's corner sits on the Earth's centre
    # and later rotation pivots about the centre
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=True)
    # turn the opening to face the -y/+x viewer (azimuth -45 degrees)
    cutter.rotation_euler[2] = math.radians(-90)

    def sphere(name, r):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=SEGMENTS, ring_count=RINGS, radius=r)
        ob = bpy.context.active_object
        ob.name = name
        ob.data.name = name
        # small twist so meridian edges don't lie on the cut planes
        ob.rotation_euler[2] = math.radians(360 / SEGMENTS / 2)
        bpy.ops.object.transform_apply(rotation=True)
        return ob

    def subtract(ob, cutter_ob):
        mod = ob.modifiers.new("Cut", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.solver = "EXACT"
        mod.object = cutter_ob
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier=mod.name)

    objects = []
    for i, (name, radius_km, rgb, emission, _) in enumerate(LAYERS):
        ob = sphere(name, radius_km / 1000.0)
        ob.data.materials.append(make_material(name, rgb, emission))

        # hollow it out down to the next layer, so each layer's cut face is a
        # ring of its own (solid nested spheres would overlap on the cut plane)
        if i + 1 < len(LAYERS):
            inner = sphere("_inner", LAYERS[i + 1][1] / 1000.0)
            subtract(ob, inner)
            bpy.data.objects.remove(inner, do_unlink=True)

        subtract(ob, cutter)
        bpy.ops.object.select_all(action="DESELECT")
        ob.select_set(True)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
        objects.append(ob)

    bpy.data.objects.remove(cutter, do_unlink=True)
    return objects


def export_glb(path):
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_apply=True,
        export_yup=True,
        # Draco isn't bundled with the pip build of Blender; compress afterwards:
        #   gltf-transform draco earth_cutaway.glb earth_cutaway.draco.glb
        export_extras=True,
    )


def render_preview(path):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 32
    scene.render.resolution_x = 900
    scene.render.resolution_y = 700
    scene.render.film_transparent = True

    bpy.ops.object.camera_add(location=(14, -14, 10))
    cam = bpy.context.active_object
    direction = -cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 50
    scene.camera = cam

    bpy.ops.object.light_add(type="SUN", location=(5, -10, 10))
    sun = bpy.context.active_object
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(40), math.radians(10), math.radians(30))

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    scene.world = world

    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="earth_cutaway.glb")
    p.add_argument("--preview", default=None)
    args = p.parse_args(argv)

    objs = build()
    for ob in objs:
        ob["model_version"] = MODEL_VERSION
    export_glb(args.out)
    print(f"Exported {args.out} (earth-cutaway {MODEL_VERSION})")
    if args.preview:
        render_preview(args.preview)
        print(f"Preview {args.preview}")


if __name__ == "__main__":
    main(sys.argv[1:])
