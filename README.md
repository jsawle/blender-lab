# Blender Lab

Experiments with 3D models authored by Python scripts in Blender (run headless, no
Blender interface) and shown with the ArcGIS Maps SDK for JavaScript.

`index.html` tests the SDK 5 light-emitting materials and glow on two models:

- **Pompeii house at night** — a representative atrium house with oil lamps, braziers
  and a lararium flame. Roofs are a separate GLB so they can be switched off.
- **Earth's core** — a cutaway Earth with a glowing outer and inner core.

## Pipeline

```
pip install bpy scipy
python blender/pompeii_house.py --out models/pompeii_house.glb --split
python blender/earth_cutaway.py --out models/earth_cutaway.glb
python tools/model_manifest.py models      # real sizes, read by the page
```

Emissive parts are ordinary Blender materials with Emission set. The glTF exporter
writes them as `emissiveFactor`, and the page reads them with
`material.emissive.source: "emissive"`.

## Versions

| Part | Version |
| --- | --- |
| Lab page | 0.1.1 |
| Earth cutaway model | 0.2.0 |
| Pompeii house model | 0.2.0 |

The Pompeii house follows the proportions of William Gell's 1832 measurements of
the House of the Tragic Poet. It is not a survey of one building, and its placement
in Regio VI is approximate.
