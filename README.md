# RCT Cycles Graphics

A Blender add-on for rendering [OpenRCT2](https://openrct2.io) object sprites
with **Cycles**, in the visual style of the original RollerCoaster Tycoon 2
graphics. It is a modern successor of the Blender 2.79-only
[RCT Graphics Helper](https://github.com/OpenRCT2/Blender-RCT-Graphics).

- Works with Blender 4.2 LTS and newer (tested on Blender 5.1).
- No ImageMagick: all post-processing is done in Python/numpy inside Blender.

See [specifications.md](specifications.md) for the original goals.

## Installing

1. Run `python3 tools/build_zip.py` (or download a release zip).
2. In Blender: *Edit > Preferences > Add-ons > Install from Disk...* and pick
   the zip, then enable **RCT Cycles Graphics**.
