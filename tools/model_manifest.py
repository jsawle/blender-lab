"""
Write models/manifest.json: each GLB's real size in metres and the model version.

ArcGIS (ObjectSymbol3DLayer) scales a glTF model to the `height` you give it,
keeping proportions. Passing each model's true height keeps it at real scale,
and keeps separately exported parts (house body + roofs) lined up.

    python tools/model_manifest.py models
"""
import json
import struct
import sys
from pathlib import Path

VERSIONS = {  # bump with the model's MODEL_VERSION in blender/*.py
    "earth_cutaway": "0.2.0",
    "pompeii_house": "0.2.0",
    "stratovolcano_cutaway": "0.1.0",
}


def glb_bounds(path):
    data = path.read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for node in gltf.get("nodes", []):
        if "mesh" not in node:
            continue
        t = node.get("translation", [0, 0, 0])
        for prim in gltf["meshes"][node["mesh"]]["primitives"]:
            acc = gltf["accessors"][prim["attributes"]["POSITION"]]
            for i in range(3):
                lo[i] = min(lo[i], acc["min"][i] + t[i])
                hi[i] = max(hi[i], acc["max"][i] + t[i])
    return lo, hi


def main(folder):
    out = {}
    for glb in sorted(Path(folder).glob("*.glb")):
        lo, hi = glb_bounds(glb)
        key = next((k for k in VERSIONS if glb.stem.startswith(k)), glb.stem)
        out[glb.name] = {
            "version": VERSIONS.get(key, "unknown"),
            # glTF is y-up: height is the y extent
            "height_m": round(hi[1] - lo[1], 4),
            "width_m": round(hi[0] - lo[0], 4),
            "depth_m": round(hi[2] - lo[2], 4),
            "min_y_m": round(lo[1], 4),
            "bytes": glb.stat().st_size,
        }
    (Path(folder) / "manifest.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "models")
